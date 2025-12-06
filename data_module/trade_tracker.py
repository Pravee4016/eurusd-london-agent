"""
Trade Tracker Module
Tracks individual trade alerts and their outcomes in Firestore.
"""

import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pytz

from google.cloud import firestore
from config.settings import TIME_ZONE

logger = logging.getLogger(__name__)

class TradeTracker:
    """Tracks trades and performance stats."""
    
    def __init__(self):
        self.db = None
        self.collection_name = "trades"
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

    def update_outcome(self, trade_id: str, outcome: Dict) -> bool:
        """
        Update trade outcome.
        outcome = {
            "status": "WIN" | "LOSS" | "BREAKEVEN",
            "exit_price": float,
            "pnl_points": float,
            "duration_mins": float
        }
        """
        if not self.db:
            return False

        try:
            doc_ref = self.db.collection(self.collection_name).document(trade_id)
            doc_ref.update({
                "status": outcome.get("status"),
                "outcome": outcome,
                "closed_at": firestore.SERVER_TIMESTAMP
            })
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update trade outcome: {str(e)}")
            return False

    def check_open_trades(self, current_prices: Dict[str, float]) -> int:
        """
        Check all open trades and automatically close them if TP or SL is hit.
        
        Args:
            current_prices: Dict of {instrument: current_price}
            
        Returns:
            Number of trades closed
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
                
                # Skip if we don't have current price for this instrument
                if instrument not in current_prices:
                    continue
                
                current_price = current_prices[instrument]
                
                # Determine if LONG or SHORT
                is_long = "BULLISH" in signal_type or "SUPPORT" in signal_type or "LONG" in signal_type
                
                outcome = None
                exit_price = None
                
                # Check if TP or SL hit
                if is_long:
                    # LONG trade
                    if current_price >= tp:
                        # Target hit - WIN
                        outcome = "WIN"
                        exit_price = tp
                    elif current_price <= sl:
                        # Stop loss hit - LOSS
                        outcome = "LOSS"
                        exit_price = sl
                else:
                    # SHORT trade
                    if current_price <= tp:
                        # Target hit - WIN
                        outcome = "WIN"
                        exit_price = tp
                    elif current_price >= sl:
                        # Stop loss hit - LOSS
                        outcome = "LOSS"
                        exit_price = sl
                
                # Update trade if outcome determined
                if outcome:
                    pnl_points = abs(exit_price - entry) if outcome == "WIN" else -abs(exit_price - entry)
                    
                    # Calculate duration
                    duration_mins = (now - opened_at).total_seconds() / 60.0 if opened_at else 0
                    
                    outcome_data = {
                        "status": outcome,
                        "exit_price": exit_price,
                        "pnl_points": pnl_points,
                        "duration_mins": duration_mins,
                        "closed_by": "AUTO"
                    }
                    
                    # Update in Firestore
                    doc_ref = self.db.collection(self.collection_name).document(trade_id)
                    doc_ref.update({
                        "status": outcome,
                        "outcome": outcome_data,
                        "closed_at": now
                    })
                    
                    closed_count += 1
                    logger.info(
                        f"✅ Trade auto-closed: {instrument} {signal_type} | "
                        f"{outcome} @ {exit_price:.2f} | P&L: {pnl_points:.2f}"
                    )
            
            return closed_count
            
        except Exception as e:
            logger.error(f"❌ Failed to check open trades: {str(e)}")
            return 0

    def get_stats(self, days: int = 7) -> Dict:
        """
        Calculate performance stats for the last N days.
        """
        if not self.db:
            return {}

        try:
            # Calculate start date
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # Query trades
            trades_ref = self.db.collection(self.collection_name)
            query = trades_ref.where("date", ">=", start_date).stream()
            
            total_alerts = 0
            wins = 0
            losses = 0
            by_type = {}
            
            for doc in query:
                trade = doc.to_dict()
                total_alerts += 1
                
                stype = trade.get("signal_type", "UNKNOWN")
                status = trade.get("status", "OPEN")
                
                # Stats by type
                if stype not in by_type:
                    by_type[stype] = {"count": 0, "wins": 0, "losses": 0}
                
                by_type[stype]["count"] += 1
                
                if status == "WIN":
                    wins += 1
                    by_type[stype]["wins"] += 1
                elif status == "LOSS":
                    losses += 1
                    by_type[stype]["losses"] += 1
            
            win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
            
            return {
                "period_days": days,
                "total_alerts": total_alerts,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "by_type": by_type
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get stats: {str(e)}")
            return {}

# Singleton
_tracker = None

def get_trade_tracker() -> TradeTracker:
    global _tracker
    if _tracker is None:
        _tracker = TradeTracker()
    return _tracker
