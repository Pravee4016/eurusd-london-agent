"""
AI Analysis Module using Groq API
Generates intelligent trade signal analysis and summaries.
"""

import requests
import json
import logging
import time
from typing import Dict, Optional
from datetime import datetime
import hashlib

from config.settings import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_MAX_TOKENS,
    GROQ_TEMPERATURE,
    GROQ_REQUESTS_PER_DAY,
    DEBUG_MODE,
    DRY_RUN,
)

logger = logging.getLogger(__name__)


class GroqAnalyzer:
    """Interface with Groq API for AI-powered analysis."""

    def __init__(self):
        self.api_key = GROQ_API_KEY
        self.model = GROQ_MODEL
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.request_count = 0
        self.tokens_used = 0
        self.cache: Dict[str, Dict] = {}

        logger.info(f"🤖 GroqAnalyzer initialized | Model: {self.model}")
        self._validate_api_key()

    def _validate_api_key(self):
        if not self.api_key or self.api_key == "YOUR_GROQ_KEY_HERE":
            logger.error("❌ GROQ_API_KEY not configured!")
            raise ValueError("GROQ_API_KEY required")

    # =====================================================================
    # SIGNAL ANALYSIS
    # =====================================================================

    def analyze_signal(self, signal_data:Dict) -> Dict:
        """
        Analyze a trading signal using AI.

        signal_data should contain:
            instrument, signal_type, price_level, entry, sl, tp, technical_data.
        """
        try:
            cache_key = self._generate_cache_key(signal_data)
            if cache_key in self.cache:
                logger.debug("💾 GroqAnalyzer cache HIT")
                return self.cache[cache_key]

            prompt = self._build_analysis_prompt(signal_data)

            logger.debug(
                f"📤 Sending analysis request to Groq | "
                f"{signal_data.get('instrument')} | {signal_data.get('signal_type')}"
            )

            response_text = self._call_groq_api(prompt)
            if not response_text:
                return self._fallback_analysis(signal_data)

            analysis = self._parse_analysis_response(
                response_text, signal_data
            )

            self.cache[cache_key] = analysis
            logger.info(
                "✅ Signal analyzed | "
                f"Conf: {analysis['confidence']}% | "
                f"Reco: {analysis['recommendation']}"
            )
            return analysis

        except Exception as e:
            logger.error(f"❌ Signal analysis failed: {str(e)}")
            return self._fallback_analysis(signal_data)

    def generate_market_summary(self, market_data: Dict) -> str:
        """
        Generate AI market summary (2-3 sentences).
        """
        try:
            prompt = (
                "Provide a concise 2-3 sentence market summary for "
                "the following \n\n"
                f"{json.dumps(market_data, indent=2)}"
            )

            logger.debug("📊 Generating market summary via Groq")
            response_text = self._call_groq_api(prompt)
            if not response_text:
                return "Market analysis unavailable."

            summary = response_text.strip()[:600]
            logger.info(
                f"✅ Market summary generated | Length: {len(summary)} chars"
            )
            return summary

        except Exception as e:
            logger.error(f"❌ Summary generation failed: {str(e)}")
            return "Market analysis temporarily unavailable."

    def forecast_market_outlook(self, market_context: str) -> Dict:
        """
        Generate AI forecast for next trading day based on today's market action.
        """
        try:
            prompt = (
                "Based on today's market action, provide a forecast for the next trading day.\\n\\n"
                f"Today's Summary: {market_context}\\n\\n"
                "Respond in JSON format:\\n"
                "{\\n"
                '  \\"outlook\\": \\"BULLISH/BEARISH/NEUTRAL\\",\\n'
                '  \\"confidence\\": 0-100,\\n'
                ' \\"summary\\": \\"2-3 sentence forecast\\",\\n'
                '  \\"key_levels\\": [\\"level1\\", \\"level2\\"]\\n'
                "}"
            )
            
            logger.debug("🔮 Generating market forecast via Groq")
            response_text = self._call_groq_api(prompt)
            
            if not response_text:
                return {
                    "outlook": "NEUTRAL",
                    "confidence": 50,
                    "summary": "Forecast unavailable",
                    "key_levels": []
                }
            
            # Try to parse JSON
            response_text = response_text.strip()
            if response_text.startswith("{"):
                forecast = json.loads(response_text)
            else:
                # Fallback parsing
                lower = response_text.lower()
                outlook = "NEUTRAL"
                if "bullish" in lower:
                    outlook = "BULLISH"
                elif "bearish" in lower:
                    outlook = "BEARISH"
                
                forecast = {
                    "outlook": outlook,
                    "confidence": 65,
                    "summary": response_text[:400],
                    "key_levels": []
                }
            
            logger.info(f"✅ Forecast generated | Outlook: {forecast.get('outlook', 'NEUTRAL')}")
            return forecast
            
        except Exception as e:
            logger.error(f"❌ Forecast generation failed: {str(e)}")
            return {
                "outlook": "NEUTRAL",
                "confidence": 50,
                "summary": "Forecast temporarily unavailable.",
                "key_levels": []
            }

    # =====================================================================
    # GROQ API CALL
    # =====================================================================

    def _call_groq_api(
        self, prompt: str, retries: int = 3
    ) -> Optional[str]:
        """
        Call Groq API with retry logic and simple rate tracking.
        """
        if DRY_RUN:
            logger.warning("🚫 DRY RUN: Groq API not called")
            return "Dry run response."

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert intraday trader. "
                        "Respond in concise JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": GROQ_TEMPERATURE,
            "max_tokens": GROQ_MAX_TOKENS,
            "top_p": 1,
        }

        for attempt in range(retries):
            try:
                start = time.time()
                response = requests.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                elapsed = time.time() - start

                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)
                    self.tokens_used += total_tokens
                    self.request_count += 1

                    logger.debug(
                        f"   Groq API OK | Time: {elapsed:.2f}s | "
                        f"Tokens: {total_tokens}"
                    )
                    content = data["choices"][0]["message"]["content"]
                    return content

                if response.status_code == 429:
                    logger.warning(
                        f"⚠️  Groq rate limited, attempt {attempt + 1}"
                    )
                    time.sleep(2 ** attempt)
                    continue

                logger.warning(
                    f"⚠️  Groq API error {response.status_code}: "
                    f"{response.text[:200]}"
                )
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)

            except requests.exceptions.Timeout:
                logger.warning(
                    f"⚠️  Groq timeout, attempt {attempt + 1}/{retries}"
                )
                if attempt < retries - 1:
                    time.sleep(2)

            except Exception as e:
                logger.error(f"❌ Groq request failed: {str(e)}")
                if attempt < retries - 1:
                    time.sleep(2)

        logger.error("❌ Groq API call failed after retries")
        return None

    # =====================================================================
    # PROMPT & RESPONSE HANDLING
    # =====================================================================

    def _build_analysis_prompt(self, signal_data: Dict) -> str:
        """Build compact JSON-focused prompt."""
        return (
            "Analyze this intraday trading signal and respond with a JSON:\n\n"
            f"{json.dumps(signal_data, indent=2)}\n\n"
            "Response JSON format:\n"
            "{\n"
            '  \"recommendation\": \"BUY/SELL/HOLD\",\n'
            '  \"confidence\": 0-100,\n'
            '  \"summary\": \"short explanation\",\n'
            '  \"risks\": [\"risk1\", \"risk2\"]\n'
            "}\n"
        )

    def _parse_analysis_response(
        self, response_text: str, signal_data: Dict
    ) -> Dict:
        """Parse Groq text into structured dict."""
        try:
            # Try to parse JSON directly
            response_text = response_text.strip()
            if response_text.startswith("{"):
                data = json.loads(response_text)
            else:
                # Fallback: basic text parsing
                lower = response_text.lower()
                reco = "HOLD"
                if "buy" in lower:
                    reco = "BUY"
                elif "sell" in lower:
                    reco = "SELL"

                data = {
                    "recommendation": reco,
                    "confidence": 65,
                    "summary": response_text[:400],
                    "risks": [],
                }

            return {
                "signal_type": signal_data.get("signal_type"),
                "recommendation": data.get("recommendation", "HOLD"),
                "confidence": float(data.get("confidence", 65)),
                "summary": data.get("summary", "")[:600],
                "risks": data.get("risks", []),
                "entry_point": signal_data.get("entry"),
                "stop_loss": signal_data.get("sl"),
                "take_profit": signal_data.get("tp"),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.warning(
                f"⚠️  Could not parse Groq response as JSON: {str(e)}"
            )
            return self._fallback_analysis(signal_data)

    def _generate_cache_key(self, signal_data: Dict) -> str:
        """Generate hash for signal_data to cache AI result."""
        key_str = json.dumps(signal_data, sort_keys=True, default=str)
        return hashlib.md5(key_str.encode("utf-8")).hexdigest()

    def _fallback_analysis(self, signal_data: Dict) -> Dict:
        """Fallback if Groq is unavailable."""
        return {
            "signal_type": signal_data.get("signal_type"),
            "recommendation": "HOLD",
            "confidence": 50.0,
            "summary": "AI analysis unavailable, use technicals only.",
            "risks": ["AI service unavailable"],
            "entry_point": signal_data.get("entry"),
            "stop_loss": signal_data.get("sl"),
            "take_profit": signal_data.get("tp"),
            "timestamp": datetime.now().isoformat(),
        }

    # =====================================================================
    # USAGE STATS & TEST
    # =====================================================================

    def get_usage_stats(self) -> Dict:
        """Return simple usage stats."""
        return {
            "requests_made": self.request_count,
            "tokens_used": self.tokens_used,
            "tokens_remaining": GROQ_REQUESTS_PER_DAY - self.tokens_used,
        }

    def print_usage_stats(self):
        stats = self.get_usage_stats()
        logger.info(
            "📊 Groq Usage | "
            f"Requests: {stats['requests_made']} | "
            f"Tokens: {stats['tokens_used']} / {GROQ_REQUESTS_PER_DAY}"
        )

    def clear_cache(self):
        self.cache.clear()
        logger.info("🗑️  GroqAnalyzer cache cleared")

    def test_connection(self) -> bool:
        """Simple connection test to Groq."""
        try:
            logger.info("🧪 Testing Groq API connection...")
            resp = self._call_groq_api('Say "OK" if you are working.')
            if resp and "OK" in resp:
                logger.info("✅ Groq API connection successful")
                return True
            logger.warning(f"⚠️  Groq test unexpected response: {resp}")
            return False
        except Exception as e:
            logger.error(f"❌ Groq connection test failed: {str(e)}")
            return False


_analyzer: Optional[GroqAnalyzer] = None


def get_analyzer() -> GroqAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = GroqAnalyzer()
    return _analyzer


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG if DEBUG_MODE else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    analyzer = get_analyzer()
    analyzer.test_connection()
    analyzer.print_usage_stats()
