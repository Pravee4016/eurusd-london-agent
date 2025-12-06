"""
EUR/USD LONDON SESSION TRADING AGENT - Main Orchestrator
Coordinates: Data → Technical Analysis → AI → Telegram Alerts
"""

import logging
import sys
from datetime import datetime, time, timedelta
from typing import Dict, List, Tuple

import pytz
import os
from flask import Flask, request

from config.settings import (
    INSTRUMENTS,
    ANALYSIS_START_TIME,
    MARKET_CLOSE_TIME,
    TIME_ZONE,
    DEBUG_MODE,
    MIN_SIGNAL_CONFIDENCE,
)

from data_module.fetcher import get_data_fetcher, DataFetcher
from analysis_module.technical import TechnicalAnalyzer
from ai_module.groq_analyzer import get_analyzer
from telegram_module.bot_handler import get_bot
from data_module.persistence import get_persistence
from data_module.trade_tracker import get_trade_tracker
from analysis_module.manipulation_guard import CircuitBreaker

# ------------------------------------------------------
# Market Hours Check (moved to cloud_function_handler)
# ------------------------------------------------------
def _is_market_hours_quick():
    """Quick market hours check for early exit (London session)."""
    london_tz = pytz.timezone(TIME_ZONE)
    now = datetime.now(london_tz).time()
    # London session: 08:00-16:00 GMT
    return time(8, 0) <= now <= time(16, 0)

logger = logging.getLogger(__name__)


def setup_logging():
    log_format = "%(asctime)s | %(name)s | %(levelname)-8s | %(message)s"
    log_level = logging.DEBUG if DEBUG_MODE else logging.INFO

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("./logs/trading_agent.log", mode="a"),
        ],
    )

    return logging.getLogger(__name__)


logger = setup_logging()


class NiftyTradingAgent:
    """Main trading agent orchestrator."""

    def __init__(self):
        self.fetcher: DataFetcher = get_data_fetcher()
        self.ai_analyzer = get_analyzer()
        self.telegram_bot = get_bot()
        self.persistence = get_persistence()
        self.trade_tracker = get_trade_tracker()
        self.circuit_breaker = CircuitBreaker()
        
        self.signals_generated: List[Dict] = []
        self.alerts_sent = 0
        
        # Daily event tracking for EOD summary
        self.daily_breakouts: List[Dict] = []
        self.daily_breakdowns: List[Dict] = []
        self.daily_retests: List[Dict] = []
        self.daily_reversals: List[Dict] = []
        self.daily_data_fetches = 0
        self.daily_analyses = 0
        
        # Duplicate alert prevention - Load from Firestore (persistent across executions)
        self.recent_alerts: Dict[str, datetime] = self.persistence.get_recent_alerts()
        logger.info(f"📂 Loaded {len(self.recent_alerts)} recent alerts from Firestore")
        
        # Level-based memory (tracks S/R levels to prevent repeats all day)
        self.daily_level_memory: set = set()

        logger.info("=" * 70)
        logger.info("🚀 EUR/USD LONDON SESSION TRADING AGENT INITIALIZED")
        logger.info("=" * 70)
        logger.info(f"Mode: {'DEBUG' if DEBUG_MODE else 'PRODUCTION'}")
        logger.info(f"Timezone: {TIME_ZONE}")
        logger.info(f"Analysis start time: {ANALYSIS_START_TIME}")
        logger.info(f"Currency Pair: EUR/USD")
        logger.info(f"Session: London (08:00-16:00 GMT)")

    # =====================================================================
    # MAIN EXECUTION
    # =====================================================================

    def run_analysis(self, instruments: List[str] = None) -> Dict:
        """
        Main analysis execution loop.
        """
        if instruments is None:
            instruments = [
                k for k, v in INSTRUMENTS.items() if v.get("active", False)
            ]

        logger.info(f"\n📊 ANALYSIS STARTED | Instruments: {instruments}")
        logger.info("=" * 70)

        # Track data fetch count
        self.persistence.increment_stat("data_fetches", len(instruments))

        results = {
            "timestamp": datetime.now().isoformat(),
            "instruments_analyzed": 0,
            "signals_generated": 0,
            "alerts_sent": 0,
            "errors": 0,
            "details": {},
        }

        for instrument in instruments:
            try:
                logger.info(f"\n🔍 Analyzing: {instrument}")
                logger.info("-" * 70)

                # Fetch real-time price first for Circuit Breaker
                forex_data = self.fetcher.fetch_forex_data(instrument) or {}
                current_price = forex_data.get("last_price", 0)

                # ===========================
                # 1. VELOCITY BREAKER CHECK
                # ===========================
                # We need fresh 5m data for velocity check
                df_5m_integrity = self.fetcher.fetch_historical_data(
                     instrument, resolution="5", days_back=1
                )
                if df_5m_integrity is not None and not df_5m_integrity.empty:
                     df_5m_integrity = self.fetcher.preprocess_ohlcv(df_5m_integrity)
                     is_safe, reason = self.circuit_breaker.check_market_integrity(
                          df_5m_integrity, current_price, instrument
                     )
                     if not is_safe:
                          logger.warning(f"⛔ MARKET UNSAFE: {reason}. Skipping analysis.")
                          results["errors"] += 1
                          results["details"][instrument] = {"error": reason}
                          continue

                instrument_result = self._analyze_single_instrument(instrument, forex_data)
                results["details"][instrument] = instrument_result

                if instrument_result["success"]:
                    results["instruments_analyzed"] += 1
                    results["signals_generated"] += instrument_result[
                        "signals_count"
                    ]
                    results["alerts_sent"] += instrument_result["alerts_sent"]
                else:
                    results["errors"] += 1
                
                self.persistence.increment_stat("analyses_run")

            except Exception as e:
                logger.error(
                    f"❌ Error analyzing {instrument}: {str(e)}",
                    exc_info=DEBUG_MODE,
                )
                results["errors"] += 1

        self._print_analysis_summary(results)
        return results

    def _analyze_single_instrument(self, instrument: str, forex_data: Dict = None) -> Dict:
        """Analyze single instrument with 5m + 15m data and MTF filters."""
        result = {
            "instrument": instrument,
            "success": False,
            "signals_count": 0,
            "alerts_sent": 0,
            "signals": [],
            "errors": [],
        }

        try:
            logger.debug("Step 1: Checking forex data...")
            if not forex_data:
                 forex_data = self.fetcher.fetch_forex_data(instrument)
            
            if not forex_data:
                logger.warning("⚠️  Forex data fetch failed")
                forex_data = {}  # Empty dict as fallback

            logger.debug("Step 2: Fetching 5m and 15m historical data...")
            df_5m = self.fetcher.fetch_historical_data(
                instrument, resolution="5", days_back=5
            )
            df_15m = self.fetcher.fetch_historical_data(
                instrument, resolution="15", days_back=10
            )
            # Fetch daily data for previous day trend
            df_daily = self.fetcher.fetch_historical_data(
                instrument, resolution="D", days_back=5
            )

            if df_5m is None or df_5m.empty:
                logger.error("❌ No 5m historical data available")
                result["errors"].append("5m data unavailable")
                return result

            if df_15m is None or df_15m.empty:
                logger.error("❌ No 15m historical data available")
                result["errors"].append("15m data unavailable")
                return result

            df_5m = self.fetcher.preprocess_ohlcv(df_5m)
            df_15m = self.fetcher.preprocess_ohlcv(df_15m)
            if df_daily is not None and not df_daily.empty:
                df_daily = self.fetcher.preprocess_ohlcv(df_daily)

            logger.debug(
                f"5m shape: {df_5m.shape} | 15m shape: {df_15m.shape}"
            )

            analyzer = TechnicalAnalyzer(instrument)
            higher_tf_context = analyzer.get_higher_tf_context(df_15m, df_5m, df_daily)
            analysis = analyzer.analyze_with_multi_tf(
                df_5m, higher_tf_context
            )
            
            # Check and auto-close open trades based on current price
            current_price = forex_data.get("last_price", 0)
            if current_price > 0:
                closed = self.trade_tracker.check_open_trades({instrument: current_price})
                if closed > 0:
                    logger.info(f"   ✅ Auto-closed {closed} trade(s) for {instrument}")

            signals = self._generate_signals(instrument, analysis, forex_data)

            enriched_signals = []
            for sig in signals:
                if "BREAKOUT" in sig.get("signal_type", ""):
                    direction = (
                        "UP"
                        if "BULLISH" in sig["signal_type"]
                        else "DOWN"
                    )
                    is_false, fb_details = analyzer.detect_false_breakout(
                        df_5m, sig["price_level"], direction
                    )
                    sig["false_breakout"] = is_false
                    sig["false_breakout_details"] = fb_details
                enriched_signals.append(sig)

            final_signals = []
            for sig in enriched_signals:
                if sig.get("false_breakout"):
                    logger.info(
                        "⏭️  Suppressing alert due to false breakout | "
                        f"{sig['instrument']} @ {sig['price_level']:.2f}"
                    )
                    # Optionally send a dedicated false breakout alert:
                    # self.telegram_bot.send_false_breakout_alert(sig)
                    continue
                final_signals.append(sig)

            result["signals"] = final_signals
            result["signals_count"] = len(final_signals)

            for signal in final_signals:
                ai_analysis = self._get_ai_analysis(signal)
                signal["ai_analysis"] = ai_analysis
                
                # Track events for daily summary
                self._track_daily_event(signal)

                if self._send_alert(signal):
                    result["alerts_sent"] += 1
                    self.alerts_sent += 1
            
            self.daily_analyses += 1

            logger.info(
                f"✅ {instrument} analysis complete | "
                f"{result['signals_count']} signals | "
                f"{result['alerts_sent']} alerts sent"
            )
            result["success"] = True
            return result

        except Exception as e:
            logger.error(f"❌ Exception: {str(e)}", exc_info=DEBUG_MODE)
            result["errors"].append(str(e))
            return result

    def _generate_signals(
        self, instrument: str, analysis: Dict, nse_data: Dict
    ) -> List[Dict]:
        """
        Generate trading signals from analysis with confidence gate.
        """
        from config.settings import MAX_SAME_DIRECTION_ALERTS
        
        signals: List[Dict] = []
        current_price = float(nse_data.get("price", 0) or 0) if nse_data else 0

        try:
            # ====================
            # Choppy Session Filter
            # ====================
            analyzer = TechnicalAnalyzer(instrument)
            is_choppy, choppy_reason = analyzer._is_choppy_session(
                self.fetcher.get_historical_data(instrument, "5m", 100)
            )
            if is_choppy:
                logger.warning(f"⏭️ Choppy session detected: {choppy_reason} - suppressing signals")
                return signals
            
            # ====================
            # Correlation Check (max same-direction alerts in 15 mins)
            # ====================
            tz = pytz.timezone(TIME_ZONE)
            now = datetime.now(tz)
            recent_15min = now - timedelta(minutes=15)
            
            recent_same_direction = sum(
                1 for key, ts in self.recent_alerts.items()
                if ts > recent_15min and (
                    ("BULLISH" in key or "SUPPORT" in key) == 
                    (analysis.get("breakout_signal") and "BULLISH" in str(analysis.get("breakout_signal")))
                )
            )
            
            if recent_same_direction >= MAX_SAME_DIRECTION_ALERTS:
                logger.warning(f"⏭️ Correlation limit: {recent_same_direction} similar directional alerts in 15m")
                return signals

            breakout = analysis.get("breakout_signal")
            retest = analysis.get("retest_signal")
            inside_bar = analysis.get("inside_bar_signal")

            if breakout:
                sig = {
                    "instrument": instrument,
                    "signal_type": breakout.signal_type.value,
                    "entry_price": breakout.entry_price,
                    "stop_loss": breakout.stop_loss,
                    "take_profit": breakout.take_profit,
                    "confidence": breakout.confidence,
                    "volume_confirmed": breakout.volume_confirmed,
                    "momentum_confirmed": breakout.momentum_confirmed,
                    "risk_reward_ratio": breakout.risk_reward_ratio,
                    "description": breakout.description,
                    "price_level": breakout.price_level,
                    "timestamp": breakout.timestamp.isoformat(),
                }
                if sig["confidence"] >= MIN_SIGNAL_CONFIDENCE:
                    logger.info(
                        f"   🚀 {sig['signal_type']} | Entry: {sig['entry_price']:.2f} "
                        f"| Conf: {sig['confidence']:.1f}%"
                    )
                    signals.append(sig)
                else:
                    logger.info(
                        f"   ⏭️  {sig['signal_type']} dropped (low confidence "
                        f"{sig['confidence']:.1f}%)"
                    )

            if retest:
                sig = {
                    "instrument": instrument,
                    "signal_type": retest.signal_type.value,
                    "entry_price": retest.entry_price,
                    "stop_loss": retest.stop_loss,
                    "take_profit": retest.take_profit,
                    "confidence": retest.confidence,
                    "price_level": retest.price_level,
                    "description": retest.description,
                    "timestamp": retest.timestamp.isoformat(),
                }
                if sig["confidence"] >= MIN_SIGNAL_CONFIDENCE:
                    logger.info(
                        f"   🎯 {sig['signal_type']} | Level: {sig['price_level']:.2f} "
                        f"| Conf: {sig['confidence']:.1f}%"
                    )
                    signals.append(sig)

            if inside_bar:
                sig = {
                    "instrument": instrument,
                    "signal_type": inside_bar.signal_type.value,
                    "entry_price": inside_bar.entry_price,
                    "stop_loss": inside_bar.stop_loss,
                    "take_profit": inside_bar.take_profit,
                    "confidence": inside_bar.confidence,
                    "description": inside_bar.description,
                    "timestamp": inside_bar.timestamp.isoformat(),
                }
                if sig["confidence"] >= MIN_SIGNAL_CONFIDENCE:
                    logger.info(
                        f"   📊 {sig['signal_type']} | Conf: {sig['confidence']:.1f}%"
                    )
                    signals.append(sig)

            # Pin Bar Signals
            pin_bar = analysis.get("pin_bar_signal")
            if pin_bar:
                sig = {
                    "instrument": instrument,
                    "signal_type": pin_bar.signal_type.value,
                    "entry_price": pin_bar.entry_price,
                    "stop_loss": pin_bar.stop_loss,
                    "take_profit": pin_bar.take_profit,
                    "confidence": pin_bar.confidence,
                    "price_level": pin_bar.price_level,
                    "description": pin_bar.description,
                    "risk_reward_ratio": pin_bar.risk_reward_ratio,
                    "timestamp": pin_bar.timestamp.isoformat(),
                }
                if sig["confidence"] >= MIN_SIGNAL_CONFIDENCE:
                    logger.info(
                        f"   🔨 {sig['signal_type']} | Level: {sig['price_level']:.2f} | "
                        f"Conf: {sig['confidence']:.1f}% | RR: {sig['risk_reward_ratio']:.1f}"
                    )
                    signals.append(sig)

            # Engulfing Signals
            engulfing = analysis.get("engulfing_signal")
            if engulfing:
                sig = {
                    "instrument": instrument,
                    "signal_type": engulfing.signal_type.value,
                    "entry_price": engulfing.entry_price,
                    "stop_loss": engulfing.stop_loss,
                    "take_profit": engulfing.take_profit,
                    "confidence": engulfing.confidence,
                    "price_level": engulfing.price_level,
                    "description": engulfing.description,
                    "risk_reward_ratio": engulfing.risk_reward_ratio,
                    "timestamp": engulfing.timestamp.isoformat(),
                }
                if sig["confidence"] >= MIN_SIGNAL_CONFIDENCE:
                    logger.info(
                        f"   🟢 {sig['signal_type']} | Level: {sig['price_level']:.2f} | "
                        f"Conf: {sig['confidence']:.1f}% | RR: {sig['risk_reward_ratio']:.1f}"
                    )
                    signals.append(sig)

            if analysis.get("breakout_signal") and not analysis.get(
                "volume_confirmed"
            ):
                logger.warning("   ⚠️  Breakout without volume confirmation")

            # ====================
            # EMERGENCY FIX: Detect Conflicting Signals
            # ====================
            # If both LONG and SHORT signals detected in same cycle, keep only highest confidence
            if len(signals) > 1:
                long_signals = [s for s in signals if any(x in s["signal_type"] for x in ["BULLISH", "SUPPORT"])]
                short_signals = [s for s in signals if any(x in s["signal_type"] for x in ["BEARISH", "RESISTANCE"])]
                
                if long_signals and short_signals:
                    # CONFLICT DETECTED - both LONG and SHORT at same time
                    logger.warning(
                        f"⚠️ CONFLICT: Both LONG and SHORT signals detected | "
                        f"Long: {len(long_signals)} | Short: {len(short_signals)}"
                    )
                    
                    # Take only the highest confidence signal
                    all_sigs = long_signals + short_signals
                    best_signal = max(all_sigs, key=lambda x: x.get('confidence', 0))
                    
                    logger.warning(
                        f"   ✅ Keeping highest confidence: {best_signal['signal_type']} "
                        f"({best_signal['confidence']:.0f}%)"
                    )
                    
                    # Filter out all except the best
                    signals = [best_signal]

            return signals

        except Exception as e:
            logger.error(f"❌ Signal generation failed: {str(e)}")
            return []

    def _get_ai_analysis(self, signal: Dict) -> Dict:
        """Get AI analysis for a given signal."""
        try:
            signal_data = {
                "instrument": signal.get("instrument"),
                "signal_type": signal.get("signal_type"),
                "price_level": signal.get("price_level"),
                "entry": signal.get("entry_price"),
                "sl": signal.get("stop_loss"),
                "tp": signal.get("take_profit"),
                "technical_data": {
                    "volume_confirmed": signal.get("volume_confirmed"),
                    "momentum_confirmed": signal.get("momentum_confirmed"),
                    "rr_ratio": signal.get("risk_reward_ratio"),
                },
            }
            analysis = self.ai_analyzer.analyze_signal(signal_data)
            logger.debug(
                f"   AI Analysis: {analysis.get('recommendation')} | "
                f"Conf: {analysis.get('confidence')}%"
            )
            return analysis

        except Exception as e:
            logger.warning(f"⚠️  AI analysis failed: {str(e)}")
            return {"recommendation": "HOLD", "confidence": 50}

    def _check_alert_limits(self, signal: Dict) -> Tuple[bool, str]:
        """
        Check if sending this alert would exceed daily limits.
        
        Returns:
            (can_send, rejection_reason)
        """
        try:
            from config.settings import (
                MAX_ALERTS_PER_DAY,
                MAX_ALERTS_PER_TYPE,
                MAX_ALERTS_PER_INSTRUMENT
            )
            
            # Get today's stats from persistence
            try:
                today_stats = self.persistence.get_daily_stats()
                total_alerts = today_stats.get("alerts_sent", 0)
            except:
                # If persistence fails, allow alert (fail open)
                return True, ""
            
            instrument = signal.get("instrument", "")
            signal_type = signal.get("signal_type", "")
            
            # 1. Check total daily limit
            if total_alerts >= MAX_ALERTS_PER_DAY:
                return False, f"Daily limit reached ({total_alerts}/{MAX_ALERTS_PER_DAY})"
            
            # 2. Check per-type limit (count alerts of this type today)
            # We approximate by checking recent_alerts for similar types
            recent_of_type = sum(
                1 for key in self.recent_alerts.keys()
                if signal_type in key
            )
            
            if recent_of_type >= MAX_ALERTS_PER_TYPE:
                return False, f"{signal_type} limit reached ({recent_of_type}/{MAX_ALERTS_PER_TYPE})"
            
            # 3. Check per-instrument limit
            recent_for_instrument = sum(
                1 for key in self.recent_alerts.keys()
                if key.startswith(instrument)
            )
            
            if recent_for_instrument >= MAX_ALERTS_PER_INSTRUMENT:
                return False, f"{instrument} limit reached ({recent_for_instrument}/{MAX_ALERTS_PER_INSTRUMENT})"
            
            return True, ""
            
        except Exception as e:
            logger.warning(f"⚠️ Alert limit check failed: {str(e)}")
            return True, ""  # Fail open

    def _send_alert(self, signal: Dict) -> bool:
        """Send Telegram alert for a signal with duplicate prevention and limits."""
        try:
            import pytz
            
            stype = signal.get("signal_type", "")
            instrument = signal.get("instrument", "")
            price_level = signal.get("price_level", 0)
            
            # ====================
            # Alert Limit Check
            # ====================
            can_send, reject_reason = self._check_alert_limits(signal)
            if not can_send:
                logger.warning(f"⏭️ Alert limit: {reject_reason}")
                return False
            
            # ====================
            # Duplicate & Conflict Prevention
            # ====================
            # ====================
            # Duplicate & Conflict Prevention
            # ====================
            ist = pytz.timezone(TIME_ZONE)  # London timezone for EUR/USD
            now = datetime.now(ist)
            
            # 1. Fuzzy Duplicate Check (30 min cooldown)
            # Check for same instrument + same type + nearby level
            # This suppresses TRUE duplicates but allows valid re-entries after 30 min
            is_duplicate = False
            for key, timestamp in self.recent_alerts.items():
                parts = key.split("_")
                if len(parts) < 3: continue
                
                prev_inst = parts[0]
                prev_type = "_".join(parts[1:-1])
                prev_level = float(parts[-1])
                
                # Check if same instrument and signal type
                if prev_inst == instrument and prev_type == stype:
                    # Check price proximity (within 0.1%)
                    # e.g. 26000 vs 26026 is 0.1% diff -> Duplicate
                    if abs(prev_level - price_level) < (price_level * 0.001):
                        time_diff = (now - timestamp).total_seconds() / 60.0
                        if time_diff < 30:
                            logger.info(
                                f"⏭️ Skipping duplicate alert (fuzzy) | {instrument} {stype} @ {price_level:.2f} | "
                                f"Close to {prev_level:.2f} ({time_diff:.1f}m ago)"
                            )
                            return False

            # 2. Directional Conflict Check (15 min cooldown)
            
            # 1b. Level-Based Memory (all-day blocking at same S/R level)
            # Track specific S/R levels and block any signal at same level for entire day
            # Round to nearest 25 points to catch nearby levels (26130, 26135, 26140 all → 26125/26150)
            level_key = f"{instrument}_{stype}_level_{round(price_level / 25) * 25:.0f}"
            if hasattr(self, 'daily_level_memory'):
                if level_key in self.daily_level_memory:
                    logger.info(
                        f"⏭️ Skipping repeat at same level | {instrument} {stype} @ {price_level:.2f} | "
                        f"Already alerted at this 25-point zone today"
                    )
                    return False
            else:
                # Initialize if doesn't exist
                self.daily_level_memory = set()
            # Prevent LONG signal if SHORT sent recently at same level (and vice versa)
            current_direction = "LONG" if "BULLISH" in stype or "SUPPORT" in stype else "SHORT"
            
            for key, timestamp in self.recent_alerts.items():
                parts = key.split("_")
                if len(parts) < 3: continue
                
                prev_inst = parts[0]
                prev_type = "_".join(parts[1:-1])
                prev_level = float(parts[-1])
                
                # Check if same instrument and nearby level (within 0.2%)
                if prev_inst == instrument and abs(prev_level - price_level) < (price_level * 0.002):
                    prev_direction = "LONG" if "BULLISH" in prev_type or "SUPPORT" in prev_type else "SHORT"
                    
                    # If directions oppose and within 15 mins
                    if current_direction != prev_direction:
                        conflict_diff = (now - timestamp).total_seconds() / 60.0
                        if conflict_diff < 15:
                            
                            # EXCEPTION: Allow if price moved significantly against previous direction?
                            # Actually, if we are at the "same level" (within 0.2%), we haven't moved significantly.
                            # So we stick to the chop filter.
                            
                            logger.info(
                                f"⏭️ Skipping conflicting signal | {current_direction} vs recent {prev_direction} | "
                                f"Diff: {conflict_diff:.1f} mins"
                            )
                            return False
            
            # Create key for storage using actual entry price (not rounded price_level)
            # This ensures fuzzy duplicate check can compare actual prices
            entry_price = signal.get("entry_price", price_level)
            alert_key = f"{instrument}_{stype}_{entry_price:.2f}"
            
            # ====================
            # Send Alert
            # ====================
            if "BREAKOUT" in stype or "BREAKDOWN" in stype:
                success = self.telegram_bot.send_breakout_alert(signal)
            elif "RETEST" in stype or "SUPPORT_BOUNCE" in stype or "RESISTANCE_BOUNCE" in stype:
                success = self.telegram_bot.send_retest_alert(signal)
            elif "INSIDE_BAR" in stype:
                success = self.telegram_bot.send_inside_bar_alert(signal)
            elif "PIN_BAR" in stype or "ENGULFING" in stype:
                # Use retest alert format for pin bars and engulfing (similar structure)
                success = self.telegram_bot.send_retest_alert(signal)
            else:
                msg = (
                    f"{stype}\nEntry: {signal.get('entry_price')}\n"
                    f"{signal.get('description', '')}"
                )
                success = self.telegram_bot.send_message(msg)

            if success:
                logger.info("   ✅ Telegram alert sent")
                self.persistence.increment_stat("alerts_sent")
                
                # Record trade for performance tracking
                trade_id = self.trade_tracker.record_alert(signal)
                if trade_id:
                    logger.info(f"   📝 Trade tracked: {trade_id}")
                else:
                    logger.warning("   ⚠️ Failed to track trade")
                
                # Record this alert to prevent duplicates
                self.recent_alerts[alert_key] = now
                
                # Record level for all-day blocking (25-point zones)
                level_key = f"{instrument}_{stype}_level_{round(price_level / 25) * 25:.0f}"
                self.daily_level_memory.add(level_key)
                
                # Cleanup old entries (older than 6 hours - full trading session)
                cutoff_time = now - timedelta(hours=6)
                self.recent_alerts = {
                    k: v for k, v in self.recent_alerts.items() 
                    if v > cutoff_time
                }
                
                # Save to Firestore for persistence across executions
                self.persistence.save_recent_alerts(self.recent_alerts)
            else:
                logger.warning("   ⚠️  Telegram alert failed")
            return success

        except Exception as e:
            logger.error(f"❌ Alert sending failed: {str(e)}")
            return False

    # =====================================================================
    # DAILY EVENT TRACKING & SUMMARY
    # =====================================================================

    def _track_daily_event(self, signal: Dict):
        """Track signal event for daily summary."""
        signal_type = signal.get("signal_type", "")
        
        # Local tracking - categorize all signal types
        if signal_type == "BULLISH_BREAKOUT":
            self.daily_breakouts.append(signal)
            self.persistence.add_event("breakouts", signal)
        elif signal_type == "BEARISH_BREAKOUT" or "BREAKDOWN" in signal_type:
            self.daily_breakdowns.append(signal)
            self.persistence.add_event("breakdowns", signal)
        elif any(x in signal_type for x in ["RETEST", "BOUNCE", "PIN_BAR", "ENGULFING", "INSIDE_BAR"]):
            self.daily_retests.append(signal)
            self.persistence.add_event("retests", signal)
        # Could add reversal detection logic here if needed

    def generate_daily_summary(self) -> Dict:
        """Generate comprehensive end-of-day market summary."""
        try:
            logger.info("📊 Generating end-of-day market summary")
            
            # Fetch persisted stats
            stored_stats = self.persistence.get_daily_stats()
            events = stored_stats.get("events", {})
            
            instruments = [
                k for k, v in INSTRUMENTS.items() if v.get("active", False)
            ]
            
            summary = {
                "timestamp": datetime.now().isoformat(),
                "instruments": {},
                "statistics": {
                    "data_fetches": stored_stats.get("data_fetches", 0),
                    "analyses_run": stored_stats.get("analyses_run", 0),
                    "alerts_sent": stored_stats.get("alerts_sent", 0),
                    "breakouts": len(events.get("breakouts", [])),
                    "breakdowns": len(events.get("breakdowns", [])),
                    "retests": len(events.get("retests", [])),
                    "reversals": len(events.get("reversals", [])),
                },
                "events": events
            }
            
            # Get latest data for each instrument
            for instrument in instruments:
                try:
                    # Fetch latest daily candle
                    df_day = self.fetcher.fetch_historical_data(
                        instrument, period="2d", interval="1d"
                    )
                    
                    if df_day is not None and not df_day.empty:
                        df_day = self.fetcher.preprocess_ohlcv(df_day)
                        latest = df_day.iloc[-1]
                        
                        # Get PDH/PDL for context
                        pdh_pdl = self.fetcher.get_previous_day_stats(instrument)
                        
                        # Get intraday data for trend analysis
                        df_5m = self.fetcher.fetch_historical_data(
                            instrument, period="1d", interval="5m"
                        )
                        
                        # Calculate short-term trend (last hour of trading)
                        short_term_trend = "NEUTRAL"
                        long_term_trend = "NEUTRAL"
                        
                        if df_5m is not None and not df_5m.empty and len(df_5m) >= 12:
                            df_5m = self.fetcher.preprocess_ohlcv(df_5m)
                            last_12 = df_5m.tail(12)  # Last hour
                            
                            if last_12.iloc[-1]["close"] > last_12.iloc[0]["close"] * 1.001:
                                short_term_trend = "BULLISH"
                            elif last_12.iloc[-1]["close"] < last_12.iloc[0]["close"] * 0.999:
                                short_term_trend = "BEARISH"
                        
                        # Long-term trend from daily close vs open
                        if latest["close"] > latest["open"] * 1.005:
                            long_term_trend = "BULLISH"
                        elif latest["close"] < latest["open"] * 0.995:
                            long_term_trend = "BEARISH"
                        
                        change_pct = ((latest["close"] - latest["open"]) / latest["open"]) * 100
                        
                        summary["instruments"][instrument] = {
                            "open": latest["open"],
                            "high": latest["high"],
                            "low": latest["low"],
                            "close": latest["close"],
                            "change_pct": change_pct,
                            "pdh": pdh_pdl.get("pdh") if pdh_pdl else None,
                            "pdl": pdh_pdl.get("pdl") if pdh_pdl else None,
                            "short_term_trend": short_term_trend,
                            "long_term_trend": long_term_trend,
                        }
                        
                except Exception as e:
                    logger.error(f"Error getting summary for {instrument}: {str(e)}")
            
            # Get AI forecast
            summary["ai_forecast"] = self._get_ai_market_forecast(summary)
            
            # Get performance stats
            summary["performance"] = self.trade_tracker.get_stats(days=1)
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate daily summary: {str(e)}")
            return {}

    def _get_ai_market_forecast(self, summary: Dict) -> Dict:
        """Get AI-powered market forecast for next trading day."""
        try:
            # Build context for AI
            context_parts = []
            
            for inst, data in summary.get("instruments", {}).items():
                context_parts.append(
                    f"{inst}: Close {data['close']:.2f} ({data['change_pct']:+.2f}%), "
                    f"Trend: {data['short_term_trend']}/{data['long_term_trend']}"
                )
            
            stats = summary.get("statistics", {})
            context_parts.append(
                f"Today's activity: {stats.get('breakouts', 0)} breakouts, "
                f"{stats.get('breakdowns', 0)} breakdowns, {stats.get('retests', 0)} retests"
            )
            
            context = ". ".join(context_parts)
            
            forecast = self.ai_analyzer.forecast_market_outlook(context)
            return forecast
            
        except Exception as e:
            logger.warning(f"AI forecast failed: {str(e)}")
            return {"outlook": "NEUTRAL", "confidence": 50, "summary": "Forecast unavailable"}

    # =====================================================================
    # UTILITY
    # =====================================================================

    def _print_analysis_summary(self, results: Dict):
        logger.info("\n" + "=" * 70)
        logger.info("📊 ANALYSIS SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Timestamp: {results['timestamp']}")
        logger.info(
            f"Instruments Analyzed: {results['instruments_analyzed']}"
        )
        logger.info(
            f"Total Signals Generated: {results['signals_generated']}"
        )
        logger.info(f"Alerts Sent: {results['alerts_sent']}")
        logger.info(f"Errors: {results['errors']}")
        logger.info("=" * 70 + "\n")

    def is_market_hours(self) -> bool:
        """Check if current time is within market hours (Mon-Fri, IST)."""
        tz = pytz.timezone(TIME_ZONE)
        now = datetime.now(tz)

        market_open = datetime.strptime(
            ANALYSIS_START_TIME, "%H:%M"
        ).time()
        market_close = datetime.strptime(
            MARKET_CLOSE_TIME, "%H:%M"
        ).time()

        if now.weekday() > 4:
            logger.debug("📅 Market closed (weekend)")
            return False

        if market_open <= now.time() <= market_close:
            return True

        logger.debug(f"⏰ Outside market hours ({now.time()})")
        return False

    def check_scheduled_messages(self):
        """
        Check and send scheduled messages based on time windows.
        Ensures messages are sent only once per day.
        """
        tz = pytz.timezone(TIME_ZONE)
        now = datetime.now(tz).time()
        
        # 1. Startup Message + PDH/PDL (09:15 - 09:20)
        if time(9, 15) <= now <= time(9, 20):
            # We use a simple check: if we haven't sent it today (tracked via log/state or just rely on 5m cron)
            # Since cron runs every 5 mins, this window ensures it runs exactly once or twice.
            # To be safe, we can check if we already sent it in this run context, 
            # but for a stateless cloud function, we rely on the narrow window.
            # A better approach for stateless: check if a "startup_sent" flag exists in DB/Cache.
            # For now, we'll assume the 5-min cron hits this window once.
            
            logger.info("⏰ Time window for Startup Message")
            
            pdh_pdl_stats = {}
            for instrument in INSTRUMENTS:
                if INSTRUMENTS[instrument]["active"]:
                    stats = self.fetcher.get_previous_day_stats(instrument)
                    if stats:
                        pdh_pdl_stats[instrument] = stats
            
            self.telegram_bot.send_startup_message(pdh_pdl_stats)

        # 2. Market Context / Opening Range (09:30 - 09:35)
        elif time(9, 30) <= now <= time(9, 35):
            logger.info("⏰ Time window for Market Context Update")
            
            context_data = {}
            pdh_pdl_stats = {}
            sr_levels = {}  # NEW: Support/Resistance levels

            for instrument in INSTRUMENTS:
                if INSTRUMENTS[instrument]["active"]:
                    # Opening range stats
                    stats = self.fetcher.get_opening_range_stats(instrument)
                    if stats:
                        context_data[instrument] = stats
                    
                    # PDH/PDL
                    p_stats = self.fetcher.get_previous_day_stats(instrument)
                    if p_stats:
                        pdh_pdl_stats[instrument] = p_stats
                    
                    # NEW: Calculate S/R levels
                    try:
                        df_5m = self.fetcher.fetch_historical_data(instrument, period="5d", interval="5m")
                        if df_5m is not None and not df_5m.empty:
                            df_5m = self.fetcher.preprocess_ohlcv(df_5m)
                            analyzer = TechnicalAnalyzer(instrument)
                            sr = analyzer.calculate_support_resistance(df_5m)
                            sr_levels[instrument] = sr
                            logger.info(f"✅ S/R calculated for {instrument} | Supports: {len(sr['support'])} | Resistances: {len(sr['resistance'])}")
                    except Exception as e:
                        logger.error(f"❌ S/R calculation failed for {instrument}: {e}")
            
            if context_data or pdh_pdl_stats or sr_levels:
                self.telegram_bot.send_market_context(context_data, pdh_pdl_stats, sr_levels)
            else:
                logger.warning("⚠️ No market context data available to send")
        
        # 3. End-of-Day Summary (15:25 - 15:30)
        elif time(15, 25) <= now <= time(15, 30):
            logger.info("⏰ Time window for End-of-Day Summary")
            
            summary = self.generate_daily_summary()
            if summary:
                self.telegram_bot.send_daily_summary(summary)

    def get_statistics(self) -> Dict:
        """Return simple statistics."""
        return {
            "signals_generated": len(self.signals_generated),
            "alerts_sent": self.alerts_sent,
            "ai_usage": self.ai_analyzer.get_usage_stats(),
            "bot_stats": self.telegram_bot.get_stats(),
        }


def main(dry_run=False):
    """Main entry point for local run or cloud function."""
    logger.info("🚀 Agent starting...")

    agent = NiftyTradingAgent()

    logger.info("\n🔌 Testing external connections...")
    if not agent.ai_analyzer.test_connection():
        logger.error("❌ Groq API connection failed")
        agent.telegram_bot.send_error_notification(
            "Groq API connection failed"
        )
        return

    if not agent.telegram_bot.test_connection():
        logger.error("❌ Telegram connection failed")
        return

    logger.info("✅ All connections successful\n")

    if dry_run or agent.is_market_hours():
        # Check for scheduled messages (Startup, Market Context)
        if not dry_run:
            agent.check_scheduled_messages()
        
        # Run Analysis
        results = agent.run_analysis()
    else:
        logger.info("⏰ Outside market hours - skipping analysis")
        # Note: Removed Telegram message spam - just log and exit silently

    stats = agent.get_statistics()
    logger.info("\n📈 STATISTICS")
    logger.info(f"   Signals: {stats['signals_generated']}")
    logger.info(f"   Alerts Sent: {stats['alerts_sent']}")
    logger.info(
        f"   AI Usage: {stats['ai_usage']['tokens_used']} tokens used"
    )


# Initialize Flask app
app = Flask(__name__)

@app.route("/", methods=["POST", "GET"])
def cloud_function_handler(request_context=None):
    """Entry point for Google Cloud Functions & Cloud Run."""
    # Handle Cloud Run (Flask) request object
    if request_context is None:
        request_context = request
        
    # Early exit for outside market hours (avoid full initialization)
    if not _is_market_hours_quick():
        return {"status": "skipped", "message": "Outside market hours"}, 200
    
    logger.info("☁️  Cloud Function triggered")
    main()
    return {"status": "success", "message": "Analysis completed"}, 200


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nifty AI Trading Agent")
    parser.add_argument(
        "--once", action="store_true", help="Run analysis once"
    )
    parser.add_argument(
        "--test", action="store_true", help="Test connections only"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Force run analysis (bypass time check) and simulate alerts"
    )

    args = parser.parse_args()

    if args.test:
        agent = NiftyTradingAgent()
        logger.info("Testing connections...")
        agent.ai_analyzer.test_connection()
        agent.telegram_bot.test_connection()
    else:
        # Pass args to main if needed, or set global dry_run
        if args.dry_run:
            logger.info("🔧 DRY RUN MODE DETECTED: Bypassing market hours check")
            main(dry_run=args.dry_run)
        else:
            # Running as a server (Cloud Run default behavior if no args)
            port = int(os.environ.get("PORT", 8080))
            app.run(host="0.0.0.0", port=port)
