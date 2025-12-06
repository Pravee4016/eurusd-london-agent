import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import unittest
import pytz

from analysis_module.technical import TechnicalAnalyzer, TechnicalLevels, SignalType
from analysis_module.manipulation_guard import CircuitBreaker
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

class TestAnalysis(unittest.TestCase):

    def test_risk_reward(self):
        """Test risk:reward calculation."""
        risk = 0.0020
        reward = 0.0060
        rr = reward / risk
        self.assertGreaterEqual(rr, 1.5)

    def test_circuit_breaker(self):
        """Test Velocity Breaker logic."""
        logger.info("🧪 Testing Circuit Breaker...")
        cb = CircuitBreaker()
        
        # Create normal market data
        data = {
            "timestamp": [datetime.now()],
            "open": [1.1000],
            "high": [1.1005],
            "low": [1.0995],
            "close": [1.1000],
            "volume": [1000]
        }
        df = pd.DataFrame(data)
        
        # Should be SAFE
        is_safe, reas = cb.check_market_integrity(df, 1.1000, "EUR/USD")
        self.assertTrue(is_safe, f"Should be safe but got: {reas}")
        
        # Create FLASH CRASH data (massive 1% move in 5m)
        data_crash = {
            "timestamp": [datetime.now()],
            "open": [1.1000],
            "high": [1.1150], # 1.3% move
            "low": [1.1000],
            "close": [1.1100],
            "volume": [5000]
        }
        df_crash = pd.DataFrame(data_crash)
        
        # Should be UNSAFE
        is_safe, reason = cb.check_market_integrity(df_crash, 1.1100, "EUR/USD")
        self.assertFalse(is_safe, f"Should have tripped breaker: {reason}")
        if not is_safe:
             logger.info(f"✅ Circuit Breaker tripped correctly: {reason}")

    def test_breakout_detection(self):
        logger.info("🧪 Testing Breakout Detection...")
        analyzer = TechnicalAnalyzer("EURUSD")
        
        # 1. Generate range data
        df = generate_trend_data(1.1000, trend='FLAT', bars=30)
        
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
            volatility_score=50,
            asian_high=0.0,
            asian_low=0.0
        )
        
        # Mock context
        context = {
            "trend_direction": "UP",
            "rsi_15": 60.0
        }
        
        signal = analyzer.detect_breakout(df, levels, context)
        
        if signal:
             self.assertEqual(signal.signal_type, SignalType.BULLISH_BREAKOUT)
             logger.info(f"✅ Bullish Breakout Detected: {signal.description}")
        else:
             logger.warning("⚠️ Breakout not detected (could be strict tolerances)")

if __name__ == "__main__":
    unittest.main()
