"""
Persistence Module
Handles state storage using Google Cloud Firestore.
Required for stateless Cloud Function execution to track daily stats.
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional
import json

from google.cloud import firestore
from config.settings import TIME_ZONE, DEBUG_MODE

logger = logging.getLogger(__name__)

class PersistenceManager:
    """Manages daily state in Firestore."""
    
    def __init__(self):
        self.db = None
        self.collection_name = "eurusd_daily_stats"
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        
        if not self.project_id:
            logger.warning("⚠️ GOOGLE_CLOUD_PROJECT not set, persistence disabled")
            return

        try:
            self.db = firestore.Client(project=self.project_id)
            logger.info(f"💾 Firestore initialized | Project: {self.project_id}")
        except Exception as e:
            logger.error(f"❌ Firestore init failed: {str(e)}")

    def _get_today_doc_id(self) -> str:
        """Get document ID for today (YYYY-MM-DD)."""
        return datetime.now().strftime("%Y-%m-%d")

    def increment_stat(self, stat_name: str, value: int = 1):
        """Increment a counter stat."""
        if not self.db:
            return

        try:
            doc_ref = self.db.collection(self.collection_name).document(self._get_today_doc_id())
            
            # Use atomic increment
            doc_ref.set({
                stat_name: firestore.Increment(value),
                "last_updated": firestore.SERVER_TIMESTAMP
            }, merge=True)
            
        except Exception as e:
            logger.error(f"❌ Failed to increment {stat_name}: {str(e)}")

    def add_event(self, event_type: str, event_data: Dict):
        """Add an event (breakout, signal) to the daily list."""
        if not self.db:
            return

        try:
            doc_ref = self.db.collection(self.collection_name).document(self._get_today_doc_id())
            
            # Firestore array_union to append to list
            doc_ref.set({
                f"events.{event_type}": firestore.ArrayUnion([event_data]),
                "last_updated": firestore.SERVER_TIMESTAMP
            }, merge=True)
            
        except Exception as e:
            logger.error(f"❌ Failed to add event {event_type}: {str(e)}")

    def get_daily_stats(self) -> Dict:
        """Retrieve all stats for today."""
        if not self.db:
            return {}

        try:
            doc_ref = self.db.collection(self.collection_name).document(self._get_today_doc_id())
            doc = doc_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            return {}
            
        except Exception as e:
            logger.error(f"❌ Failed to get daily stats: {str(e)}")
            return {}
    
    def save_recent_alerts(self, recent_alerts: Dict[str, datetime]):
        """
        Save recent alerts to Firestore for duplicate detection across executions.
        
        Args:
            recent_alerts: Dict of {alert_key: timestamp}
        """
        if not self.db:
            return
        
        try:
            doc_ref = self.db.collection("eurusd_system_state").document("recent_alerts")
            
            # Convert datetime objects to ISO strings for Firestore
            alerts_serialized = {
                key: timestamp.isoformat() 
                for key, timestamp in recent_alerts.items()
            }
            
            doc_ref.set({
                "alerts": alerts_serialized,
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            
            logger.debug(f"💾 Saved {len(recent_alerts)} recent alerts to Firestore")
        
        except Exception as e:
            logger.error(f"❌ Failed to save recent alerts: {e}")
    
    def get_recent_alerts(self) -> Dict[str, datetime]:
        """
        Retrieve recent alerts from Firestore.
        
        Returns:
            Dict of {alert_key: timestamp}
        """
        if not self.db:
            return {}
        
        try:
            doc_ref = self.db.collection("eurusd_system_state").document("recent_alerts")
            doc = doc_ref.get()
            
            if not doc.exists:
                return {}
            
            data = doc.to_dict()
            alerts_serialized = data.get("alerts", {})
            
            # Convert ISO strings back to datetime objects
            from datetime import datetime
            import pytz
            
            recent_alerts = {}
            ist = pytz.timezone("Asia/Kolkata")
            
            for key, timestamp_str in alerts_serialized.items():
                try:
                    # Parse ISO string and localize to IST
                    dt = datetime.fromisoformat(timestamp_str)
                    if dt.tzinfo is None:
                        dt = ist.localize(dt)
                    recent_alerts[key] = dt
                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse timestamp for {key}: {e}")
            
            logger.debug(f"📂 Loaded {len(recent_alerts)} recent alerts from Firestore")
            return recent_alerts
        
        except Exception as e:
            logger.error(f"❌ Failed to get recent alerts: {e}")
            return {}

# =========================================================================
# SINGLETON
# =========================================================================

_persistence: Optional[PersistenceManager] = None


def get_persistence() -> PersistenceManager:
    """Singleton pattern for PersistenceManager."""
    global _persistence
    if _persistence is None:
        _persistence = PersistenceManager()
    return _persistence
