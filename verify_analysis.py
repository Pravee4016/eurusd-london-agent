
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
import pytz
from analysis_module.technical import TechnicalAnalyzer, TechnicalLevels, Signal, SignalType
from config.settings import TIME_ZONE

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_mock_candle(timestamp, open_p, high_p, low_p, close_p, volume=1000):
    """Helper to create a single candle row"""
    return {
        "timestamp": timestamp,
        "open": float(open_p),
        "high": float(high_p),
        "low": float(low_p),
        "close": float(close_p),
        "volume": float(volume),
    }

def generate_trend_data(start_price, trend='UP', bars=100):
    """Generate trending data"""
    data = []
    current_price = start_price
    
    start_time = datetime.now(pytz.timezone(TIME_ZONE)) - timedelta(minutes=bars*5)
    
    for i in range(bars):
        timestamp = start_time + timedelta(minutes=i*5)
        
        if trend == 'UP':
            change = np.random.normal(0.0001, 0.00005) # Small positive drift
        elif trend == 'DOWN':
            change = np.random.normal(-0.0001, 0.00005) # Small negative drift
        else:
            change = np.random.normal(0, 0.0001) # Random walk
            
        current_price += change
        
        # Create OHLC
        open_p = current_price
        high_p = open_p + 0.0002
        low_p = open_p - 0.0002
        close_p = open_p + (change * 0.5)
        
        data.append(create_mock_candle(timestamp, open_p, high_p, low_p, close_p))
        
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    return df

def test_breakout_detection():
    logger.info("🧪 Testing Breakout Detection...")
    analyzer = TechnicalAnalyzer("EURUSD")
    
    # 1. Generate range data
    df = generate_trend_data(1.1000, trend='FLAT', bars=30)
    
    # Add a resistance level explicitly
    resistance_level = 1.1020
    
    # Create a breakout candle
    last_candle = create_mock_candle(
        df.index[-1] + timedelta(minutes=5),
        1.1018, 1.1025, 1.1015, 1.1023, volume=5000 # High volume breakout
    )
    
    df = pd.concat([df, pd.DataFrame([last_candle]).set_index('timestamp')])
    
    # Mock levels
    levels = TechnicalLevels(
        support_levels=[1.0980],
        resistance_levels=[1.1020],
        pivot=1.1000,
        pdh=1.1050,
        pdl=1.0950,
        atr=0.0010,
        volatility_score=50
    )
    
    # Mock context
    context = {
        "trend_direction": "UP",
        "rsi_15": 60.0
    }
    
    signal = analyzer.detect_breakout(df, levels, context)
    
    if signal and signal.signal_type == SignalType.BULLISH_BREAKOUT:
        logger.info(f"✅ Bullish Breakout Detected: {signal.description}")
    else:
        logger.error("❌ Failed to detect Bullish Breakout")

def test_pin_bar_detection():
    logger.info("🧪 Testing Pin Bar Detection...")
    analyzer = TechnicalAnalyzer("EURUSD")
    
    df = generate_trend_data(1.1000, trend='DOWN', bars=30)
    
    # Create Hammer at support (1.0980)
    # Open 1.0985, Close 1.0988, Low 1.0975, High 1.0990
    # Range = 15 pips. Body = 3 pips. Lower Wick = 10 pips (>60%)
    hammer = create_mock_candle(
        df.index[-1] + timedelta(minutes=5),
        1.0985, 1.0990, 1.0975, 1.0988, volume=1000
    )
    
    df = pd.concat([df, pd.DataFrame([hammer]).set_index('timestamp')])
    
    levels = TechnicalLevels(
        support_levels=[1.0975], # Exact low match
        resistance_levels=[1.1050],
        pivot=1.1000,
        pdh=1.1050,
        pdl=1.0950,
        atr=0.0010,
        volatility_score=50
    )
    
    context = {"trend_direction": "FLAT", "rsi_15": 30.0} # Oversold
    
    signal = analyzer.detect_pin_bar(df, levels, context)
    
    if signal and signal.signal_type == SignalType.BULLISH_PIN_BAR:
        logger.info(f"✅ Bullish Pin Bar Detected: {signal.description}")
    else:
        logger.error("❌ Failed to detect Bullish Pin Bar")

def test_engulfing_detection():
    logger.info("🧪 Testing Engulfing Detection...")
    analyzer = TechnicalAnalyzer("EURUSD")
    
    df = generate_trend_data(1.1000, trend='DOWN', bars=30)
    
    # Previous Bearish Candle
    prev_candle = create_mock_candle(
         df.index[-1] + timedelta(minutes=5),
         1.1005, 1.1005, 1.0995, 1.0995, volume=1000
    )
    
    # Current Bullish Engulfing Candle
    curr_candle = create_mock_candle(
         df.index[-1] + timedelta(minutes=10),
         1.0994, 1.1010, 1.0994, 1.1010, volume=3000 # High volume
    )
    
    df = pd.concat([df, pd.DataFrame([prev_candle]).set_index('timestamp')])
    df = pd.concat([df, pd.DataFrame([curr_candle]).set_index('timestamp')])
    
    levels = TechnicalLevels(
        support_levels=[1.0990],
        resistance_levels=[1.1050],
        pivot=1.1000,
        pdh=1.1050,
        pdl=1.0950,
        atr=0.0010,
        volatility_score=50
    )
    
    context = {"trend_direction": "UP", "rsi_15": 40.0}
    
    signal = analyzer.detect_engulfing(df, levels, context)
    
    if signal and signal.signal_type == SignalType.BULLISH_ENGULFING:
        logger.info(f"✅ Bullish Engulfing Detected: {signal.description}")
    else:
        logger.error("❌ Failed to detect Bullish Engulfing")

if __name__ == "__main__":
    test_breakout_detection()
    test_pin_bar_detection()
    test_engulfing_detection()
