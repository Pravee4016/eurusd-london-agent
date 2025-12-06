
import pandas as pd
import logging
import pytz
from datetime import datetime, time, timedelta

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("Backtest")

from data_module.fetcher import get_data_fetcher
from analysis_module.technical import TechnicalAnalyzer
from config.settings import TIME_ZONE, MIN_SIGNAL_CONFIDENCE

def run_backtest():
    logger.info("🚀 Starting Backtest for Dec 5, 2025 (London Session)")
    
    fetcher = get_data_fetcher()
    analyzer = TechnicalAnalyzer("EURUSD")
    
    # 1. Fetch Historical Data (last 5 days to ensure ample context)
    # This should cover Dec 5 (yesterday/today depending on TZ)
    logger.info("Dataset: Fetching last 3 days of 5m data using yfinance...")
    # Using protected method directly due to Finnhub timeouts
    df_5m = fetcher._fetch_historical_yfinance("EURUSD", resolution="5", days_back=3)
    
    if df_5m is None or df_5m.empty:
        logger.error("❌ No data fetched")
        return
        
    # Rename columns to lowercase AFTER preprocessing
    # df_5m.columns = [c.lower() for c in df_5m.columns]


    # 1b. Fetch 15m data for MTF context
    df_15m = fetcher._fetch_historical_yfinance("EURUSD", resolution="15", days_back=5)
    if df_15m is not None:
        pass # df_15m.columns = [c.lower() for c in df_15m.columns]
        
    df_daily = fetcher._fetch_historical_yfinance("EURUSD", resolution="D", days_back=5)
    if df_daily is not None:
        pass # df_daily.columns = [c.lower() for c in df_daily.columns]
    
    # 2. Filter for Dec 05
    # Target date: 2025-12-05
    target_date = "2025-12-05"
    
    # Convert index to London time if not already
    london_tz = pytz.timezone(TIME_ZONE)
    if df_5m.index.tzinfo is None:
        df_5m.index = df_5m.index.tz_localize("UTC").tz_convert(london_tz)
    else:
        df_5m.index = df_5m.index.tz_convert(london_tz)
        
    df_day = df_5m[df_5m.index.strftime('%Y-%m-%d') == target_date]
    
    if df_day.empty:
        logger.error(f"❌ No data found for {target_date}")
        logger.info(f"Available dates: {df_5m.index.date.unique()}")
        return
        
    logger.info(f"✅ Loaded {len(df_day)} candles for {target_date}")
    
    # 3. Simulate Trading Session (08:00 - 16:00 GMT)
    # London is GMT+0 in winter, so 08:00 locally
    market_open = time(8, 0)
    market_close = time(16, 0)
    
    signals_found = 0
    
    # Preprocess full datasets once for efficiency (in real sim we'd do it step-by-step but for backtest this is OK as long as we slice)
    # Actually, indicators like EMA/RSI need history.
    # We should preprocess the WHOLE dataset, then slice.
    
    df_5m_proc = fetcher.preprocess_ohlcv(df_5m)
    # NOW lowercase columns for Analyzer
    df_5m_proc.columns = [c.lower() for c in df_5m_proc.columns]
    
    if df_15m is not None:
        df_15m_proc = fetcher.preprocess_ohlcv(df_15m)
        df_15m_proc.columns = [c.lower() for c in df_15m_proc.columns]
    else:
        df_15m_proc = None
        
    if df_daily is not None:
        # Daily usually doesn't need preprocess, just renaming
        df_daily.columns = [c.lower() for c in df_daily.columns]
    
    for i in range(len(df_day)):
        current_candle = df_day.iloc[i]
        current_time = current_candle.name.time()
        
        # Skip pre-market
        if current_time < market_open or current_time > market_close:
            continue
            
        # Slice data up to this point (simulate real-time)
        # We need the full history UP TO this candle
        current_timestamp = current_candle.name
        
        # Slice 5m data: all data up to current timestamp
        slice_5m = df_5m_proc[df_5m_proc.index <= current_timestamp]
        
        # Slice 15m data: all data up to current timestamp
        # (Be careful not to look ahead - use 15m candle that closed BEFORE or AT current time)
        slice_15m = df_15m_proc[df_15m_proc.index <= current_timestamp]
        
        # Run Analysis
        higher_tf_context = analyzer.get_higher_tf_context(slice_15m, slice_5m, df_daily)
        analysis = analyzer.analyze_with_multi_tf(slice_5m, higher_tf_context)
        
        # Check Signals
        breakout = analysis.get("breakout_signal")
        retest = analysis.get("retest_signal")
        inside = analysis.get("inside_bar_signal")
        pin = analysis.get("pin_bar_signal")
        engulfing = analysis.get("engulfing_signal")
        
        timestamp_str = current_timestamp.strftime('%H:%M')
        price_str = f"{current_candle['Close']:.5f}"
        
        found = False
        
        if breakout and breakout.confidence >= MIN_SIGNAL_CONFIDENCE:
            logger.info(f"⏰ {timestamp_str} | 🚀 BREAKOUT ({breakout.signal_type.value}) | Price: {price_str} | Conf: {breakout.confidence}%")
            found = True
            
        if retest and retest.confidence >= MIN_SIGNAL_CONFIDENCE:
            logger.info(f"⏰ {timestamp_str} | 🎯 RETEST ({retest.signal_type.value}) | Price: {price_str} | Conf: {retest.confidence}%")
            found = True
            
        if inside and inside.confidence >= MIN_SIGNAL_CONFIDENCE:
            logger.info(f"⏰ {timestamp_str} | 📊 INSIDE BAR ({inside.signal_type.value}) | Conf: {inside.confidence}%")
            found = True
            
        if pin and pin.confidence >= MIN_SIGNAL_CONFIDENCE:
            logger.info(f"⏰ {timestamp_str} | 🔨 PIN BAR ({pin.signal_type.value}) | Price: {price_str} | Conf: {pin.confidence}%")
            found = True
            
        if engulfing and engulfing.confidence >= MIN_SIGNAL_CONFIDENCE:
            logger.info(f"⏰ {timestamp_str} | 🟢 ENGULFING ({engulfing.signal_type.value}) | Price: {price_str} | Conf: {engulfing.confidence}%")
            found = True
            
        if found:
            signals_found += 1
            
    logger.info("="*50)
    logger.info(f"Backtest Complete. Total Signals: {signals_found}")
    logger.info("="*50)

if __name__ == "__main__":
    run_backtest()
