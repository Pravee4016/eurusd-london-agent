"""
Manipulation Guard (Circuit Breaker)
Protects against Flash Crashes and Freak Trades.
Adapted for Forex (EUR/USD) - No Expiry Logic
"""

import logging
from datetime import datetime
import pandas as pd
from typing import Tuple

from config.settings import (
    MAX_1MIN_MOVE_PCT,
    TIME_ZONE
)

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(self):
        self.triggered = False
        self.trigger_reason = None
        self.trigger_time = None
        self.pause_duration = 0

    def check_market_integrity(self, df_5m: pd.DataFrame, current_price: float, instrument: str = "EUR/USD") -> Tuple[bool, str]:
        """
        Run all safety checks.
        Returns: (is_safe, reason)
        """
        
        # 1. Check if Breaker already tripped
        if self.triggered:
            elapsed = (datetime.now() - self.trigger_time).total_seconds() / 60
            if elapsed < self.pause_duration:
                return False, f"Circuit Breaker Active ({self.trigger_reason}) - {int(self.pause_duration - elapsed)}m remaining"
            else:
                self._reset_breaker()

        # 2. Flash Crash / Velocity Check (1-minute equivalent using last 5m candle limit)
        # Note: Ideally we check tick data or 1m data. Using 5m rapid move proxy.
        if not df_5m.empty:
            last_candle = df_5m.iloc[-1]
            high = last_candle['high']
            low = last_candle['low']
            open_p = last_candle['open']
            
            # Use High-Low range as proxy for volatility/velocity
            move_pct = ((high - low) / open_p) * 100
            
            # If a single 5m candle moves > 2.5x the 1min limit limit, it's a crash/spike
            # For EURUSD, 0.2% * 2.5 = 0.5% move in 5m (approx 50 pips) is extreme
            if move_pct > (MAX_1MIN_MOVE_PCT * 2.5): 
                self._trip_breaker("Flash Move Detected", 15)
                return False, f"Flash Crash Protection: {move_pct:.2f}% move in 5m"

        return True, "Market Normal"

    def _trip_breaker(self, reason: str, duration_mins: int):
        self.triggered = True
        self.trigger_reason = reason
        self.trigger_time = datetime.now()
        self.pause_duration = duration_mins
        logger.warning(f"🚨 CIRCUIT BREAKER TRIPPED: {reason}. Pausing for {duration_mins} mins.")

    def _reset_breaker(self):
        self.triggered = False
        self.trigger_reason = None
        self.trigger_time = None
        logger.info("✅ Circuit Breaker Reset. Resuming operations.")
