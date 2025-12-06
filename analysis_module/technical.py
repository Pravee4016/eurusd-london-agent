"""
Technical Analysis Module
Core calculations: PDH/PDL, Support/Resistance, Volume, Breakouts, Advanced TA
Includes debugging output for signal validation
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, time
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

from config.settings import (
    SR_CLUSTER_TOLERANCE_PIPS,
    MIN_SR_TOUCHES,
    LOOKBACK_BARS,
    MIN_VOLUME_RATIO,
    VOLUME_PERIOD,
    BREAKOUT_CONFIRMATION_PIPS,
    RETEST_ZONE_PIPS,
    MIN_RSI_BULLISH,
    MAX_RSI_BEARISH,
    RSI_PERIOD,
    ATR_PERIOD,
    EMA_SHORT,
    EMA_LONG,
    MIN_RISK_REWARD_RATIO,
    ATR_SL_MULTIPLIER,
    ATR_TP_MULTIPLIER,
    DEBUG_MODE,
    ROUND_NUMBER_LEVELS,
    ROUND_NUMBER_LEVELS,
    TIME_ZONE,
    ASIAN_SESSION_START,
    ASIAN_SESSION_END,
)

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Signal types"""

    BULLISH_BREAKOUT = "BULLISH_BREAKOUT"
    BEARISH_BREAKOUT = "BEARISH_BREAKOUT"
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    RETEST_SETUP = "RETEST_SETUP"
    INSIDE_BAR = "INSIDE_BAR"
    SUPPORT_BOUNCE = "SUPPORT_BOUNCE"
    RESISTANCE_BOUNCE = "RESISTANCE_BOUNCE"
    BULLISH_PIN_BAR = "BULLISH_PIN_BAR"
    BEARISH_PIN_BAR = "BEARISH_PIN_BAR"
    BULLISH_ENGULFING = "BULLISH_ENGULFING"
    BEARISH_ENGULFING = "BEARISH_ENGULFING"


@dataclass
class Signal:
    """Trading signal data class"""

    signal_type: SignalType
    instrument: str
    timeframe: str
    price_level: float
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float  # 0-100%
    volume_confirmed: bool
    momentum_confirmed: bool
    risk_reward_ratio: float
    timestamp: pd.Timestamp
    description: str
    debug_info: Dict = None


@dataclass
class TechnicalLevels:
    """Support/Resistance levels and related metrics"""

    support_levels: List[float]
    resistance_levels: List[float]
    pivot: float
    pdh: float
    pdl: float
    atr: float
    atr: float
    volatility_score: float
    asian_high: float = 0.0
    asian_low: float = 0.0


class TechnicalAnalyzer:
    """Main technical analysis engine"""

    def __init__(self, instrument: str):
        self.instrument = instrument
        logger.info(f"🔬 TechnicalAnalyzer initialized for {instrument}")

    # =====================================================================
    # ASIAN RANGE (TOKYO SESSION)
    # =====================================================================

    def get_asian_range(self, df: pd.DataFrame) -> Optional[Dict]:
        """
        Calculate Asian Session High/Low (00:00 - 08:00 GMT).
        These levels often act as support/resistance during London/NY.
        """
        try:
            import pytz
            london_tz = pytz.timezone(TIME_ZONE)
            
            # Ensure index is datetime
            df = df.copy()
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)

            # Convert to London time if not already (assuming input is UTC or London)
            # Safe check: if no tz, localize to UTC then convert. If tz, convert.
            if df.index.tz is None:
                 df.index = df.index.tz_localize("UTC").tz_convert(london_tz)
            else:
                 df.index = df.index.tz_convert(london_tz)

            # Get today's data (or the last complete trading day in view)
            # We want the MOST RECENT completed Asian session relative to the latest data point
            last_timestamp = df.index[-1]
            current_day = last_timestamp.date()
            
            # Filter for current day's Asian session
            todays_data = df[df.index.date == current_day]
            
            # Parse start/end times
            start_h, start_m = map(int, ASIAN_SESSION_START.split(":"))
            end_h, end_m = map(int, ASIAN_SESSION_END.split(":"))
            
            asian_data = todays_data.between_time(
                time(start_h, start_m), 
                time(end_h, end_m)
            )
            
            if asian_data.empty:
                # If we are strictly BEFORE Asian session (unlikely in London agent)
                # or if the data is just missing
                return None
                
            high = float(asian_data["high"].max())
            low = float(asian_data["low"].min())
            
            logger.info(
                f"🌏 Asian Range ({ASIAN_SESSION_START}-{ASIAN_SESSION_END}) | "
                f"High: {high:.4f} | Low: {low:.4f}"
            )
            
            return {"high": high, "low": low}
            
        except Exception as e:
            logger.warning(f"⚠️ Asian range calculation failed: {e}")
            return None

    # =====================================================================
    # PDH / PDL
    # =====================================================================

    def calculate_pdh_pdl(
        self, df: pd.DataFrame
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Calculate Previous Day High & Low.

        Uses daily resample of df.
        """
        try:
            df = df.copy()
            df.index = pd.to_datetime(df.index)

            daily_df = df.resample("D").agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )

            if len(daily_df) < 2:
                logger.warning("❌ Not enough daily data for PDH/PDL")
                return None, None

            prev_day = daily_df.iloc[-2]
            pdh = float(prev_day["high"])
            pdl = float(prev_day["low"])

            current_open = float(daily_df.iloc[-1]["open"])
            gap_pct = (
                ((current_open - pdh) / pdh) * 100.0 if pdh > 0 else 0.0
            )

            logger.info(
                f"📊 PDH/PDL | PDH: {pdh:.2f} | PDL: {pdl:.2f} | "
                f"Gap% vs PDH(open): {gap_pct:.2f}%"
            )

            if DEBUG_MODE:
                logger.debug(
                    f"   PDH: {pdh:.2f}, PDL: {pdl:.2f}, "
                    f"Current open: {current_open:.2f}, Gap%: {gap_pct:.2f}"
                )

            return pdh, pdl

        except Exception as e:
            logger.error(f"❌ PDH/PDL calculation failed: {str(e)}")
            return None, None

    # =====================================================================
    # SUPPORT / RESISTANCE
    # =====================================================================

    def calculate_support_resistance(self, df: pd.DataFrame) -> TechnicalLevels:
        """
        Calculate Support/Resistance levels with clustering.
        """
        try:
            df = df.copy()
            lookback = min(LOOKBACK_BARS, len(df))
            df_sub = df.tail(lookback)

            highs = df_sub["high"].values
            lows = df_sub["low"].values

            support_levels = self._find_support_levels(lows)
            resistance_levels = self._find_resistance_levels(highs)

            # Calculate Asian Range
            asian_range = self.get_asian_range(df)
            asian_high = asian_range["high"] if asian_range else 0.0
            asian_low = asian_range["low"] if asian_range else 0.0

            # Include Asian levels in main clusters
            if asian_high > 0:
                resistance_levels.append(asian_high)
            if asian_low > 0:
                support_levels.append(asian_low)

            support_clusters = self._cluster_levels(support_levels)
            resistance_clusters = self._cluster_levels(resistance_levels)

            pdh, pdl = self.calculate_pdh_pdl(df)
            pivot_std, _ = self._calculate_pivots(df_sub)

            atr = self._calculate_atr(df_sub)
            volatility_score = self._calculate_volatility_score(df_sub)

            logger.info(
                "✅ S/R Calculated | "
                f"Supports: {len(support_clusters)} | "
                f"Resistances: {len(resistance_clusters)}"
            )

            if DEBUG_MODE:
                logger.debug(
                    "   Supports: "
                    f"{[f'{s:.2f}' for s in support_clusters[:5]]}"
                )
                logger.debug(
                    "   Resistances: "
                    f"{[f'{r:.2f}' for r in resistance_clusters[:5]]}"
                )

            return TechnicalLevels(
                support_levels=sorted(support_clusters),
                resistance_levels=sorted(resistance_clusters, reverse=True),
                pivot=pivot_std,
                pdh=pdh or 0.0,
                pdl=pdl or 0.0,
                atr=atr,
                volatility_score=volatility_score,
                asian_high=asian_high,
                asian_low=asian_low,
            )

        except Exception as e:
            logger.error(f"❌ S/R calculation failed: {str(e)}")
            return TechnicalLevels([], [], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def _find_support_levels(self, lows: np.ndarray) -> List[float]:
        """Identify support levels via local minima."""
        supports: List[float] = []
        for i in range(1, len(lows) - 1):
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                supports.append(float(lows[i]))
        return supports

    def _find_resistance_levels(self, highs: np.ndarray) -> List[float]:
        """Identify resistance levels via local maxima."""
        resistances: List[float] = []
        for i in range(1, len(highs) - 1):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                resistances.append(float(highs[i]))
        return resistances

    def _cluster_levels(
        self, levels: List[float], tolerance_pips: float = SR_CLUSTER_TOLERANCE_PIPS
    ) -> List[float]:
        """Cluster nearby levels together (pip-based for forex)."""
        if not levels:
            return []

        sorted_levels = sorted(levels)
        clusters: List[float] = []
        current_cluster: List[float] = [sorted_levels[0]]
        
        # Convert pips to price difference (1 pip = 0.0001 for EUR/USD)
        pip_value = 0.0001
        tolerance = tolerance_pips * pip_value

        for level in sorted_levels[1:]:
            cluster_mean = float(np.mean(current_cluster))

            if abs(level - cluster_mean) <= tolerance:
                current_cluster.append(level)
            else:
                clusters.append(float(np.mean(current_cluster)))
                current_cluster = [level]

        clusters.append(float(np.mean(current_cluster)))
        
        # Also include psychological round number levels (00, 20, 50, 80)
        rounded_levels = self._add_round_number_levels(clusters)

        if DEBUG_MODE:
            logger.debug(
                f"   Clustered {len(sorted_levels)} into {len(clusters)} clusters "
                f"+ {len(rounded_levels) - len(clusters)} round numbers"
            )

        return rounded_levels
    
    def _add_round_number_levels(self, levels: List[float]) -> List[float]:
        """Add psychological round number levels for forex."""
        if not levels:
            return levels
        
        # Get price range
        min_level = min(levels)
        max_level = max(levels)
        
        round_numbers = []
        # Generate round numbers in range (e.g., 1.0800, 1.0850, 1.0900, 1.1000)
        for hundredth in range(int(min_level * 100), int(max_level * 100) + 1):
            price = hundredth / 100.0
            # Check if ends in 00, 20, 50, or 80 pips
            pips = int((price * 10000) % 100)
            if pips in ROUND_NUMBER_LEVELS:
                # Only add if not too close to existing level
                if not any(abs(price - level) < 0.0010 for level in levels):
                    round_numbers.append(price)
        
        all_levels = sorted(levels + round_numbers)
        return all_levels

    def _calculate_pivots(
        self, df: pd.DataFrame
    ) -> Tuple[float, float]:
        """Calculate pivot points (Standard & simple Fibonacci-style)."""
        try:
            last_row = df.iloc[-1]
            high, low, close = (
                float(last_row["high"]),
                float(last_row["low"]),
                float(last_row["close"]),
            )

            pivot_std = (high + low + close) / 3.0
            pivot_fib = (high + low) / 2.0

            return pivot_std, pivot_fib

        except Exception as e:
            logger.warning(f"⚠️  Pivot calculation failed: {str(e)}")
            return 0.0, 0.0

    # =====================================================================
    # VOLUME ANALYSIS
    # =====================================================================

    def check_volume_confirmation(
        self, df: pd.DataFrame
    ) -> Tuple[bool, float, str]:
        """
        Check if current candle has volume confirmation.
        Returns True if volume is zero (index data) to avoid blocking signals.
        """
        try:
            df = df.copy()
            if len(df) < VOLUME_PERIOD + 2:
                return False, 0.0, ""

            # Check if volume data exists (indices often have 0 volume)
            total_volume = df["volume"].sum()
            if total_volume == 0:
                logger.debug("⚠️  Zero volume detected (Index data) - Bypassing volume check")
                return True, 1.0, "Index (No Vol)"

            current_vol = float(df["volume"].iloc[-1])
            avg_vol = float(
                df["volume"].iloc[-VOLUME_PERIOD - 1 : -1].mean()
            )
            ratio = current_vol / avg_vol if avg_vol > 0 else 0.0
            is_confirmed = ratio >= MIN_VOLUME_RATIO

            info = (
                f"Vol: {current_vol:.0f} | Avg: {avg_vol:.0f} | Ratio: {ratio:.2f}x"
            )

            if is_confirmed:
                logger.info(f"✅ Volume confirmed | {info}")
            else:
                logger.warning(f"⚠️  Low volume | {info}")

            if DEBUG_MODE:
                logger.debug(f"   Volume threshold: {MIN_VOLUME_RATIO}x")

            return is_confirmed, ratio, info

        except Exception as e:
            logger.error(f"❌ Volume check failed: {str(e)}")
            # Default to True on error to not block price signals if data is bad
            return True, 0.0, "Error (Bypassed)"

    # =====================================================================
    # OPENING RANGE BREAKOUT (ORB)
    # =====================================================================

    def get_opening_range(self, df: pd.DataFrame, duration_mins: int = 30) -> Optional[Dict]:
        """
        Calculate opening range (first N minutes of London session).
        
        London session opens at 08:00 GMT. Opening range breakouts are
        highly reliable in forex, especially EUR/USD.
        
        Args:
            df: 5-minute OHLC data with datetime index
            duration_mins: 30 minutes (default for London session)
        
        Returns:
            Dict with ORB high/low/range or None if insufficient data
        """
        try:
            import pytz
            
            # London session opens at 08:00 GMT
            if duration_mins == 30:
                end_time = "08:30"
            elif duration_mins == 60:
                end_time = "09:00"
            else:
                end_time = "08:30"
            
            # Convert to London timezone
            london_tz = pytz.timezone(TIME_ZONE)
            df_london = df.copy()
            df_london.index = df_london.index.tz_convert(london_tz)
            
            # Filter to opening range
            opening_candles = df_london.between_time("08:00", end_time)
            
            if opening_candles.empty or len(opening_candles) < 2:
                return None
            
            orb_high = opening_candles["high"].max()
            orb_low = opening_candles["low"].min()
            orb_range = orb_high - orb_low
            orb_range_pips = orb_range * 10000  # Convert to pips
            
            logger.info(
                f"📊 Opening Range ({duration_mins}min) | "
                f"High: {orb_high:.4f} | Low: {orb_low:.4f} | Range: {orb_range_pips:.1f} pips"
            )
            
            return {
                "high": orb_high,
                "low": orb_low,
                "range": orb_range,
                "range_pips": orb_range_pips,
                "duration_mins": duration_mins
            }
        
        except Exception as e:
            logger.error(f"❌ Opening range calculation failed: {e}")
            return None

    # =====================================================================
    # HIGHER TF CONTEXT (15m)
    # =====================================================================

    def get_higher_tf_context(self, df_15m: pd.DataFrame, df_5m: pd.DataFrame = None, df_daily: pd.DataFrame = None) -> Dict:
        """
        Build higher timeframe context:
        - 15m Trend direction: UP / DOWN / FLAT
        - 15m RSI and EMAs
        - 5m VWAP and 20 EMA (for intraday setups)
        - Previous day trend
        """
        context = {
            "trend_direction": "FLAT",
            "ema_short_15": 0.0,
            "ema_long_15": 0.0,
            "rsi_15": 50.0,
            "vwap_5m": 0.0,
            "vwap_slope": "FLAT",
            "ema_20_5m": 0.0,
            "price_above_vwap": False,
            "price_above_ema20": False,
            "prev_day_trend": "FLAT",
        }

        try:
            # ====================
            # 15m Trend Analysis
            # ====================
            if df_15m is None or df_15m.empty:
                logger.warning("⚠️  get_higher_tf_context: empty 15m data")
                return context

            df = df_15m.copy().sort_index()

            if len(df) < max(EMA_LONG, RSI_PERIOD) + 5:
                logger.warning(
                    "⚠️  get_higher_tf_context: not enough 15m bars"
                )
                return context

            ema_short = df["close"].ewm(
                span=EMA_SHORT, adjust=False
            ).mean()
            ema_long = df["close"].ewm(span=EMA_LONG, adjust=False).mean()

            ema_short_15 = float(ema_short.iloc[-1])
            ema_long_15 = float(ema_long.iloc[-1])
            rsi_15 = float(self._calculate_rsi(df))

            if ema_short_15 > ema_long_15 and rsi_15 >= 55:
                trend = "UP"
            elif ema_short_15 < ema_long_15 and rsi_15 <= 45:
                trend = "DOWN"
            else:
                trend = "FLAT"

            context.update(
                {
                    "trend_direction": trend,
                    "ema_short_15": ema_short_15,
                    "ema_long_15": ema_long_15,
                    "rsi_15": rsi_15,
                }
            )

            # ====================
            # 5m VWAP and 20 EMA
            # ====================
            if df_5m is not None and not df_5m.empty and len(df_5m) >= 20:
                df_5m_copy = df_5m.copy().sort_index()
                
                # Calculate VWAP
                _, vwap_5m, vwap_slope = self._calculate_vwap(df_5m_copy)
                
                # Calculate 20 EMA on 5m
                ema_20 = df_5m_copy["close"].ewm(span=20, adjust=False).mean()
                ema_20_5m = float(ema_20.iloc[-1])
                
                # Current price vs VWAP and EMA
                current_price = float(df_5m_copy["close"].iloc[-1])
                price_above_vwap = current_price > vwap_5m
                price_above_ema20 = current_price > ema_20_5m
                
                context.update({
                    "vwap_5m": vwap_5m,
                    "vwap_slope": vwap_slope,
                    "ema_20_5m": ema_20_5m,
                    "price_above_vwap": price_above_vwap,
                    "price_above_ema20": price_above_ema20,
                })

            # ====================
            # Previous Day Trend
            # ====================
            if df_daily is not None:
                prev_day_trend = self._get_previous_day_trend(df_daily)
                context["prev_day_trend"] = prev_day_trend

            # ====================
            # Opening Range (ORB)
            # ====================
            if df_5m is not None:
                orb = self.get_opening_range(df_5m, duration_mins=15)
                if orb:
                    context["opening_range"] = orb
                    context["orb_high"] = orb["high"]
                    context["orb_low"] = orb["low"]
                    context["orb_range"] = orb["range"]

            logger.info(
                "📐 Higher TF context | "
                f"Trend15m: {trend} | "
                f"VWAP: {context.get('vwap_5m', 0):.2f} ({context.get('vwap_slope', 'N/A')}) | "
                f"20EMA: {context.get('ema_20_5m', 0):.2f} | "
                f"PrevDay: {context.get('prev_day_trend', 'N/A')}"
            )
            return context

        except Exception as e:
            logger.error(f"❌ get_higher_tf_context failed: {str(e)}")
            return context

    # =====================================================================
    # BREAKOUT QUALITY FILTERS
    # =====================================================================

    def _detect_consolidation(
        self, df: pd.DataFrame, lookback: int = 20
    ) -> Optional[Dict]:
        """
        Detect if price is consolidating (sideways range).
        
        High-quality breakouts come from consolidation, not random noise.
        
        Args:
            df: OHLCV DataFrame
            lookback: Bars to analyze
            
        Returns:
            {
                "is_consolidating": bool,
                "range_high": float,
                "range_low": float,
                "range_pct": float,
                "bars_in_range": int
            }
        """
        try:
            if df is None or len(df) < lookback:
                return None
            
            recent = df.tail(lookback)
            
            # Calculate range
            range_high = float(recent["high"].max())
            range_low = float(recent["low"].min())
            range_pct = ((range_high - range_low) / range_low) * 100.0
            
            # Consolidation criteria:
            # 1. Tight range (< 2% for intraday on indices)
            # 2. Majority of bars within this range (at least 70%)
            # 3. Minimum bars in consolidation (at least 8)
            
            is_tight = range_pct < 2.0
            
            # Count bars fully within range
            bars_in_range = sum(
                1 for _, row in recent.iterrows()
                if range_low <= row["low"] and row["high"] <= range_high
            )
            
            pct_in_range = bars_in_range / lookback
            is_consolidated = is_tight and pct_in_range >= 0.7 and bars_in_range >= 8
            
            result = {
                "is_consolidating": is_consolidated,
                "range_high": range_high,
                "range_low": range_low,
                "range_pct": range_pct,
                "bars_in_range": bars_in_range,
            }
            
            if is_consolidated:
                logger.info(
                    f"📦 Consolidation detected | Range: {range_low:.2f}-{range_high:.2f} "
                    f"({range_pct:.2f}%) | {bars_in_range}/{lookback} bars"
                )
            else:
                logger.debug(
                    f"⏭️ No consolidation | Range: {range_pct:.2f}% | "
                    f"Bars in range: {bars_in_range}/{lookback}"
                )
            
            return result
            
        except Exception as e:
            logger.warning(f"⚠️ Consolidation detection failed: {str(e)}")
            return None

    def _detect_volume_surge(
        self, df: pd.DataFrame
    ) -> Tuple[bool, float, str]:
        """
        Detect volume surge on current bar.
        
        Strong breakouts have volume surges, not just average volume.
        
        Criteria:
            - Current volume > 1.5x 20-bar average
            - AND Current volume > highest of last 5 bars
            
        Returns:
            (has_surge, surge_ratio, description)
        """
        try:
            if df is None or len(df) < 20:
                return False, 0.0, "Insufficient data"
            
            # Check if volume data exists
            if df["volume"].sum() == 0:
                logger.debug("⚠️ No volume data - bypassing surge check")
                return True, 1.0, "Index (No Vol)"
            
            current_vol = float(df["volume"].iloc[-1])
            avg_vol_20 = float(df["volume"].tail(20).mean())
            max_vol_5 = float(df["volume"].tail(6).iloc[:-1].max())  # Exclude current
            
            surge_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 0
            
            # Surge conditions
            above_average = surge_ratio >= 1.5
            above_recent = current_vol > max_vol_5
            
            has_surge = above_average and above_recent
            
            if has_surge:
                description = f"Volume surge: {surge_ratio:.2f}x avg, highest in 5 bars"
                logger.info(f"📊 {description}")
            else:
                description = f"No surge: {surge_ratio:.2f}x avg (need 1.5x + highest in 5)"
                logger.debug(f"⏭️ {description}")
            
            return has_surge, surge_ratio, description
            
        except Exception as e:
            logger.warning(f"⚠️ Volume surge detection failed: {str(e)}")
            # Default to allowing the trade if check fails
            return True, 1.0, "Error (bypassed)"

    def _is_valid_breakout_time(self) -> Tuple[bool, str]:
        """
        Check if current time is suitable for breakout trading (London session).
        
        London Session: 08:00-16:00 GMT
        
        Avoid:
            - First 5 mins (08:00-08:05): Initial volatility
            - Last hour (15:00-16:00): Pre-US session, lower follow-through
            
        Best breakout hours: 08:05-15:00
        
        Returns:
            (is_valid, reason)
        """
        try:
            import pytz
            
            london_tz = pytz.timezone(TIME_ZONE)
            now = datetime.now(london_tz).time()
            
            # First 5 minutes (initial volatility)
            if time(8, 0) <= now < time(8, 5):
                return False, "Initial volatility (08:00-08:05)"
            
            # Last hour (pre-US session)
            if time(15, 0) <= now < time(16, 0):
                return False, "Pre-US session (15:00-16:00)"
            
            # Good breakout window (main London session)
            if time(8, 5) <= now < time(15, 0):
                return True, "Optimal London breakout window"
            
            return False, "Outside London session hours"
            
        except Exception as e:
            logger.warning(f"⚠️ Time check failed: {str(e)}")
            return True, "Time check bypassed"

    # =====================================================================
    # BREAKOUT DETECTION WITH MTF
    # =====================================================================

    def detect_breakout(
        self,
        df: pd.DataFrame,
        support_resistance: TechnicalLevels,
        higher_tf_context: Dict,
    ) -> Optional[Signal]:
        """
        Detect high-quality breakout with multi-factor confirmation.
        
        Filters:
        1. Time of day (avoid choppy periods)
        2. Consolidation (must break from range)
        3. MTF Trend (15m alignment)
        4. Volume Surge (explosive move)
        5. RSI Momentum
        """
        try:
            if df is None or df.empty:
                return None

            # 1. Time of Day Filter
            is_valid_time, time_reason = self._is_valid_breakout_time()
            if not is_valid_time:
                # Log only occasionally to avoid spam
                if datetime.now().minute % 15 == 0:
                    logger.debug(f"⏭️ Breakout skipped: {time_reason}")
                return None

            df = df.copy()
            current = df.iloc[-1]
            current_price = float(current["close"])
            current_high = float(current["high"])
            current_low = float(current["low"])

            trend_dir = higher_tf_context.get("trend_direction", "FLAT")
            rsi_15 = float(higher_tf_context.get("rsi_15", 50.0))

            breakout_signal: Optional[Signal] = None

            rsi_5 = self._calculate_rsi(df)
            
            # 2. Volume Surge Check
            has_surge, surge_ratio, surge_desc = self._detect_volume_surge(df)
            
            # 3. Consolidation Check
            # We check this only if we find a potential breakout level
            consolidation = self._detect_consolidation(df)
            is_consolidating = consolidation["is_consolidating"] if consolidation else False

            # 4. Opening Range Breakout (ORB) Check
            orb = higher_tf_context.get("opening_range")
            is_orb_breakout = False
            orb_direction = None
            orb_boost = 0
            
            if orb:
                import pytz
                london_tz = pytz.timezone(TIME_ZONE)
                current_time = df.index[-1].tz_convert(london_tz).time()
                # Only check ORB after it's established (after 08:30 GMT)
                if current_time > time(8, 30):
                    pip_buffer = 5 * 0.0001  # 5 pip buffer for forex
                    
                    # Bullish ORB: price breaks above opening range high
                    if current_high > (orb["high"] + pip_buffer):
                        is_orb_breakout = True
                        orb_direction = "BULLISH"
                        orb_boost = 10  # Boost confidence for ORB breakouts
                        logger.info(
                            f"🚀 ORB BULLISH BREAKOUT | Price: {current_price:.4f} > "
                            f"ORB High: {orb['high']:.4f}"
                        )
                    
                    # Bearish ORB: price breaks below opening range low
                    elif current_low < (orb["low"] - pip_buffer):
                        is_orb_breakout = True
                        orb_direction = "BEARISH"
                        orb_boost = 10  # Boost confidence for ORB breakouts
                        logger.info(
                            f"📉 ORB BEARISH BREAKOUT | Price: {current_price:.4f} < "
                            f"ORB Low: {orb['low']:.4f}"
                        )

            # ------------------------
            # Bullish breakout
            # ------------------------
            if support_resistance.resistance_levels:
                nearest_resistance = float(
                    support_resistance.resistance_levels[0]
                )

                # Check for breakout (High > Resistance)
                if current_high > nearest_resistance:
                    
                    # Filter: Must be consolidating OR have massive volume surge
                    if not is_consolidating and not has_surge:
                        logger.info(
                            f"⏭️ Bullish breakout ignored (No consolidation/surge) | "
                            f"Vol: {surge_ratio:.1f}x"
                        )
                        return None
                        
                    # Filter: MTF Trend Alignment
                    mtf_ok = (
                        trend_dir == "UP"
                        and rsi_15 >= MIN_RSI_BULLISH
                    )

                    if not mtf_ok:
                        logger.info(
                            "⏭️  Bullish breakout ignored (MTF filter) | "
                            f"Trend15m: {trend_dir} | RSI15: {rsi_15:.1f}"
                        )
                    else:
                        logger.info(
                            "🚀 Bullish breakout candidate | "
                            f"Price: {current_price:.2f} > R: {nearest_resistance:.2f} | "
                            f"Consolidation: {is_consolidating} | Surge: {has_surge}"
                        )

                        atr = support_resistance.atr
                        sl = current_low - (atr * ATR_SL_MULTIPLIER)
                        tp = current_price + (atr * ATR_TP_MULTIPLIER)
                        risk_reward = (tp - current_price) / max(
                            current_price - sl, 1e-6
                        )

                        # Confidence Scoring
                        confidence = 60.0
                        if has_surge:
                            confidence += 10
                        if is_consolidating:
                            confidence += 10
                        if rsi_5 >= MIN_RSI_BULLISH:
                            confidence += 5
                        if trend_dir == "UP":
                            confidence += 10
                        if risk_reward >= MIN_RISK_REWARD_RATIO:
                            confidence += 5
                        # NEW: ORB boost
                        if is_orb_breakout and orb_direction == "BULLISH":
                            confidence += orb_boost

                        confidence = min(confidence, 95.0)

                        breakout_signal = Signal(
                            signal_type=SignalType.BULLISH_BREAKOUT,
                            instrument=self.instrument,
                            timeframe="5MIN",
                            price_level=nearest_resistance,
                            entry_price=current_price,
                            stop_loss=sl,
                            take_profit=tp,
                            confidence=confidence,
                            volume_confirmed=has_surge,
                            momentum_confirmed=(
                                rsi_5 >= MIN_RSI_BULLISH
                            ),
                            risk_reward_ratio=risk_reward,
                            timestamp=pd.Timestamp.now(),
                            description=(
                                f"Bullish breakout at {nearest_resistance:.2f} | "
                                f"RR: {risk_reward:.2f} | "
                                f"Vol Surge: {has_surge} | Consolidation: {is_consolidating}"
                                f"{' | ORB Breakout' if is_orb_breakout and orb_direction == 'BULLISH' else ''}"
                            ),
                            debug_info={
                                "surge_ratio": surge_ratio,
                                "is_consolidating": is_consolidating,
                                "rsi_5": rsi_5,
                                "rsi_15": rsi_15,
                                "trend_dir": trend_dir,
                                "atr": atr,
                            },
                        )

            # ------------------------
            # Bearish breakdown
            # ------------------------
            if support_resistance.support_levels:
                nearest_support = float(
                    support_resistance.support_levels[0]
                )

                if current_low < nearest_support:
                    
                    # Filter: Must be consolidating OR have massive volume surge
                    if not is_consolidating and not has_surge:
                        logger.info(
                            f"⏭️ Bearish breakdown ignored (No consolidation/surge) | "
                            f"Vol: {surge_ratio:.1f}x"
                        )
                        return None
                        
                    mtf_ok = (
                        trend_dir == "DOWN"
                        and rsi_15 <= MAX_RSI_BEARISH
                    )

                    if not mtf_ok:
                        logger.info(
                            "⏭️  Bearish breakdown ignored (MTF filter) | "
                            f"Trend15m: {trend_dir} | RSI15: {rsi_15:.1f}"
                        )
                    else:
                        logger.info(
                            "📉 Bearish breakdown candidate | "
                            f"Price: {current_price:.2f} < S: {nearest_support:.2f} | "
                            f"Consolidation: {is_consolidating} | Surge: {has_surge}"
                        )

                        atr = support_resistance.atr
                        sl = current_high + (atr * ATR_SL_MULTIPLIER)
                        tp = current_price - (atr * ATR_TP_MULTIPLIER)
                        risk_reward = (current_price - tp) / max(
                            sl - current_price, 1e-6
                        )

                        # Confidence Scoring
                        confidence = 60.0
                        if has_surge:
                            confidence += 10
                        if is_consolidating:
                            confidence += 10
                        if rsi_5 <= MAX_RSI_BEARISH:
                            confidence += 5
                        if trend_dir == "DOWN":
                            confidence += 10
                        if risk_reward >= MIN_RISK_REWARD_RATIO:
                            confidence += 5
                        # NEW: ORB boost
                        if is_orb_breakout and orb_direction == "BEARISH":
                            confidence += orb_boost

                        confidence = min(confidence, 95.0)

                        breakout_signal = Signal(
                            signal_type=SignalType.BEARISH_BREAKDOWN,
                            instrument=self.instrument,
                            timeframe="5MIN",
                            price_level=nearest_support,
                            entry_price=current_price,
                            stop_loss=sl,
                            take_profit=tp,
                            confidence=confidence,
                            volume_confirmed=has_surge,
                            momentum_confirmed=(
                                rsi_5 <= MAX_RSI_BEARISH
                            ),
                            risk_reward_ratio=risk_reward,
                            timestamp=pd.Timestamp.now(),
                            description=(
                                f"Bearish breakdown at {nearest_support:.2f} | "
                                f"RR: {risk_reward:.2f} | "
                                f"Vol Surge: {has_surge} | Consolidation: {is_consolidating}"
                                f"{' | ORB Breakout' if is_orb_breakout and orb_direction == 'BEARISH' else ''}"
                            ),
                            debug_info={
                                "surge_ratio": surge_ratio,
                                "is_consolidating": is_consolidating,
                                "rsi_5": rsi_5,
                                "rsi_15": rsi_15,
                                "trend_dir": trend_dir,
                                "atr": atr,
                            },
                        )

            return breakout_signal

        except Exception as e:
            logger.error(f"❌ Breakout detection failed: {str(e)}")
            return None

    # =====================================================================
    # FALSE BREAKOUT & RETEST
    # =====================================================================

    def detect_false_breakout(
        self,
        df: pd.DataFrame,
        breakout_level: float,
        direction: str,
    ) -> Tuple[bool, Dict]:
        """
        Detect false breakout (price fails to hold beyond level).

        Args:
            df: 5m OHLCV DataFrame
            breakout_level: breakout price level (support/resistance)
            direction: "UP" for bullish breakout, "DOWN" for bearish

        Returns:
            (is_false, details_dict)
        """
        details = {
            "retracement_pct": 0.0,
            "weak_volume": False,
            "rejection_candles": 0,
        }

        try:
            if df is None or df.empty:
                return False, details

            recent = df.tail(3).copy()
            if len(recent) < 2:
                return False, details

            vol_confirmed, vol_ratio, _ = self.check_volume_confirmation(df)
            weak_volume = not vol_confirmed

            false_breakout = False
            rejection_candles = 0
            retracement_pct = 0.0

            if direction.upper() == "UP":
                for idx in recent.index[1:]:
                    close_price = float(recent.loc[idx, "close"])
                    if close_price < breakout_level:
                        rejection_candles += 1
                        retracement_pct = (
                            (breakout_level - close_price)
                            / breakout_level
                            * 100.0
                        )

                if (
                    rejection_candles > 0
                    and retracement_pct >= FALSE_BREAKOUT_RETRACEMENT
                ):
                    false_breakout = True

            elif direction.upper() == "DOWN":
                for idx in recent.index[1:]:
                    close_price = float(recent.loc[idx, "close"])
                    if close_price > breakout_level:
                        rejection_candles += 1
                        retracement_pct = (
                            (close_price - breakout_level)
                            / breakout_level
                            * 100.0
                        )

                if (
                    rejection_candles > 0
                    and retracement_pct >= FALSE_BREAKOUT_RETRACEMENT
                ):
                    false_breakout = True

            if false_breakout and weak_volume:
                logger.warning(
                    "⚠️  FALSE BREAKOUT detected | "
                    f"Dir: {direction} | Level: {breakout_level:.2f} | "
                    f"Retrace: {retracement_pct:.2f}% | "
                    f"Vol weak (ratio: {vol_ratio:.2f}x)"
                )
            elif false_breakout:
                logger.warning(
                    "⚠️  FALSE BREAKOUT detected (price action) | "
                    f"Dir: {direction} | Level: {breakout_level:.2f} | "
                    f"Retrace: {retracement_pct:.2f}%"
                )

            details.update(
                {
                    "retracement_pct": retracement_pct,
                    "weak_volume": weak_volume,
                    "rejection_candles": rejection_candles,
                }
            )
            return false_breakout, details

        except Exception as e:
            logger.error(f"❌ False breakout detection failed: {str(e)}")
            return False, details

    def detect_retest_setup(
        self, df: pd.DataFrame, support_resistance: TechnicalLevels
    ) -> Optional[Signal]:
        """
        Detect retest setup with role reversal logic.
        
        Properly identifies:
        - Support retest: Price above level (or broke above and pulled back)
        - Resistance retest: Price below level (or broke below and bounced)
        - Role reversal: Former resistance becomes support after breakout
        """
        try:
            if df is None or df.empty or len(df) < 10:
                return None

            current = df.iloc[-1]
            current_price = float(current["close"])
            
            # Look back to check for recent breakouts
            recent_bars = df.tail(10)
            recent_highs = recent_bars["high"].values
            recent_lows = recent_bars["low"].values

            candidate_levels = (
                support_resistance.support_levels[:3]
                + support_resistance.resistance_levels[:3]
            )

            for level in candidate_levels:
                distance_pips = abs(current_price - level) * 10000
                if distance_pips <= RETEST_ZONE_PIPS:
                    
                    # ====================
                    # Determine Role Reversal
                    # ====================
                    # Check if price recently broke through this level
                    broke_above = any(recent_highs > level * 1.001)  # 0.1% buffer
                    broke_below = any(recent_lows < level * 0.999)   # 0.1% buffer
                    
                    # Current position
                    price_above_level = current_price > level
                    
                    # ====================
                    # Retest Logic
                    # ====================
                    signal_type = None
                    description = ""
                    is_long = False
                    
                    # SUPPORT RETEST scenarios:
                    # 1. Price above level AND broke above recently (pullback to new support)
                    # 2. Price hovering at support from below
                    if price_above_level:
                        if broke_above:
                            # Role reversal: former resistance now support
                            signal_type = SignalType.SUPPORT_BOUNCE
                            description = f"Support retest at {level:.2f} (former resistance, role reversal)"
                            is_long = True
                        else:
                            # Regular support bounce
                            signal_type = SignalType.SUPPORT_BOUNCE
                            description = f"Support retest at {level:.2f}"
                            is_long = True
                    
                    # RESISTANCE RETEST scenarios:
                    # 1. Price below level AND broke below recently (bounce to new resistance)
                    # 2. Price testing resistance from below
                    else:  # price_above_level == False
                        if broke_below:
                            # Role reversal: former support now resistance
                            signal_type = SignalType.RESISTANCE_BOUNCE
                            description = f"Resistance retest at {level:.2f} (former support, role reversal)"
                            is_long = False
                        else:
                            # Regular resistance test
                            signal_type = SignalType.RESISTANCE_BOUNCE
                            description = f"Resistance retest at {level:.2f}"
                            is_long = False
                    
                    if signal_type is None:
                        continue
                    
                    logger.info(
                        f"🎯 RETEST SETUP | {description} | "
                        f"Price: {current_price:.2f} | Level: {level:.2f} | "
                        f"Dist: {distance_pips:.1f} pips"
                    )

                    atr = support_resistance.atr
                    
                    # ====================
                    # Entry, SL, TP Logic
                    # ====================
                    if is_long:
                        # LONG: Support retest
                        entry_price = current_price
                        stop_loss = level - (atr * 0.5)  # SL below support
                        
                        # Find next resistance for TP
                        next_resistance = None
                        for r in support_resistance.resistance_levels:
                            if r > current_price:
                                next_resistance = r
                                break
                        
                        if next_resistance:
                            take_profit = next_resistance
                        elif support_resistance.pdh > current_price:
                            take_profit = support_resistance.pdh
                        else:
                            take_profit = current_price + (atr * 2.0)
                    
                    else:
                        # SHORT: Resistance retest
                        entry_price = current_price
                        stop_loss = level + (atr * 0.5)  # SL above resistance
                        
                        # Find next support for TP
                        next_support = None
                        for s in support_resistance.support_levels:
                            if s < current_price:
                                next_support = s
                                break
                        
                        if next_support:
                            take_profit = next_support
                        elif support_resistance.pdl < current_price and support_resistance.pdl > 0:
                            take_profit = support_resistance.pdl
                        else:
                            take_profit = current_price - (atr * 2.0)
                    
                    # Calculate R:R
                    risk = abs(entry_price - stop_loss)
                    reward = abs(take_profit - entry_price)
                    rr = reward / risk if risk > 0 else 0
                    
                    # Skip if R:R too low
                    if rr < 1.5:
                        logger.info(f"⏭️ Skipping retest - poor R:R ({rr:.2f})")
                        continue

                    return Signal(
                        signal_type=signal_type,
                        instrument=self.instrument,
                        timeframe="5MIN",
                        price_level=level,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        confidence=75.0,
                        volume_confirmed=False,
                        momentum_confirmed=False,
                        risk_reward_ratio=rr,
                        timestamp=pd.Timestamp.now(),
                        description=description,
                        debug_info={
                            "distance_pips": distance_pips,
                            "broke_above": broke_above,
                            "broke_below": broke_below,
                            "price_above_level": price_above_level,
                        },
                    )

            return None

        except Exception as e:
            logger.error(f"❌ Retest detection failed: {str(e)}")
            return None

    def detect_inside_bar(
        self,
        df: pd.DataFrame,
        higher_tf_context: Dict,
        support_resistance: TechnicalLevels
    ) -> Optional[Signal]:
        """
        Detect high-probability inside bar setup with full context awareness.
        
        Only fires when:
        - Pattern is valid (size, volume)
        - Trend alignment (15m + VWAP + 20 EMA + prev day)
        - Logical target with good R:R
        - Breakout confirmed (price beyond mother bar range)
        
        Args:
            df: 5m OHLCV data
            higher_tf_context: Contains 15m trend, VWAP, 20 EMA, prev day trend
            support_resistance: S/R levels for smart targeting
        """
        try:
            if df is None or len(df) < 2:
                return None

            prev_candle = df.iloc[-2]  # Mother bar
            curr_candle = df.iloc[-1]  # Inside bar (current)

            # ====================
            # 1. Pattern Detection
            # ====================
            is_inside = (
                curr_candle["high"] < prev_candle["high"]
                and curr_candle["low"] > prev_candle["low"]
            )

            if not is_inside:
                return None

            logger.info("📊 INSIDE BAR PATTERN DETECTED | Validating setup...")

            # ====================
            # 2. Pattern Quality Check
            # ====================
            is_valid, rejection_reason = self._validate_inside_bar_pattern(
                prev_candle, curr_candle, df
            )
            
            if not is_valid:
                logger.info(f"⏭️ Inside bar rejected: {rejection_reason}")
                return None

            # ====================
            # 3. Extract Context
            # ====================
            trend_15m = higher_tf_context.get("trend_direction", "FLAT")
            price_above_vwap = higher_tf_context.get("price_above_vwap", False)
            price_above_ema20 = higher_tf_context.get("price_above_ema20", False)
            vwap_slope = higher_tf_context.get("vwap_slope", "FLAT")
            prev_day_trend = higher_tf_context.get("prev_day_trend", "FLAT")
            vwap_5m = higher_tf_context.get("vwap_5m", 0.0)
            ema_20_5m = higher_tf_context.get("ema_20_5m", 0.0)
            
            current_price = float(curr_candle["close"])
            rsi_5 = self._calculate_rsi(df)

            # ====================
            # 4. Determine Directional Bias
            # ====================
            direction = None
            signal_type = None
            
            # LONG bias conditions
            long_conditions = [
                price_above_vwap,
                price_above_ema20,
                trend_15m == "UP" or prev_day_trend == "UP",
            ]
            
            # SHORT bias conditions
            short_conditions = [
                not price_above_vwap,
                not price_above_ema20,
                trend_15m == "DOWN" or prev_day_trend == "DOWN",
            ]
            
            # Require at least 2 of 3 conditions
            if sum(long_conditions) >= 2:
                direction = "LONG"
                signal_type = SignalType.INSIDE_BAR
            elif sum(short_conditions) >= 2:
                direction = "SHORT"
                signal_type = SignalType.INSIDE_BAR
            else:
                logger.info(
                    "⏭️ Inside bar skipped - no clear directional bias | "
                    f"VWAP: {price_above_vwap} | 20EMA: {price_above_ema20} | "
                    f"Trend15m: {trend_15m} | PrevDay: {prev_day_trend}"
                )
                return None

            logger.info(f"✅ Directional bias: {direction}")

            # ====================
            # 5. Breakout Entry Logic
            # ====================
            # Check if breakout has actually happened
            if direction == "LONG":
                # For LONG, need close ABOVE mother bar high
                if current_price <= prev_candle["high"]:
                    logger.debug(
                        "⏳ Inside bar LONG setup pending - waiting for breakout above mother bar high"
                    )
                    return None  # Wait for actual breakout
                
                entry_price = float(prev_candle["high"])
                sl_price = float(prev_candle["low"])
                
            else:  # SHORT
                # For SHORT, need close BELOW mother bar low
                if current_price >= prev_candle["low"]:
                    logger.debug(
                        "⏳ Inside bar SHORT setup pending - waiting for breakout below mother bar low"
                    )
                    return None  # Wait for actual breakout
                
                entry_price = float(prev_candle["low"])
                sl_price = float(prev_candle["high"])

            # Check if mother bar is too wide - use 50% level for SL
            mother_range = abs(prev_candle["high"] - prev_candle["low"])
            atr = support_resistance.atr
            if mother_range > atr * 2.0:
                logger.info(f"⚠️ Wide mother bar detected - using 50% SL level")
                if direction == "LONG":
                    sl_price = prev_candle["low"] + (mother_range * 0.5)
                else:
                    sl_price = prev_candle["high"] - (mother_range * 0.5)

            # ====================
            # 6. Smart Target Calculation
            # ====================
            tp_price, rr_ratio, target_reason = self._calculate_inside_bar_targets(
                entry_price,
                sl_price,
                direction,
                support_resistance,
                current_price
            )
            
            if tp_price is None:
                logger.info("⏭️ Inside bar skipped - no valid target or poor R:R")
                return None

            # ====================
            # 7. Volume Confirmation
            # ====================
            vol_confirmed, vol_ratio, _ = self.check_volume_confirmation(df)

            # ====================
            # 8. Confidence Scoring
            # ====================
            confidence = 60.0
            
            # VWAP alignment
            if (direction == "LONG" and price_above_vwap) or \
               (direction == "SHORT" and not price_above_vwap):
                confidence += 10
                
            # 20 EMA alignment
            if (direction == "LONG" and price_above_ema20) or \
               (direction == "SHORT" and not price_above_ema20):
                confidence += 10
                
            # 15m trend alignment
            if (direction == "LONG" and trend_15m == "UP") or \
               (direction == "SHORT" and trend_15m == "DOWN"):
                confidence += 10
                
            # Previous day trend alignment
            if (direction == "LONG" and prev_day_trend == "UP") or \
               (direction == "SHORT" and prev_day_trend == "DOWN"):
                confidence += 5
                
            # Volume confirmation
            if vol_confirmed:
                confidence += 10
                
            # Good R:R
            if rr_ratio >= 2.0:
                confidence += 10
                
            # RSI alignment
            if (direction == "LONG" and rsi_5 >= 50) or \
               (direction == "SHORT" and rsi_5 <= 50):
                confidence += 5

            confidence = min(confidence, 95.0)

            # ====================
            # 9. Build Description
            # ====================
            description = (
                f"Inside bar {direction} breakout | "
                f"Target: {target_reason} | "
                f"VWAP: {'✓' if ((direction=='LONG' and price_above_vwap) or (direction=='SHORT' and not price_above_vwap)) else '✗'} | "
                f"20EMA: {'✓' if ((direction=='LONG' and price_above_ema20) or (direction=='SHORT' and not price_above_ema20)) else '✗'} | "
                f"15m: {trend_15m} | PrevDay: {prev_day_trend}"
            )

            logger.info(
                f"🎯 HIGH-QUALITY INSIDE BAR {direction} | "
                f"Entry: {entry_price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f} | "
                f"R:R: {rr_ratio:.2f} | Conf: {confidence:.0f}%"
            )

            return Signal(
                signal_type=signal_type,
                instrument=self.instrument,
                timeframe="5MIN",
                price_level=float(curr_candle["close"]),
                entry_price=entry_price,
                stop_loss=sl_price,
                take_profit=tp_price,
                confidence=confidence,
                volume_confirmed=vol_confirmed,
                momentum_confirmed=(rsi_5 >= 50 if direction == "LONG" else rsi_5 <= 50),
                risk_reward_ratio=rr_ratio,
                timestamp=pd.Timestamp.now(),
                description=description,
                debug_info={
                    "direction": direction,
                    "mother_high": float(prev_candle["high"]),
                    "mother_low": float(prev_candle["low"]),
                    "inside_high": float(curr_candle["high"]),
                    "inside_low": float(curr_candle["low"]),
                    "trend_15m": trend_15m,
                    "vwap_5m": vwap_5m,
                    "ema_20_5m": ema_20_5m,
                    "prev_day_trend": prev_day_trend,
                    "target_reason": target_reason,
                    "rsi_5": rsi_5,
                    "vol_ratio": vol_ratio,
                },
            )

        except Exception as e:
            logger.error(f"❌ Inside bar detection failed: {str(e)}")
            return None

    def _validate_inside_bar_pattern(
        self,
        prev_candle: pd.Series,
        curr_candle: pd.Series,
        df: pd.DataFrame
    ) -> Tuple[bool, str]:
        """
        Validate inside bar pattern quality.
        
        Returns:
            (is_valid, rejection_reason)
        """
        try:
            mother_range = prev_candle['high'] - prev_candle['low']
            inside_range = curr_candle['high'] - curr_candle['low']
            
            # Check if inside bar is not too tiny
            if inside_range < mother_range * 0.2:
                return False, "Inside bar too small (< 20% of mother bar)"
            
            # Check if inside bar is not too large  
            if inside_range > mother_range * 0.8:
                return False, "Inside bar too large (> 80% of mother bar)"
            
            # Check if mother bar is not too wide
            atr = self._calculate_atr(df)
            if mother_range > atr * 2.5:
                return False, f"Mother bar too wide ({mother_range:.2f} > 2.5x ATR)"
            
            # Check volume (if available)
            if df['volume'].sum() > 0:
                avg_vol = df['volume'].tail(20).mean()
                mother_vol = prev_candle['volume']
                curr_vol = curr_candle['volume']
                
                # Prefer volume on mother bar or breakout bar
                if mother_vol < avg_vol * 0.7 and curr_vol < avg_vol * 0.7:
                    return False, "Low volume on both mother and inside bar"
            
            return True, ""
            
        except Exception as e:
            logger.warning(f"⚠️ Pattern validation failed: {str(e)}")
            return True, ""  # Default to valid if check fails

    def _calculate_inside_bar_targets(
        self,
        entry: float,
        sl: float,
        direction: str,
        support_resistance: TechnicalLevels,
        current_price: float
    ) -> Tuple[Optional[float], float, str]:
        """
        Calculate intelligent take profit using S/R and PDH/PDL.
        
        Args:
            entry: Entry price
            sl: Stop loss
            direction: "LONG" or "SHORT"
            support_resistance: S/R levels
            current_price: Current market price
            
        Returns:
            (take_profit, risk_reward_ratio, target_reason)
        """
        try:
            risk = abs(entry - sl)
            atr = support_resistance.atr
            
            # Find nearest logical target
            target = None
            target_reason = ""
            
            if direction == "LONG":
                # Look for resistance above current price
                candidates = []
                
                # Check resistance clusters
                for r in support_resistance.resistance_levels:
                    if r > current_price:
                        candidates.append((r, "Resistance"))
                
                # Check PDH
                if support_resistance.pdh > current_price:
                    candidates.append((support_resistance.pdh, "PDH"))
                
                # Sort by distance and pick nearest
                if candidates:
                    candidates.sort(key=lambda x: abs(x[0] - current_price))
                    target, target_reason = candidates[0]
                else:
                    # Fallback to ATR-based
                    target = entry + (atr * 2.0)
                    target_reason = "ATR 2.0x"
                    
            else:  # SHORT
                # Look for support below current price
                candidates = []
                
                # Check support clusters
                for s in support_resistance.support_levels:
                    if s < current_price:
                        candidates.append((s, "Support"))
                
                # Check PDL
                if support_resistance.pdl < current_price and support_resistance.pdl > 0:
                    candidates.append((support_resistance.pdl, "PDL"))
                
                # Sort by distance and pick nearest
                if candidates:
                    candidates.sort(key=lambda x: abs(x[0] - current_price))
                    target, target_reason = candidates[0]
                else:
                    # Fallback to ATR-based
                    target = entry - (atr * 2.0)
                    target_reason = "ATR 2.0x"
            
            # Calculate R:R
            if target:
                reward = abs(target - entry)
                rr = reward / risk if risk > 0 else 0
                
                # Skip if R:R too low
                if rr < 1.5:
                    logger.info(f"⏭️ Skipping inside bar - poor R:R ({rr:.2f})")
                    return None, 0.0, "R:R < 1.5"
                
                return target, rr, target_reason
            
            return None, 0.0, "No logical target found"
            
        except Exception as e:
            logger.warning(f"⚠️ Target calculation failed: {str(e)}")
            # Fallback to simple ATR-based
            if direction == "LONG":
                target = entry + (risk * 2.0)
            else:
                target = entry - (risk * 2.0)
            return target, 2.0, "ATR Fallback"

    # =====================================================================
    # INDICATOR CALCULATIONS
    # =====================================================================

    def _calculate_rsi(
        self, df: pd.DataFrame, period: int = RSI_PERIOD
    ) -> float:
        """Calculate RSI (Relative Strength Index)."""
        try:
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0.0).rolling(period).mean()
            loss = -delta.where(delta < 0, 0.0).rolling(period).mean()

            if loss.iloc[-1] == 0 or pd.isna(loss.iloc[-1]):
                return 50.0

            rs = gain / loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi.iloc[-1])

        except Exception:
            return 50.0

    def _calculate_atr(
        self, df: pd.DataFrame, period: int = ATR_PERIOD
    ) -> float:
        """Calculate Average True Range."""
        try:
            high_low = df["high"] - df["low"]
            high_close = (df["high"] - df["close"].shift()).abs()
            low_close = (df["low"] - df["close"].shift()).abs()

            ranges = pd.concat(
                [high_low, high_close, low_close], axis=1
            )
            true_range = ranges.max(axis=1)
            atr = true_range.rolling(period).mean()

            return float(atr.iloc[-1])

        except Exception:
            return 0.0

    def _calculate_volatility_score(self, df: pd.DataFrame) -> float:
        """Calculate volatility score (0-100)."""
        try:
            returns = df["close"].pct_change()
            volatility = float(returns.std() * 100.0)
            score = min(volatility * 100.0, 100.0)
            return score
        except Exception:
            return 50.0

    def _calculate_vwap(self, df: pd.DataFrame) -> Tuple[pd.Series, float, str]:
        """
        Calculate intraday VWAP (Volume Weighted Average Price).
        Resets at day boundaries for intraday analysis.
        
        Returns:
            (vwap_series, current_vwap, vwap_slope)
        """
        try:
            df = df.copy()
            
            # Check if we have volume data
            if df['volume'].sum() == 0:
                logger.debug("⚠️ No volume data for VWAP - using simple average")
                vwap_series = df['close']
                return vwap_series, float(vwap_series.iloc[-1]), "FLAT"
            
            # Calculate typical price
            df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
            
            # Identify day boundaries (reset VWAP at each day)
            df['date'] = pd.to_datetime(df.index).date
            
            # Calculate VWAP for each day
            vwap_list = []
            for date, group in df.groupby('date'):
                group = group.copy()
                group['cum_vol'] = group['volume'].cumsum()
                group['cum_vol_price'] = (group['typical_price'] * group['volume']).cumsum()
                group['vwap'] = group['cum_vol_price'] / group['cum_vol']
                vwap_list.append(group['vwap'])
            
            vwap_series = pd.concat(vwap_list)
            current_vwap = float(vwap_series.iloc[-1])
            
            # Determine VWAP slope (last 5 bars)
            if len(vwap_series) >= 5:
                vwap_slope = "UP" if vwap_series.iloc[-1] > vwap_series.iloc[-5] else "DOWN"
            else:
                vwap_slope = "FLAT"
            
            logger.debug(f"VWAP: {current_vwap:.2f} | Slope: {vwap_slope}")
            return vwap_series, current_vwap, vwap_slope
            
        except Exception as e:
            logger.warning(f"⚠️ VWAP calculation failed: {str(e)}")
            # Fallback to close price
            return df['close'], float(df['close'].iloc[-1]), "FLAT"

    def _get_previous_day_trend(self, df: pd.DataFrame) -> str:
        """
        Determine previous day's trend based on daily data.
        
        Args:
            df: DataFrame with at least 2 days of data
            
        Returns:
            "UP" / "DOWN" / "FLAT"
        """
        try:
            if df is None or len(df) < 2:
                return "FLAT"
            
            # Get yesterday's candle (second to last)
            prev_day = df.iloc[-2]
            
            # Simple trend: close vs open
            if prev_day['close'] > prev_day['open'] * 1.002:  # 0.2% threshold
                return "UP"
            elif prev_day['close'] < prev_day['open'] * 0.998:
                return "DOWN"
            else:
                return "FLAT"
                
        except Exception as e:
            logger.warning(f"⚠️ Previous day trend calc failed: {str(e)}")
            return "FLAT"

    def detect_pin_bar(
        self,
        df: pd.DataFrame,
        support_resistance: TechnicalLevels,
        higher_tf_context: Dict,
    ) -> Optional[Signal]:
        """
        Detect pin bar (rejection candle with long wick).
        
        Bullish Pin Bar (Hammer):
            - Long lower wick (>60% of range)
            - Small body (<30% of range)
            - At support level
            - Uptrend or reversal setup
        
        Bearish Pin Bar (Shooting Star):
            - Long upper wick (>60% of range)
            - Small body (<30% of range)
            - At resistance level
            - Downtrend or reversal setup
        """
        try:
            if df is None or df.empty or len(df) < 20:
                return None

            current = df.iloc[-1]
            current_open = float(current["open"])
            current_close = float(current["close"])
            current_high = float(current["high"])
            current_low = float(current["low"])
            current_price = current_close

            # Calculate candle components
            body_size = abs(current_close - current_open)
            upper_wick = current_high - max(current_open, current_close)
            lower_wick = min(current_open, current_close) - current_low
            total_range = current_high - current_low

            if total_range < 0.0001:  # Avoid division by zero
                return None

            body_pct = (body_size / total_range)
            upper_wick_pct = (upper_wick / total_range)
            lower_wick_pct = (lower_wick / total_range)

            atr = support_resistance.atr
            trend_dir = higher_tf_context.get("trend_direction", "FLAT")
            rsi_15 = float(higher_tf_context.get("rsi_15", 50.0))

            # =============================
            # BULLISH PIN BAR (Hammer)
            # =============================
            if lower_wick_pct > 0.6 and body_pct < 0.3:
                # Check if at support level
                at_support = False
                support_level = None
                
                for level in support_resistance.support_levels[:3]:
                    distance_pips = abs(current_low - level) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:  # Near support
                        at_support = True
                        support_level = level
                        break
                
                # Also check if near PDL
                if not at_support and support_resistance.pdl > 0:
                    distance_pips = abs(current_low - support_resistance.pdl) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:
                        at_support = True
                        support_level = support_resistance.pdl

                if at_support:
                    # Check trend alignment (prefer uptrend or neutral)
                    if trend_dir in ["UP", "FLAT"]:
                        logger.info(
                            f"🔨 BULLISH PIN BAR detected | "
                            f"Lower wick: {lower_wick_pct*100:.1f}% | "
                            f"Body: {body_pct*100:.1f}% | "
                            f"At support: {support_level:.2f}"
                        )

                        entry_price = current_close
                        stop_loss = current_low - (atr * 0.5)
                        
                        # Target: Next resistance or PDH
                        target = None
                        for r in support_resistance.resistance_levels:
                            if r > current_price:
                                target = r
                                break
                        
                        if not target and support_resistance.pdh > current_price:
                            target = support_resistance.pdh
                        
                        if not target:
                            target = current_price + (atr * 3.0)
                        
                        risk = abs(entry_price - stop_loss)
                        reward = abs(target - entry_price)
                        rr = reward / risk if risk > 0 else 0
                        
                        if rr < 1.5:
                            logger.info(f"⏭️ Bullish pin bar skipped: Poor R:R ({rr:.2f})")
                            return None

                        confidence = 65.0
                        if trend_dir == "UP":
                            confidence += 10
                        if rsi_15 < 50:  # Oversold
                            confidence += 5
                        if lower_wick_pct > 0.7:  # Very long wick
                            confidence += 5

                        return Signal(
                            signal_type=SignalType.BULLISH_PIN_BAR,
                            instrument=self.instrument,
                            timeframe="5MIN",
                            price_level=support_level,
                            entry_price=entry_price,
                            stop_loss=stop_loss,
                            take_profit=target,
                            confidence=min(confidence, 90.0),
                            volume_confirmed=False,
                            momentum_confirmed=(rsi_15 < 50),
                            risk_reward_ratio=rr,
                            timestamp=pd.Timestamp.now(),
                            description=(
                                f"Bullish pin bar at {support_level:.2f} | "
                                f"Lower wick: {lower_wick_pct*100:.0f}% | RR: {rr:.1f}"
                            ),
                            debug_info={
                                "lower_wick_pct": lower_wick_pct,
                                "body_pct": body_pct,
                                "trend_dir": trend_dir,
                                "rsi_15": rsi_15,
                            },
                        )

            # =============================
            # BEARISH PIN BAR (Shooting Star)
            # =============================
            if upper_wick_pct > 0.6 and body_pct < 0.3:
                # Check if at resistance level
                at_resistance = False
                resistance_level = None
                
                for level in support_resistance.resistance_levels[:3]:
                    distance_pips = abs(current_high - level) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:  # Near resistance
                        at_resistance = True
                        resistance_level = level
                        break
                
                # Also check if near PDH
                if not at_resistance and support_resistance.pdh > 0:
                    distance_pips = abs(current_high - support_resistance.pdh) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:
                        at_resistance = True
                        resistance_level = support_resistance.pdh

                if at_resistance:
                    # Check trend alignment (prefer downtrend or neutral)
                    if trend_dir in ["DOWN", "FLAT"]:
                        logger.info(
                            f"⭐ BEARISH PIN BAR detected | "
                            f"Upper wick: {upper_wick_pct*100:.1f}% | "
                            f"Body: {body_pct*100:.1f}% | "
                            f"At resistance: {resistance_level:.2f}"
                        )

                        entry_price = current_close
                        stop_loss = current_high + (atr * 0.5)
                        
                        # Target: Next support or PDL
                        target = None
                        for s in support_resistance.support_levels:
                            if s < current_price:
                                target = s
                                break
                        
                        if not target and support_resistance.pdl > 0 and support_resistance.pdl < current_price:
                            target = support_resistance.pdl
                        
                        if not target:
                            target = current_price - (atr * 3.0)
                        
                        risk = abs(stop_loss - entry_price)
                        reward = abs(entry_price - target)
                        rr = reward / risk if risk > 0 else 0
                        
                        if rr < 1.5:
                            logger.info(f"⏭️ Bearish pin bar skipped: Poor R:R ({rr:.2f})")
                            return None

                        confidence = 65.0
                        if trend_dir == "DOWN":
                            confidence += 10
                        if rsi_15 > 50:  # Overbought
                            confidence += 5
                        if upper_wick_pct > 0.7:  # Very long wick
                            confidence += 5

                        return Signal(
                            signal_type=SignalType.BEARISH_PIN_BAR,
                            instrument=self.instrument,
                            timeframe="5MIN",
                            price_level=resistance_level,
                            entry_price=entry_price,
                            stop_loss=stop_loss,
                            take_profit=target,
                            confidence=min(confidence, 90.0),
                            volume_confirmed=False,
                            momentum_confirmed=(rsi_15 > 50),
                            risk_reward_ratio=rr,
                            timestamp=pd.Timestamp.now(),
                            description=(
                                f"Bearish pin bar at {resistance_level:.2f} | "
                                f"Upper wick: {upper_wick_pct*100:.0f}% | RR: {rr:.1f}"
                            ),
                            debug_info={
                                "upper_wick_pct": upper_wick_pct,
                                "body_pct": body_pct,
                                "trend_dir": trend_dir,
                                "rsi_15": rsi_15,
                            },
                        )

            return None

        except Exception as e:
            logger.error(f"❌ Pin bar detection failed: {str(e)}")
            return None

    def detect_engulfing(
        self,
        df: pd.DataFrame,
        support_resistance: TechnicalLevels,
        higher_tf_context: Dict,
    ) -> Optional[Signal]:
        """
        Detect bullish or bearish engulfing candlestick pattern.
        
        Bullish Engulfing:
            - Previous candle is bearish (red)
            - Current candle is bullish (green)
            - Current candle body completely engulfs previous body
            - At support level or in uptrend
            - Volume confirmation
        
        Bearish Engulfing:
            - Previous candle is bullish (green)
            - Current candle is bearish (red)
            - Current candle body completely engulfs previous body
            - At resistance level or in downtrend
            - Volume confirmation
        """
        try:
            if df is None or df.empty or len(df) < 20:
                return None

            prev = df.iloc[-2]
            current = df.iloc[-1]
            
            prev_open = float(prev["open"])
            prev_close = float(prev["close"])
            prev_high = float(prev["high"])
            prev_low = float(prev["low"])
            
            curr_open = float(current["open"])
            curr_close = float(current["close"])
            curr_high = float(current["high"])
            curr_low = float(current["low"])
            current_price = curr_close

            # Calculate body sizes
            prev_body = abs(prev_close - prev_open)
            curr_body = abs(curr_close - curr_open)
            
            # Require meaningful candles (avoid dojis)
            if prev_body < 0.00001 or curr_body < 0.00001:
                return None

            atr = support_resistance.atr
            trend_dir = higher_tf_context.get("trend_direction", "FLAT")
            rsi_15 = float(higher_tf_context.get("rsi_15", 50.0))


            # Volume check (current bar should have higher volume)
            vol_surge, surge_ratio, _ = self._detect_volume_surge(df)

            # =============================
            # BULLISH ENGULFING
            # =============================
            is_bullish_engulfing = (
                prev_close < prev_open and  # Previous bearish
                curr_close > curr_open and  # Current bullish
                curr_open <= prev_close and  # Opens at/below prev close
                curr_close >= prev_open      # Closes at/above prev open
            )

            if is_bullish_engulfing:
                # Check if at support level
                at_support = False
                support_level = None
                
                for level in support_resistance.support_levels[:3]:
                    distance_pips = abs(curr_low - level) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:
                        at_support = True
                        support_level = level
                        break
                
                if not at_support and support_resistance.pdl > 0:
                    distance_pips = abs(curr_low - support_resistance.pdl) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:
                        at_support = True
                        support_level = support_resistance.pdl

                # Require either support level OR uptrend
                if at_support or trend_dir == "UP":
                    # Require volume confirmation
                    if not vol_surge:
                        logger.info(f"⏭️ Bullish engulfing skipped: No volume surge ({surge_ratio:.1f}x)")
                        return None
                    
                    logger.info(
                        f"🟢 BULLISH ENGULFING detected | "
                        f"Prev: {prev_open:.2f}->{prev_close:.2f} | "
                        f"Curr: {curr_open:.2f}->{curr_close:.2f} | "
                        f"Vol: {surge_ratio:.1f}x"
                    )

                    entry_price = curr_close
                    stop_loss = curr_low - (atr * 0.5)
                    
                    # Target: Next resistance
                    target = None
                    for r in support_resistance.resistance_levels:
                        if r > current_price:
                            target = r
                            break
                    
                    if not target and support_resistance.pdh > current_price:
                        target = support_resistance.pdh
                    
                    if not target:
                        target = current_price + (atr * 3.0)
                    
                    risk = abs(entry_price - stop_loss)
                    reward = abs(target - entry_price)
                    rr = reward / risk if risk > 0 else 0
                    
                    if rr < 1.5:
                        logger.info(f"⏭️ Bullish engulfing skipped: Poor R:R ({rr:.2f})")
                        return None

                    confidence = 70.0
                    if trend_dir == "UP":
                        confidence += 10
                    if at_support:
                        confidence += 5
                    if rsi_15 < 50:
                        confidence += 5
                    if surge_ratio > 2.0:
                        confidence += 5

                    return Signal(
                        signal_type=SignalType.BULLISH_ENGULFING,
                        instrument=self.instrument,
                        timeframe="5MIN",
                        price_level=support_level if at_support else curr_low,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=target,
                        confidence=min(confidence, 95.0),
                        volume_confirmed=True,
                        momentum_confirmed=(rsi_15 < 50),
                        risk_reward_ratio=rr,
                        timestamp=pd.Timestamp.now(),
                        description=(
                            f"Bullish engulfing pattern | "
                            f"Vol surge: {surge_ratio:.1f}x | RR: {rr:.1f}"
                        ),
                        debug_info={
                            "surge_ratio": surge_ratio,
                            "engulf_ratio": curr_body / prev_body if prev_body > 0 else 0,
                            "trend_dir": trend_dir,
                            "rsi_15": rsi_15,
                        },
                    )

            # =============================
            # BEARISH ENGULFING
            # =============================
            is_bearish_engulfing = (
                prev_close > prev_open and  # Previous bullish
                curr_close < curr_open and  # Current bearish
                curr_open >= prev_close and  # Opens at/above prev close
                curr_close <= prev_open      # Closes at/below prev open
            )

            if is_bearish_engulfing:
                # Check if at resistance level
                at_resistance = False
                resistance_level = None
                
                for level in support_resistance.resistance_levels[:3]:
                    distance_pips = abs(curr_high - level) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:
                        at_resistance = True
                        resistance_level = level
                        break
                
                if not at_resistance and support_resistance.pdh > 0:
                    distance_pips = abs(curr_high - support_resistance.pdh) * 10000
                    if distance_pips <= RETEST_ZONE_PIPS:
                        at_resistance = True
                        resistance_level = support_resistance.pdh

                # Require either resistance level OR downtrend
                if at_resistance or trend_dir == "DOWN":
                    # Require volume confirmation
                    if not vol_surge:
                        logger.info(f"⏭️ Bearish engulfing skipped: No volume surge ({surge_ratio:.1f}x)")
                        return None
                    
                    logger.info(
                        f"🔴 BEARISH ENGULFING detected | "
                        f"Prev: {prev_open:.2f}->{prev_close:.2f} | "
                        f"Curr: {curr_open:.2f}->{curr_close:.2f} | "
                        f"Vol: {surge_ratio:.1f}x"
                    )

                    entry_price = curr_close
                    stop_loss = curr_high + (atr * 0.5)
                    
                    # Target: Next support
                    target = None
                    for s in support_resistance.support_levels:
                        if s < current_price:
                            target = s
                            break
                    
                    if not target and support_resistance.pdl > 0 and support_resistance.pdl < current_price:
                        target = support_resistance.pdl
                    
                    if not target:
                        target = current_price - (atr * 3.0)
                    
                    risk = abs(stop_loss - entry_price)
                    reward = abs(entry_price - target)
                    rr = reward / risk if risk > 0 else 0
                    
                    if rr < 1.5:
                        logger.info(f"⏭️ Bearish engulfing skipped: Poor R:R ({rr:.2f})")
                        return None

                    confidence = 70.0
                    if trend_dir == "DOWN":
                        confidence += 10
                    if at_resistance:
                        confidence += 5
                    if rsi_15 > 50:
                        confidence += 5
                    if surge_ratio > 2.0:
                        confidence += 5

                    return Signal(
                        signal_type=SignalType.BEARISH_ENGULFING,
                        instrument=self.instrument,
                        timeframe="5MIN",
                        price_level=resistance_level if at_resistance else curr_high,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=target,
                        confidence=min(confidence, 95.0),
                        volume_confirmed=True,
                        momentum_confirmed=(rsi_15 > 50),
                        risk_reward_ratio=rr,
                        timestamp=pd.Timestamp.now(),
                        description=(
                            f"Bearish engulfing pattern | "
                            f"Vol surge: {surge_ratio:.1f}x | RR: {rr:.1f}"
                        ),
                        debug_info={
                            "surge_ratio": surge_ratio,
                            "engulf_ratio": curr_body / prev_body if prev_body > 0 else 0,
                            "trend_dir": trend_dir,
                            "rsi_15": rsi_15,
                        },
                    )

            return None

        except Exception as e:
            logger.error(f"❌ Engulfing detection failed: {str(e)}")
            return None

    def _is_choppy_session(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """
        Detect if market is choppy/ranging (avoid trading in such conditions).
        
        Returns:
            (is_choppy, reason)
        
        Criteria:
            - ATR < 0.3% of price (very low volatility)
            - Price oscillating around VWAP (4+ crosses in 10 bars)
        """
        try:
            from config.settings import MIN_ATR_PERCENT, MAX_VWAP_CROSSES
            
            if df is None or len(df) < 20:
                return False, ""
            
            current_price = float(df.iloc[-1]["close"])
            atr = self._calculate_atr(df)
            
            # 1. Check ATR (volatility)
            atr_pct = (atr / current_price) * 100
            
            if atr_pct < MIN_ATR_PERCENT:
                return True, f"Low volatility (ATR: {atr_pct:.2f}%)"
            
            # 2. Check VWAP oscillation (choppy price action)
            _, vwap, _ = self._calculate_vwap(df)
            recent_closes = df.tail(10)["close"]
            
            # Count VWAP crosses
            crosses = 0
            for i in range(1, len(recent_closes)):
                prev_close = recent_closes.iloc[i-1]
                curr_close = recent_closes.iloc[i]
                
                if (prev_close < vwap and curr_close > vwap) or \
                   (prev_close > vwap and curr_close < vwap):
                    crosses += 1
            
            if crosses >= MAX_VWAP_CROSSES:
                return True, f"Choppy (VWAP crosses: {crosses})"
            
            return False, ""
            
        except Exception as e:
            logger.warning(f"⚠️ Choppy session check failed: {str(e)}")
            return False, ""
    # =====================================================================
    # TOP-LEVEL ANALYSIS WRAPPER (WITH MTF)
    # =====================================================================

    def analyze_with_multi_tf(
        self, df_5m: pd.DataFrame, higher_tf_context: Dict
    ) -> Dict:
        """
        Full analysis using 5m data + 15m higher timeframe context.
        """
        result = {
            "pdh": None,
            "pdl": None,
            "levels": None,
            "volume_confirmed": False,
            "volume_ratio": 0.0,
            "breakout_signal": None,
            "retest_signal": None,
            "inside_bar_signal": None,
            "pin_bar_signal": None,
            "engulfing_signal": None,
        }

        try:
            if df_5m is None or df_5m.empty:
                logger.error("❌ analyze_with_multi_tf: empty 5m data")
                return result

            pdh, pdl = self.calculate_pdh_pdl(df_5m)
            levels = self.calculate_support_resistance(df_5m)
            vol_confirmed, vol_ratio, _ = self.check_volume_confirmation(df_5m)
            breakout = self.detect_breakout(df_5m, levels, higher_tf_context)
            retest = self.detect_retest_setup(df_5m, levels)
            inside_bar = self.detect_inside_bar(df_5m, higher_tf_context, levels)
            pin_bar = self.detect_pin_bar(df_5m, levels, higher_tf_context)
            engulfing = self.detect_engulfing(df_5m, levels, higher_tf_context)

            result.update(
                {
                    "pdh": pdh,
                    "pdl": pdl,
                    "levels": levels,
                    "volume_confirmed": vol_confirmed,
                    "volume_ratio": vol_ratio,
                    "breakout_signal": breakout,
                    "retest_signal": retest,
                    "inside_bar_signal": inside_bar,
                    "pin_bar_signal": pin_bar,
                    "engulfing_signal": engulfing,
                }
            )
            return result

        except Exception as e:
            logger.error(f"❌ analyze_with_multi_tf failed: {str(e)}")
            return result


# =========================================================================
# HELPER
# =========================================================================


def analyze_instrument(df: pd.DataFrame, instrument: str) -> Dict:
    """
    Legacy helper (single timeframe).
    """
    analyzer = TechnicalAnalyzer(instrument)
    pdh, pdl = analyzer.calculate_pdh_pdl(df)
    levels = analyzer.calculate_support_resistance(df)
    vol_confirmed, vol_ratio, _ = analyzer.check_volume_confirmation(df)
    breakout = analyzer.detect_breakout(
        df, levels, {"trend_direction": "FLAT", "rsi_15": 50.0}
    )
    retest = analyzer.detect_retest_setup(df, levels)
    inside_bar = analyzer.detect_inside_bar(df)

    return {
        "pdh": pdh,
        "pdl": pdl,
        "levels": levels,
        "volume_confirmed": vol_confirmed,
        "volume_ratio": vol_ratio,
        "breakout_signal": breakout,
        "retest_signal": retest,
        "inside_bar_signal": inside_bar,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("✅ Technical Analysis Module loaded")
