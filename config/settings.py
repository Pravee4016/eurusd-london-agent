"""
Configuration & Settings Module for EUR/USD London Session Trading
All API keys, thresholds, and constants specific to forex trading
"""

import os
from dotenv import load_dotenv
from enum import Enum

# Load environment variables
load_dotenv()

# ============================================================================
# API KEYS & CREDENTIALS
# ============================================================================

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "YOUR_FINNHUB_KEY_HERE")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "YOUR_GROQ_KEY_HERE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")

# ============================================================================
# MARKET PARAMETERS - EUR/USD FOREX
# ============================================================================


class Instrument(Enum):
    """Trading instruments"""

    EURUSD = "EUR/USD"


INSTRUMENTS = {
    "EURUSD": {
        "symbol": "OANDA:EUR_USD",  # Finnhub forex symbol format
        "display_name": "EUR/USD",
        "tick_size": 0.0001,  # 1 pip
        "pip_value": 0.0001,
        "typical_spread": 0.0001,  # 1 pip spread
        "active": True,
    },
}

# Trading hours (London Session - GMT)
MARKET_OPEN_TIME = "08:00"  # London session open
ANALYSIS_START_TIME = os.getenv("ANALYSIS_START_TIME", "07:55")  # Pre-session analysis
MARKET_CLOSE_TIME = "16:00"  # London session close

# Asian Session (Monitoring only, for levels)
ASIAN_SESSION_START = "00:00"
ASIAN_SESSION_END = "08:00"

# Timeframes for analysis
TIMEFRAMES = {
    "5MIN": "5",  # Finnhub uses numeric resolution
    "15MIN": "15",
    "1HOUR": "60",
    "1DAY": "D",
}

PRIMARY_TIMEFRAME = "5MIN"  # Main execution timeframe
CONFIRMATION_TIMEFRAME = "15MIN"  # Trend confirmation

# ============================================================================
# TECHNICAL ANALYSIS THRESHOLDS - FOREX SPECIFIC
# ============================================================================

# Volume Configuration (for forex, volume is aggregate tick volume)
MIN_VOLUME_RATIO = float(os.getenv("MIN_VOLUME_RATIO", 1.2))  # Lower for forex
VOLUME_PERIOD = 20  # candles lookback

# Breakout Configuration (pip-based instead of percentage)
BREAKOUT_CONFIRMATION_CANDLES = 2
BREAKOUT_CONFIRMATION_PIPS = 5  # Must break level by 5 pips
RETEST_ZONE_PIPS = 10  # Retest within 10 pips of level

# Support/Resistance Configuration (forex respects round numbers)
SR_CLUSTER_TOLERANCE_PIPS = 5  # Cluster levels within 5 pips
MIN_SR_TOUCHES = 2
LOOKBACK_BARS = 100

# Round number levels (psychological levels in forex)
ROUND_NUMBER_LEVELS = [0, 20, 50, 80, 100]  # Pips ending in these values

# Momentum Configuration
MIN_RSI_BULLISH = int(os.getenv("MIN_MOMENTUM_RSI", 60))
MAX_RSI_BEARISH = int(os.getenv("MAX_MOMENTUM_RSI", 40))
RSI_PERIOD = 14

# ATR (for dynamic SL/TP in pips)
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 2.5

# Typical EUR/USD ATR ranges (in pips)
MIN_ATR_PIPS = 20  # Minimum volatility for trading
TYPICAL_ATR_LONDON = 50  # Average London session ATR

# Moving Averages
EMA_SHORT = 9
EMA_LONG = 21
SMA_VOLUME = 20

# MACD Configuration
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Bollinger Bands
BB_PERIOD = 20
BB_STD_DEV = 2

# Stochastic Configuration
STOCH_PERIOD = 14
STOCH_SMOOTH_K = 3
STOCH_SMOOTH_D = 3

# ============================================================================
# RISK MANAGEMENT - FOREX SPECIFIC
# ============================================================================

MIN_RISK_REWARD_RATIO = 1.5
MAX_DAILY_TRADES = 5
MIN_SIGNAL_CONFIDENCE = int(os.getenv("MIN_SIGNAL_CONFIDENCE", 65))

# Position sizing (lot-based for forex)
DEFAULT_POSITION_SIZE = 0.01  # 0.01 lots = 1,000 units (micro lot)
MAX_POSITION_SIZE = 0.1  # 0.1 lots = 10,000 units

# Stop Loss / Take Profit defaults (in pips)
DEFAULT_SL_PIPS = 15
DEFAULT_TP_PIPS = 30

# ============================================================================
# AI & GROQ CONFIGURATION
# ============================================================================

GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", 400))
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", 0.3))
GROQ_REQUESTS_PER_DAY = int(os.getenv("GROQ_REQUESTS_PER_DAY", 1000))

# ============================================================================
# TELEGRAM CONFIGURATION
# ============================================================================

TELEGRAM_MAX_MESSAGE_LENGTH = 4000
INCLUDE_CHARTS_IN_ALERT = (
    os.getenv("INCLUDE_CHARTS_IN_ALERT", "true").lower() == "true"
)
INCLUDE_AI_SUMMARY_IN_ALERT = (
    os.getenv("INCLUDE_AI_SUMMARY_IN_ALERT", "true").lower() == "true"
)

ALERT_TYPES = {
    "BREAKOUT": "🚀 BREAKOUT",
    "BREAKOUT_CONFIRMED": "✅ BREAKOUT CONFIRMED",
    "FALSE_BREAKOUT": "⚠️ FALSE BREAKOUT",
    "RETEST": "🎯 RETEST SETUP",
    "INSIDE_BAR": "📊 INSIDE BAR SETUP",
    "BREAKDOWN": "📉 BREAKDOWN",
    "SUPPORT_HIT": "🛡️ SUPPORT HIT",
    "RESISTANCE_HIT": "🔴 RESISTANCE HIT",
}

# ============================================================================
# SCHEDULING CONFIGURATION - LONDON SESSION
# ============================================================================

TIME_ZONE = os.getenv("TIME_ZONE", "Europe/London")
SCHEDULE_CRON = "0 8 * * MON-FRI"  # London session start
INTRADAY_MONITORING_INTERVAL = 5  # minutes

# ============================================================================
# DATA STORAGE & CACHING
# ============================================================================

CACHE_DIR = "./cache"
CACHE_DATA_TTL = 3600  # seconds

LOG_DIR = "./logs"
LOG_LEVEL = os.getenv("LOGLEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ============================================================================
# CLOUD DEPLOYMENT - NEW GCP PROJECT
# ============================================================================

GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
CLOUD_FUNCTION_REGION = os.getenv("CLOUD_FUNCTION_REGION", "us-central1")
FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "")

# Firestore collections (separate from NIFTY agent)
FIRESTORE_COLLECTION_DAILY_STATS = "eurusd_daily_stats"
FIRESTORE_COLLECTION_TRADES = "eurusd_trades"

DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "LOCAL")  # LOCAL, GCP
ENABLE_CLOUD_LOGGING = DEPLOYMENT_MODE != "LOCAL"

# ============================================================================
# DEBUG & DEVELOPMENT
# ============================================================================

DEBUG_MODE = os.getenv("DEBUG_MODE", "False") == "True"

# ============================================================================
# RISK MANAGEMENT - ALERT LIMITS
# ============================================================================

# Daily Alert Limits
MAX_ALERTS_PER_DAY = int(os.getenv("MAX_ALERTS_PER_DAY", "999"))  # Rely on other filters
MAX_ALERTS_PER_TYPE = int(os.getenv("MAX_ALERTS_PER_TYPE", "10"))  # Max per signal type
MAX_ALERTS_PER_INSTRUMENT = int(os.getenv("MAX_ALERTS_PER_INSTRUMENT", "15"))  # Max per instrument

# Choppy Market Detection (in pips for forex)
MIN_ATR_PERCENT = float(os.getenv("MIN_ATR_PERCENT", "0.2"))  # 0.2% = ~22 pips at 1.10
MAX_VWAP_CROSSES = int(os.getenv("MAX_VWAP_CROSSES", "4"))  # Max crosses in 10 bars = choppy

# Velocity Breaker (Flash Crash Protection)
# 0.2% per minute is extreme for EUR/USD (approx 20 pips/min)
MAX_1MIN_MOVE_PCT = float(os.getenv("MAX_1MIN_MOVE_PCT", "0.2"))

# Correlation Limits
MAX_SAME_DIRECTION_ALERTS = int(os.getenv("MAX_SAME_DIRECTION_ALERTS", "3"))  # Max similar directional trades in 15 mins

SEND_TEST_ALERTS = os.getenv("SEND_TEST_ALERTS", "False").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "False").lower() == "true"
VERBOSE = os.getenv("VERBOSE", "False").lower() == "true"


def validate_config():
    """Validate critical configuration"""
    errors = []

    if not FINNHUB_API_KEY or FINNHUB_API_KEY == "YOUR_FINNHUB_KEY_HERE":
        errors.append("❌ FINNHUB_API_KEY not set in .env")

    if not GROQ_API_KEY or GROQ_API_KEY == "YOUR_GROQ_KEY_HERE":
        errors.append("❌ GROQ_API_KEY not set in .env")

    if (
        not TELEGRAM_BOT_TOKEN
        or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE"
    ):
        errors.append("❌ TELEGRAM_BOT_TOKEN not set in .env")

    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        errors.append("❌ TELEGRAM_CHAT_ID not set in .env")

    return errors


os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

if __name__ == "__main__":
    errs = validate_config()
    if errs:
        print("\n⚠️  Configuration Issues:\n")
        for e in errs:
            print(f"   {e}")
        print("\n📝 Please create .env file with required keys")
    else:
        print("✅ Configuration validated successfully!")
