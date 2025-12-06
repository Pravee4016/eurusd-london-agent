"""
Data Fetching Module for EUR/USD Forex Trading
Retrieves real-time OHLCV data using Finnhub API
Includes caching and error handling mechanisms
"""

import finnhub
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import json
import os
import logging
from typing import Dict, List, Optional
import time
import pytz

from config.settings import (
    FINNHUB_API_KEY,
    CACHE_DIR,
    INSTRUMENTS,
    DEBUG_MODE,
    TIME_ZONE,
)

logger = logging.getLogger(__name__)


class DataFetcher:
    """Fetch real-time forex data with caching & error handling"""

    def __init__(self):
        # Initialize Finnhub client
        self.finnhub_client = finnhub.Client(api_key=FINNHUB_API_KEY)
        self.cache = {}
        self.cache_timestamps = {}
        logger.info("📊 DataFetcher initialized with Finnhub API")

    # =========================================================================
    # FOREX DATA FETCHING
    # =========================================================================

    def fetch_forex_data(self, instrument: str = "EURUSD", retries: int = 3) -> Optional[Dict]:
        """
        Fetch real-time forex quote data.

        Args:
            instrument: 'EURUSD' (maps to OANDA:EUR_USD in Finnhub)
            retries: Number of retry attempts

        Returns:
            Dict with current price data or None if failed
        """
        if instrument not in INSTRUMENTS:
            logger.error(f"❌ Unknown instrument: {instrument}")
            return None

        symbol = INSTRUMENTS[instrument]["symbol"]

        for attempt in range(retries):
            try:
                logger.info(f"📡 Fetching forex quote for {symbol} (attempt {attempt + 1}/{retries})")
                
                # Get forex quote from Finnhub
                quote = self.finnhub_client.quote(symbol)
                
                if not quote or quote.get("c") == 0:
                    logger.warning(f"⚠️ Empty or invalid quote data for {symbol}")
                    time.sleep(1)
                    continue

                # Format response similar to NSE data structure
                forex_data = {
                    "symbol": instrument,
                    "last_price": quote["c"],  # Current price
                    "open": quote["o"],  # Open price of the day
                    "high": quote["h"],  # High price of the day
                    "low": quote["l"],  # Low price of the day
                    "previous_close": quote["pc"],  # Previous close price
                    "change": quote["c"] - quote["pc"],
                    "change_percent": ((quote["c"] - quote["pc"]) / quote["pc"] * 100) if quote["pc"] else 0,
                    "timestamp": datetime.now(pytz.timezone(TIME_ZONE)),
                }

                logger.info(
                    f"✅ {instrument}: {forex_data['last_price']:.4f} "
                    f"(H: {forex_data['high']:.4f}, L: {forex_data['low']:.4f})"
                )

                return forex_data

            except finnhub.FinnhubAPIException as e:
                logger.error(f"❌ Finnhub API error: {e}")
                # If 403 (forbidden - free tier doesn't have forex), fall back to yfinance
                if "403" in str(e) or "don't have access" in str(e).lower():
                    logger.info("📡 Falling back to yfinance for EUR/USD data...")
                    return self._fetch_forex_yfinance(instrument)
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                continue
            except Exception as e:
                logger.error(f"❌ Unexpected error fetching forex data: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                continue

        logger.error(f"❌ Failed to fetch forex data after {retries} attempts")
        return None

    def fetch_historical_data(
        self,
        instrument: str,
        resolution: str = "5",  # 5-minute candles
        days_back: int = 5,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical forex candle data using Finnhub.

        Args:
            instrument: 'EURUSD'
            resolution: '1', '5', '15', '30', '60', 'D' (Finnhub format)
            days_back: Number of days of historical data

        Returns:
            DataFrame with OHLCV or None
        """
        if instrument not in INSTRUMENTS:
            logger.error(f"❌ Unknown instrument: {instrument}")
            return None

        symbol = INSTRUMENTS[instrument]["symbol"]

        try:
            # Calculate time range (Finnhub uses Unix timestamps)
            end_time = int(datetime.now().timestamp())
            start_time = int((datetime.now() - timedelta(days=days_back)).timestamp())

            logger.info(
                f"📊 Fetching {days_back}d historical data for {symbol} "
                f"(resolution: {resolution})"
            )

            # Fetch forex candles from Finnhub
            candles = self.finnhub_client.forex_candles(
                symbol=symbol,
                resolution=resolution,
                _from=start_time,
                to=end_time
            )

            if candles["s"] != "ok":
                logger.error(f"❌ Finnhub returned status: {candles['s']}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(candles["t"], unit="s"),
                "open": candles["o"],
                "high": candles["h"],
                "low": candles["l"],
                "close": candles["c"],
                "volume": candles["v"],
            })

            # Set timestamp as index
            df.set_index("timestamp", inplace=True)
            df.index = df.index.tz_localize("UTC").tz_convert(TIME_ZONE)

            # Rename columns to match expected format
            df = df.rename(columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            })

            logger.info(
                f"✅ Fetched {len(df)} candles for {instrument} "
                f"({df.index[0]} to {df.index[-1]})"
            )

            return df

        except finnhub.FinnhubAPIException as e:
            logger.error(f"❌ Finnhub API error: {e}")
            # Fall back to yfinance for free tier
            if "403" in str(e) or "don't have access" in str(e).lower():
                logger.info("📡 Falling back to yfinance for historical data...")
                return self._fetch_historical_yfinance(instrument, resolution, days_back)
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching historical data: {e}")
            return None

    def get_historical_data(
        self, 
        instrument: str, 
        interval: str, 
        bars: int
    ) -> Optional[pd.DataFrame]:
        """
        Get historical data with bars-based signature (for choppy session filter).
        
        Args:
            instrument: 'EURUSD'
            interval: '5', '15', etc (Finnhub resolution)
            bars: Number of bars needed
            
        Returns:
            DataFrame with OHLCV or None
        """
        # Convert interval to Finnhub resolution format
        resolution_map = {"5m": "5", "15m": "15", "1h": "60", "1d": "D"}
        resolution = resolution_map.get(interval, interval)

        # Estimate days needed based on bars and interval
        if resolution == "5":
            days_back = max(5, (bars * 5) // (60 * 24) + 2)  # 5-min bars
        elif resolution == "15":
            days_back = max(5, (bars * 15) // (60 * 24) + 2)  # 15-min bars
        elif resolution == "60":
            days_back = max(5, (bars * 60) // (60 * 24) + 2)  # 1-hour bars
        else:
            days_back = bars + 5  # Daily bars

        df = self.fetch_historical_data(instrument, resolution, days_back)
        
        if df is not None and len(df) > bars:
            # Return only the requested number of bars
            df = df.tail(bars)
        
        return df

    def get_previous_day_stats(self, instrument: str) -> Optional[Dict]:
        """
        Fetch Previous Day High (PDH) and Low (PDL) for forex.
        
        Note: For 24-hour forex markets, "previous day" is defined as
        the 00:00-23:59 GMT period.
        """
        try:
            # Fetch daily data
            df = self.fetch_historical_data(instrument, resolution="D", days_back=2)
            
            if df is None or len(df) < 2:
                logger.warning(f"⚠️ Insufficient daily data for {instrument}")
                return None

            # Get previous day (second to last)
            prev_day = df.iloc[-2]
            
            stats = {
                "pdh": prev_day["High"],
                "pdl": prev_day["Low"],
                "pdc": prev_day["Close"],
                "date": prev_day.name.date(),
            }

            logger.info(
                f"📅 {instrument} Previous Day: "
                f"H={stats['pdh']:.4f}, L={stats['pdl']:.4f}, C={stats['pdc']:.4f}"
            )

            return stats

        except Exception as e:
            logger.error(f"❌ Error fetching previous day stats: {e}")
            return None

    def get_opening_range_stats(self, instrument: str) -> Optional[Dict]:
        """
        Fetch High/Low of the London session opening range (first 30 minutes).
        
        Opening range: 08:00-08:30 GMT
        """
        try:
            # Fetch 5-minute data for today
            df = self.fetch_historical_data(instrument, resolution="5", days_back=1)
            
            if df is None or len(df) == 0:
                logger.warning(f"⚠️ No intraday data for {instrument}")
                return None

            # Filter for London session open (08:00-08:30 GMT)
            london_tz = pytz.timezone("Europe/London")
            today = datetime.now(london_tz).date()
            
            # Convert to London time for filtering
            df_london = df.copy()
            df_london.index = df_london.index.tz_convert(london_tz)
            
            # Get today's data
            df_today = df_london[df_london.index.date == today]
            
            if len(df_today) == 0:
                logger.warning(f"⚠️ No data for today for {instrument}")
                return None

            # Filter for opening range (08:00-08:30)
            opening_range = df_today.between_time("08:00", "08:30")
            
            if len(opening_range) == 0:
                logger.warning(f"⚠️ No opening range data yet for {instrument}")
                return None

            stats = {
                "or_high": opening_range["High"].max(),
                "or_low": opening_range["Low"].min(),
                "or_range": opening_range["High"].max() - opening_range["Low"].min(),
                "time_period": "08:00-08:30 GMT",
            }

            logger.info(
                f"🕗 {instrument} Opening Range: "
                f"H={stats['or_high']:.4f}, L={stats['or_low']:.4f}, "
                f"Range={stats['or_range']*10000:.1f} pips"
            )

            return stats

        except Exception as e:
            logger.error(f"❌ Error fetching opening range: {e}")
            return None

    # =========================================================================
    # YFINANCE FALLBACK (FREE TIER)
    # =========================================================================

    def _fetch_forex_yfinance(self, instrument: str = "EURUSD") -> Optional[Dict]:
        """Fetch real-time forex data using yfinance (free)."""
        try:
            ticker_map = {"EURUSD": "EURUSD=X"}
            ticker = ticker_map.get(instrument, "EURUSD=X")
            
            forex = yf.Ticker(ticker)
            df = forex.history(period="1d", interval="5m")
            
            if df.empty:
                logger.error("❌ No data from yfinance")
                return None
            
            latest = df.iloc[-1]
            first = df.iloc[0]
            
            forex_data = {
                "symbol": instrument,
                "last_price": float(latest["Close"]),
                "open": float(first["Open"]),
                "high": float(df["High"].max()),
                "low": float(df["Low"].min()),
                "previous_close": float(df.iloc[-2]["Close"]) if len(df) > 1 else float(latest["Close"]),
                "change": float(latest["Close"] - first["Open"]),
                "change_percent": float((latest["Close"] - first["Open"]) / first["Open"] * 100),
                "timestamp": datetime.now(pytz.timezone(TIME_ZONE)),
            }
            
            logger.info(
                f"✅ {instrument} (yfinance): {forex_data['last_price']:.4f} "
                f"(H: {forex_data['high']:.4f}, L: {forex_data['low']:.4f})"
            )
            
            return forex_data
            
        except Exception as e:
            logger.error(f"❌ yfinance error: {e}")
            return None
    
    def _fetch_historical_yfinance(self, instrument: str, resolution: str, days_back: int) -> Optional[pd.DataFrame]:
        """Fetch historical forex data using yfinance (free)."""
        try:
            ticker_map = {"EURUSD": "EURUSD=X"}
            ticker = ticker_map.get(instrument, "EURUSD=X")
            
            # Map Finnhub resolution to yfinance interval
            interval_map = {"1": "1m", "5": "5m", "15": "15m", "60": "1h", "D": "1d"}
            interval = interval_map.get(resolution, "5m")
            
            # Calculate period
            period_map = {1: "1d", 2: "2d", 5: "5d", 10: "1mo", 30: "1mo"}
            period = period_map.get(days_back, f"{days_back}d")
            
            logger.info(f"📊 Fetching {period} historical data from yfinance (interval: {interval})")
            
            forex = yf.Ticker(ticker)
            df = forex.history(period=period, interval=interval)
            
            if df.empty:
                logger.error("❌ No historical data from yfinance")
                return None
            
            # Rename columns to match expected format
            df.index = df.index.tz_convert(TIME_ZONE)
            df = df.rename(columns={
                "Open": "Open",
                "High": "High",
                "Low": "Low",
                "Close": "Close",
                "Volume": "Volume",
            })
            
            # Keep only OHLCV columns
            df = df[["Open", "High", "Low", "Close", "Volume"]]
            
            logger.info(
                f"✅ Fetched {len(df)} candles from yfinance "
                f"({df.index[0]} to {df.index[-1]})"
            )
            
            return df
            
        except Exception as e:
            logger.error(f"❌ yfinance historical error: {e}")
            return None

    # =========================================================================
    # VALIDATION & CACHING
    # =========================================================================

    def _is_cache_valid(self, cache_key: str, ttl: int = 60) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self.cache_timestamps:
            return False

        age = time.time() - self.cache_timestamps[cache_key]
        return age < ttl

    def clear_cache(self, instrument: Optional[str] = None):
        """Clear cache for specific instrument or all."""
        if instrument:
            keys_to_remove = [k for k in self.cache if instrument in k]
            for key in keys_to_remove:
                del self.cache[key]
                del self.cache_timestamps[key]
            logger.info(f"🗑️ Cleared cache for {instrument}")
        else:
            self.cache.clear()
            self.cache_timestamps.clear()
            logger.info("🗑️ Cleared all cache")

    # =========================================================================
    # PREPROCESSING & UTILITIES
    # =========================================================================

    def preprocess_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Preprocess OHLCV data for analysis.

        Adds:
        - hl_range
        - hl_mid
        - co_change
        - typical_price
        """
        if df is None or len(df) == 0:
            return df

        df = df.copy()

        # Calculate derived fields
        df["hl_range"] = df["High"] - df["Low"]
        df["hl_mid"] = (df["High"] + df["Low"]) / 2
        df["co_change"] = df["Close"] - df["Open"]
        df["typical_price"] = (df["High"] + df["Low"] + df["Close"]) / 3

        # Calculate ATR in pips (for EUR/USD)
        df["atr_pips"] = df["hl_range"] * 10000

        logger.debug(f"✅ Preprocessed {len(df)} candles")
        return df

    def save_to_csv(
        self, df: pd.DataFrame, instrument: str, filename: Optional[str] = None
    ):
        """Save data to CSV for offline analysis."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{instrument}_{timestamp}.csv"

        filepath = os.path.join(CACHE_DIR, filename)
        df.to_csv(filepath)
        logger.info(f"💾 Saved data to {filepath}")

    def load_from_csv(self, filename: str) -> Optional[pd.DataFrame]:
        """Load data from CSV."""
        filepath = os.path.join(CACHE_DIR, filename)
        if not os.path.exists(filepath):
            logger.error(f"❌ File not found: {filepath}")
            return None

        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        logger.info(f"📂 Loaded {len(df)} rows from {filepath}")
        return df


# =========================================================================
# UTILITY
# =========================================================================


_fetcher: Optional[DataFetcher] = None


def get_data_fetcher() -> DataFetcher:
    """Singleton pattern for DataFetcher."""
    global _fetcher
    if _fetcher is None:
        _fetcher = DataFetcher()
    return _fetcher


def test_data_fetcher():
    """Test the data fetcher with EUR/USD."""
    logger.info("🧪 Testing DataFetcher with EUR/USD...")

    fetcher = get_data_fetcher()

    # Test real-time quote
    forex_data = fetcher.fetch_forex_data("EURUSD")
    if forex_data:
        print(f"\n✅ Real-time EUR/USD: {forex_data['last_price']:.4f}")
    else:
        print("\n❌ Failed to fetch real-time data")

    # Test historical data
    df = fetcher.fetch_historical_data("EURUSD", resolution="5", days_back=2)
    if df is not None and len(df) > 0:
        print(f"\n✅ Historical data: {len(df)} candles")
        print(df.tail())
    else:
        print("\n❌ Failed to fetch historical data")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    test_data_fetcher()
