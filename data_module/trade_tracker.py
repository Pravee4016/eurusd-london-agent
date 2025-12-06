"""
Trade Tracker Module
Tracks individual trade alerts and their outcomes in Firestore.
Isolated for EUR/USD Agent.
"""

import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Optional
import pytz

from google.cloud import firestore
from config.settings import TIME_ZONE, FIRESTORE_COLLECTION_TRADES

logger = logging.getLogger(__name__)

class TradeTracker:
    """Tracks trades and performance stats."""
    
    def __init__(self):
        self.db = None
        self.collection_name = FIRESTORE_COLLECTION_TRADES  # Uses eurusd_trades from settings
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        
        if not self.project_id:
            logger.warning("⚠️ GOOGLE_CLOUD_PROJECT not set, trade tracking disabled")
            return

        try:
            self.db = firestore.Client(project=self.project_id)
        except Exception as e:
            logger.error(f"❌ Firestore init failed for TradeTracker: {str(e)}")

    def record_alert(self, signal: Dict) -> Optional[str]:
        """
        Record a new trade alert.
        Returns trade_id if successful.
        """
        if not self.db:
            return None

        try:
            trade_id = str(uuid.uuid4())
            ist = pytz.timezone(TIME_ZONE)
            now = datetime.now(ist)
            
            # Clean up signal data for storage (remove non-serializable objects)
            trade_data = {
                "trade_id": trade_id,
                "timestamp": now,
                "date": now.strftime("%Y-%m-%d"),
                "instrument": signal.get("instrument"),
                "signal_type": signal.get("signal_type"),
                "price_level": signal.get("price_level"),
                "entry_price": signal.get("entry_price"),
                "stop_loss": signal.get("stop_loss"),
                "take_profit": signal.get("take_profit"),
                "confidence": signal.get("confidence"),
                "risk_reward": signal.get("risk_reward_ratio"),
                "description": signal.get("description"),
                "atr": signal.get("atr", 0.0),
                "status": "OPEN",  # OPEN, WIN, LOSS, BREAKEVEN
                "filters": signal.get("debug_info", {}),
                "outcome": None
            }
            
            self.db.collection(self.collection_name).document(trade_id).set(trade_data)
            logger.info(f"📝 Trade recorded: {trade_id} | {signal.get('signal_type')}")
            return trade_id
            
        except Exception as e:
            logger.error(f"❌ Failed to record trade: {str(e)}")
            return None

    def check_open_trades(self, current_prices: Dict[str, float]) -> int:
        """
        Check all open trades and automatically close them if TP or SL is hit.
        """
        if not self.db:
            return 0

        try:
            ist = pytz.timezone(TIME_ZONE)
            now = datetime.now(ist)
            
            # Query open trades
            trades_ref = self.db.collection(self.collection_name)
            query = trades_ref.where("status", "==", "OPEN").stream()
            
            closed_count = 0
            
            for doc in query:
                trade = doc.to_dict()
                trade_id = trade.get("trade_id")
                instrument = trade.get("instrument")
                entry = trade.get("entry_price")
                tp = trade.get("take_profit")
                sl = trade.get("stop_loss")
                signal_type = trade.get("signal_type", "")
                opened_at = trade.get("timestamp")
                
                # Check based on instrument symbol or common name
                # EurUsd agent might use "EUR/USD" or "EURUSD"
                price = None
                if instrument in current_prices:
                    price = current_prices[instrument]
                elif "EUR" in instrument and "EURUSD" in current_prices:
                    price = current_prices["EURUSD"]
                
                if price is None:
                    continue
                
                current_price = price
                
                # Determine if LONG or SHORT
                is_long = "BULLISH" in signal_type or "SUPPORT" in signal_type or "LONG" in signal_type
                atr = trade.get("atr", 0.0)
                
                # ===========================
                # ATR TRAILING STOP LOGIC
                # ===========================
                trailing_mult = 1.5
                
                if atr > 0:
                    if is_long:
                        potential_sl = current_price - (atr * trailing_mult)
                        if potential_sl > sl:
                            logger.info(f"🔄 Trailing SL updated: {sl:.4f} -> {potential_sl:.4f}")
                            sl = potential_sl
                            doc.reference.update({"stop_loss": sl})
                    else:
                        potential_sl = current_price + (atr * trailing_mult)
                        if potential_sl < sl:
                            logger.info(f"🔄 Trailing SL updated: {sl:.4f} -> {potential_sl:.4f}")
                            sl = potential_sl
                            doc.reference.update({"stop_loss": sl})
                
                outcome = None
                exit_price = None
                
                # Check if TP or SL hit
                if is_long:
                    if current_price >= tp:
                        outcome = "WIN"
                        exit_price = tp
                    elif current_price <= sl:
                        outcome = "LOSS"
                        exit_price = sl
                else:
                    if current_price <= tp:
                        outcome = "WIN"
                        exit_price = tp
                    elif current_price >= sl:
                        outcome = "LOSS"
                        exit_price = sl
                
                # Update trade if outcome determined
                if outcome:
                    if outcome == "WIN":
                         pnl_points = abs(exit_price - entry) * 10000 # Pips
                    else:
                         pnl_points = -abs(exit_price - entry) * 10000 # Pips
                    
                    # Calculate duration
                    duration_mins = (now - opened_at).total_seconds() / 60.0 if opened_at else 0
                    
                    outcome_data = {
                        "status": outcome,
                        "exit_price": exit_price,
                        "pnl_pips": pnl_points,
                        "duration_mins": duration_mins,
                        "closed_by": "AUTO"
                    }
                    
                    # Update in Firestore
                    doc_ref.update({
                        "status": outcome,
                        "outcome": outcome_data,
                        "closed_at": now
                    })
                    
                    closed_count += 1
                    logger.info(
                        f"✅ Trade auto-closed: {signal_type} | "
                        f"{outcome} @ {exit_price:.4f} | P&L: {pnl_points:.1f} pips"
                    )
            
            return closed_count
            
        except Exception as e:
            logger.error(f"❌ Failed to check open trades: {str(e)}")
            return 0

# Singleton
_tracker = None

def get_trade_tracker() -> TradeTracker:
    global _tracker
    if _tracker is None:
        _tracker = TradeTracker()
    return _tracker
