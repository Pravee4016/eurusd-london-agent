"""
Telegram Bot Handler
Sends formatted alerts, signals, and notifications to Telegram.
"""

import requests
import json
import logging
from typing import Dict, Optional
from datetime import datetime

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_MAX_MESSAGE_LENGTH,
    INCLUDE_CHARTS_IN_ALERT,
    INCLUDE_AI_SUMMARY_IN_ALERT,
    ALERT_TYPES,
    DRY_RUN,
    DEBUG_MODE,
)

logger = logging.getLogger(__name__)


class TelegramBot:
    """Send alerts and messages to Telegram."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.message_count = 0

        logger.info(f"🤖 TelegramBot initialized | Chat ID: {self.chat_id}")
        self._validate_credentials()

    def _validate_credentials(self):
        if not self.token or self.token == "YOUR_BOT_TOKEN_HERE":
            logger.error("❌ TELEGRAM_BOT_TOKEN not configured")
        if not self.chat_id or self.chat_id == "YOUR_CHAT_ID_HERE":
            logger.error("❌ TELEGRAM_CHAT_ID not configured")

    # =====================================================================
    # CORE SEND
    # =====================================================================

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a plain message to Telegram chat.
        """
        if DRY_RUN:
            logger.warning(f"🚫 DRY RUN: Not sending Telegram message: {text[:80]}...")
            return True

        if len(text) > TELEGRAM_MAX_MESSAGE_LENGTH:
            logger.warning(
                f"⚠️  Message too long ({len(text)} chars), truncating"
            )
            text = text[: TELEGRAM_MAX_MESSAGE_LENGTH - 3] + "..."

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

            logger.debug(
                f"📤 Sending Telegram message | Length: {len(text)} chars"
            )
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()
            if data.get("ok"):
                msg_id = data["result"]["message_id"]
                self.message_count += 1
                logger.info(f"✅ Telegram message sent | ID: {msg_id}")
                if DEBUG_MODE:
                    logger.debug(f"   Preview: {text[:150]}...")
                return True

            logger.error(
                f"❌ Telegram API error: {data.get('description', 'Unknown')}"
            )
            return False

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Telegram send failed: {str(e)}")
            return False

    # =====================================================================
    # SIGNAL ALERTS
    # =====================================================================

    def send_breakout_alert(self, signal: Dict) -> bool:
        """Send formatted breakout/breakdown alert."""
        try:
            instrument = signal.get("instrument", "N/A")
            signal_type = signal.get("signal_type", "BREAKOUT")
            entry = float(signal.get("entry_price", 0.0))
            sl = float(signal.get("stop_loss", 0.0))
            tp = float(signal.get("take_profit", 0.0))
            rr = float(signal.get("risk_reward_ratio", 0.0))
            conf = float(signal.get("confidence", 0.0))

            emoji = "🚀" if "BULLISH" in signal_type else "📉"

            header = ALERT_TYPES.get(
                "BREAKOUT", "BREAKOUT"
            ) if "BREAKOUT" in signal_type else ALERT_TYPES.get(
                "BREAKDOWN", "BREAKDOWN"
            )

            message = (
                f"{emoji} {header}\n\n"
                f"📊 {instrument}\n"
                f"💰 Entry: {entry:.2f}\n"
                f"🛑 SL: {sl:.2f}\n"
                f"🎯 TP: {tp:.2f}\n"
                f"📈 RR: {rr:.2f}:1\n"
                f"⚡ Confidence: {conf:.1f}%\n\n"
                f"{signal.get('description', '')}\n\n"
            )
            
            # Add IST timestamp
            import pytz
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)
            message += f"⏰ {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}"

            if signal.get("ai_analysis") and INCLUDE_AI_SUMMARY_IN_ALERT:
                ai_data = signal["ai_analysis"]
                summary = ai_data.get("summary", "")
                reco = ai_data.get("recommendation", "HOLD")
                ai_conf = ai_data.get("confidence", 0)
                message += (
                    f"\n\n🤖 AI: {reco} ({ai_conf:.0f}%)\n"
                    f"{summary[:300]}"
                )

            return self.send_message(message)

        except Exception as e:
            logger.error(f"❌ Failed to format breakout alert: {str(e)}")
            return False

    def send_false_breakout_alert(self, signal: Dict) -> bool:
        """Send false breakout warning."""
        try:
            instrument = signal.get("instrument", "N/A")
            level = float(signal.get("price_level", 0.0))
            fb = signal.get("false_breakout_details", {})
            retrace = float(fb.get("retracement_pct", 0.0))

            message = (
                f"⚠️ {ALERT_TYPES.get('FALSE_BREAKOUT', 'FALSE BREAKOUT')}\n\n"
                f"📊 {instrument}\n"
                f"📍 Level: {level:.2f}\n"
                f"↩ Retracement: {retrace:.2f}%\n\n"
                f"Possible trap / failed breakout at key level.\n\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            return self.send_message(message)

        except Exception as e:
            logger.error(
                f"❌ Failed to format false breakout alert: {str(e)}"
            )
            return False

    def send_retest_alert(self, signal: Dict) -> bool:
        """Send retest setup alert."""
        try:
            import pytz
            
            instrument = signal.get("instrument", "N/A")
            signal_type = signal.get("signal_type", "RETEST")
            level = float(signal.get("price_level", 0.0))
            entry = float(signal.get("entry_price", 0.0))
            sl = float(signal.get("stop_loss", 0.0))
            tp = float(signal.get("take_profit", 0.0))
            conf = float(signal.get("confidence", 0.0))
            desc = signal.get("description", "")
            
            # Determine direction
            direction = "📈 LONG" if entry > sl else "📉 SHORT"
            emoji = "🎯" if "SUPPORT" in signal_type.upper() else "🔄"
            
            # Calculate R:R
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = reward / risk if risk > 0 else 0
            
            # Get IST time
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)

            message = (
                f"{emoji} {ALERT_TYPES.get('RETEST', 'RETEST')} {direction}\n\n"
                f"📊 <b>{instrument}</b>\n"
                f"📍 Key Level: {level:.2f}\n\n"
                f"<b>💰 Entry:</b> {entry:.2f}\n"
                f"<b>🛑 Stop Loss:</b> {sl:.2f}\n"
                f"<b>🎯 Target:</b> {tp:.2f}\n"
                f"<b>📈 Risk:Reward:</b> 1:{rr:.1f}\n"
                f"<b>⚡ Confidence:</b> {conf:.0f}%\n\n"
                f"💡 {desc}\n\n"
                f"⏰ {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}"
            )

            return self.send_message(message)

        except Exception as e:
            logger.error(f"❌ Failed to format retest alert: {str(e)}")
            return False

    def send_inside_bar_alert(self, signal: Dict) -> bool:
        """Send inside bar setup alert."""
        try:
            import pytz
            
            instrument = signal.get("instrument", "N/A")
            entry = float(signal.get("entry_price", 0.0))
            sl = float(signal.get("stop_loss", 0.0))
            tp = float(signal.get("take_profit", 0.0))
            conf = float(signal.get("confidence", 0.0))
            desc = signal.get("description", "")
            
            # Calculate R:R
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            rr = reward / risk if risk > 0 else 0
            
            # Get IST time
            ist = pytz.timezone("Asia/Kolkata")
            now_ist = datetime.now(ist)

            message = (
                f"📊 {ALERT_TYPES.get('INSIDE_BAR', 'INSIDE BAR SETUP')}\n\n"
                f"📊 <b>{instrument}</b>\n\n"
                f"<b>💰 Entry:</b> {entry:.2f}\n"
                f"<b>🛑 Stop Loss:</b> {sl:.2f}\n"
                f"<b>🎯 Target:</b> {tp:.2f}\n"
                f"<b>📈 Risk:Reward:</b> 1:{rr:.1f}\n"
                f"<b>⚡ Confidence:</b> {conf:.0f}%\n\n"
                f"💡 {desc}\n\n"
                f"⏰ {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}"
            )

            return self.send_message(message)

        except Exception as e:
            logger.error(
                f"❌ Failed to format inside bar alert: {str(e)}"
            )
            return False

    # =====================================================================
    # OTHER NOTIFICATIONS
    # =====================================================================

    def send_daily_summary(self, summary_data: Dict) -> bool:
        """Send comprehensive end-of-day market summary."""
        try:
            message = "<b>📊 END-OF-DAY MARKET SUMMARY</b>\n"
            message += f"📅 {datetime.now().strftime('%B %d, %Y')}\n\n"
            
            # Price action for each instrument
            instruments_data = summary_data.get("instruments", {})
            for instrument, data in instruments_data.items():
                change_pct = data.get("change_pct", 0)
                emoji = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➖"
                
                message += f"<b>{emoji} {instrument}</b>\n"
                message += f"Open: {data.get('open', 0):.2f} | High: {data.get('high', 0):.2f}\n"
                message += f"Low: {data.get('low', 0):.2f} | <b>Close: {data.get('close', 0):.2f}</b>\n"
                message += f"Change: <b>{change_pct:+.2f}%</b>\n"
                
                # Key levels
                if data.get("pdh") and data.get("pdl"):
                    message += f"PDH: {data['pdh']:.2f} | PDL: {data['pdl']:.2f}\n"
                
                # Trend
                st_trend = data.get("short_term_trend", "NEUTRAL")
                lt_trend = data.get("long_term_trend", "NEUTRAL")
                message += f"Trend: {st_trend} (ST) / {lt_trend} (LT)\n\n"
            
            # Events summary
            stats = summary_data.get("statistics", {})
            message += "<b>🎯 Today's Events</b>\n"
            message += f"🚀 Breakouts: {stats.get('breakouts', 0)}\n"
            message += f"📉 Breakdowns: {stats.get('breakdowns', 0)}\n"
            message += f"🔄 Retests: {stats.get('retests', 0)}\n"
            message += f"↩️ Reversals: {stats.get('reversals', 0)}\n\n"
            
            # Performance stats
            perf = summary_data.get("performance", {})
            if perf and perf.get("total_alerts", 0) > 0:
                message += "<b>📊 Performance (Last 24h)</b>\n"
                message += f"Total Alerts: {perf.get('total_alerts', 0)}\n"
                
                # Only show win rate if we have closed trades
                wins = perf.get("wins", 0)
                losses = perf.get("losses", 0)
                if wins + losses > 0:
                    message += f"Win Rate: {perf.get('win_rate', 0):.1f}% ({wins}W-{losses}L)\n"
                
                by_type = perf.get("by_type", {})
                if by_type:
                    message += "<i>By Setup:</i>\n"
                    for stype, data in by_type.items():
                        readable_type = stype.replace("_", " ").title()
                        count = data.get("count", 0)
                        message += f"- {readable_type}: {count}\n"
                message += "\n"
            
            # AI Forecast
            forecast = summary_data.get("ai_forecast", {})
            if forecast:
                outlook = forecast.get("outlook", "NEUTRAL")
                outlook_emoji = "🟢" if outlook == "BULLISH" else "🔴" if outlook == "BEARISH" else "🟡"
                
                message += f"<b>{outlook_emoji} AI Forecast - {outlook}</b>\n"
                message += f"Confidence: {forecast.get('confidence', 50):.0f}%\n"
                
                # Parse summary if it's a JSON string (common with LLM output)
                ai_summary = forecast.get("summary", "No forecast available")
                if isinstance(ai_summary, str) and ai_summary.strip().startswith("{"):
                    try:
                        import json
                        parsed = json.loads(ai_summary)
                        ai_summary = parsed.get("summary", ai_summary)
                    except:
                        pass
                        
                message += f"{ai_summary}\n\n"
            
            # Statistics
            message += "<b>📊 Session Stats</b>\n"
            message += f"📡 Data Fetches: {stats.get('data_fetches', 0)}\n"
            message += f"🔍 Analyses: {stats.get('analyses_run', 0)}\n"
            message += f"🔔 Alerts Sent: {stats.get('alerts_sent', 0)}\n"
            
            return self.send_message(message)

        except Exception as e:
            logger.error(
                f"❌ Failed to send daily summary: {str(e)}"
            )
            return False

    def send_error_notification(
        self, error_msg: str, context: str = ""
    ) -> bool:
        """Send error notification."""
        try:
            message = (
                "❌ ERROR NOTIFICATION\n\n"
                f"{context}\n\n"
                f"Error: {error_msg[:500]}\n\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            return self.send_message(message)

        except Exception as e:
            logger.error(
                f"❌ Failed to send error notification: {str(e)}"
            )
            return False

    def send_startup_message(self, pdh_pdl_stats: Optional[Dict] = None) -> bool:
        """Send startup confirmation message with optional PDH/PDL stats."""
        try:
            message = (
                "🚀 EUR/USD LONDON SESSION TRADING AGENT STARTED\n\n"
                "✅ System online and monitoring markets\n"
                "📊 Instruments: EUR/USD\n"
                "🔔 Breakout / retest / inside bar alerts will be sent\n"
                "⏰ Active: 08:00 - 16:00 GMT (London Session)\n"
            )

            if pdh_pdl_stats:
                message += "\n📋 <b>Previous Day Stats</b>\n"
                for instrument, stats in pdh_pdl_stats.items():
                    message += (
                        f"\n<b>{instrument}</b>\n"
                        f"High: {stats['pdh']:.2f}\n"
                        f"Low: {stats['pdl']:.2f}\n"
                        f"Close: {stats['pdc']:.2f}\n"
                    )

            return self.send_message(message)

        except Exception as e:
            logger.error(
                f"❌ Failed to send startup message: {str(e)}"
            )
            return False

    def send_market_context(self, context_data: Dict, pdh_pdl_stats: Optional[Dict] = None, sr_levels: Optional[Dict] = None) -> bool:
        """Send market context (Opening Range + S/R) update with optional PDH/PDL."""
        try:
            message = "🌅 <b>MARKET CONTEXT UPDATE</b>\n\n"
            
            all_instruments = set(context_data.keys())
            if pdh_pdl_stats:
                all_instruments.update(pdh_pdl_stats.keys())
            if sr_levels:
                all_instruments.update(sr_levels.keys())
            
            for instrument in sorted(list(all_instruments)):
                message += f"<b>{instrument}</b>\n"
                
                # PDH/PDL
                if pdh_pdl_stats and instrument in pdh_pdl_stats:
                    stats = pdh_pdl_stats[instrument]
                    message += (
                        f"PDH: {stats['pdh']:.2f} | PDL: {stats['pdl']:.2f}\n"
                    )

                # Opening Range
                if instrument in context_data:
                    stats = context_data[instrument]
                    if "orb_5m_high" in stats:
                        message += (
                            f"5m OR: {stats['orb_5m_low']:.2f} - {stats['orb_5m_high']:.2f}\n"
                        )
                    if "orb_15m_high" in stats:
                        message += (
                            f"15m OR: {stats['orb_15m_low']:.2f} - {stats['orb_15m_high']:.2f}\n"
                        )
                
                # NEW: Support/Resistance Levels
                if sr_levels and instrument in sr_levels:
                    sr = sr_levels[instrument]
                    # Show top 3 supports and resistances
                    supports = sorted(sr.get('support', []))[-3:] if sr.get('support') else []
                    resistances = sorted(sr.get('resistance', []))[:3] if sr.get('resistance') else []
                    
                    if supports:
                        message += f"📊 Supports: {', '.join([f'{s:.2f}' for s in supports])}\n"
                    if resistances:
                        message += f"📊 Resistances: {', '.join([f'{r:.2f}' for r in resistances])}\n"
                
                message += "\n"

            message += f"⏰ {datetime.now().strftime('%H:%M:%S')}"
            return self.send_message(message)

        except Exception as e:
            logger.error(f"❌ Failed to send market context: {str(e)}")
            return False

    # =====================================================================
    # MEDIA (optional stub)
    # =====================================================================

    def send_chart(self, chart_path: str, caption: str = "") -> bool:
        """Send chart image to Telegram (optional, can be extended)."""
        if not INCLUDE_CHARTS_IN_ALERT:
            logger.debug("⏭️  Chart sending disabled in settings")
            return True

        if DRY_RUN:
            logger.warning(
                f"🚫 DRY RUN: Not sending chart: {chart_path}"
            )
            return True

        try:
            url = f"{self.base_url}/sendPhoto"
            with open(chart_path, "rb") as photo:
                files = {"photo": photo}
                data = {
                    "chat_id": self.chat_id,
                    "caption": caption[:1024],
                }

                logger.debug(f"📤 Sending chart: {chart_path}")
                response = requests.post(
                    url, files=files, data=data, timeout=30
                )
                response.raise_for_status()

                if response.json().get("ok"):
                    logger.info("✅ Chart sent to Telegram")
                    return True

                logger.error("❌ Failed to send chart")
                return False

        except Exception as e:
            logger.error(f"❌ Chart sending failed: {str(e)}")
            return False

    # =====================================================================
    # CONNECTION TEST & STATS
    # =====================================================================

    def test_connection(self) -> bool:
        """Test Telegram bot connection."""
        try:
            logger.info("🧪 Testing Telegram connection...")
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("ok"):
                bot_name = data["result"].get("first_name", "Bot")
                logger.info(
                    f"✅ Telegram connection successful | Bot: {bot_name}"
                )
                return True
            logger.error("❌ Telegram getMe returned not ok")
            return False
        except Exception as e:
            logger.error(f"❌ Telegram connection test failed: {str(e)}")
            return False

    def get_stats(self) -> Dict:
        """Get simple bot statistics."""
        return {
            "messages_sent": self.message_count,
            "chat_id": self.chat_id,
        }


_bot: Optional[TelegramBot] = None


def get_bot() -> TelegramBot:
    """Singleton getter for TelegramBot."""
    global _bot
    if _bot is None:
        _bot = TelegramBot()
    return _bot


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    bot = get_bot()
    bot.test_connection()
    bot.send_startup_message()
