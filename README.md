# EUR/USD London Session Trading Agent

**A production-ready algorithmic trading system for EUR/USD forex pair focused on the London trading session (08:00-16:00 GMT) with 6 pattern detection strategies, Finnhub API integration, and automated performance tracking.**

---

## 🚀 Current Status

- **Version**: v1.0.0-live
- **Platform**: Google Cloud Run (Deployed)
- **Service URL**: `https://eurusd-london-agent-499697087516.us-central1.run.app`
- **Data Provider**: Finnhub API
- **Trading Hours**: London Session (08:00-16:00 GMT, Mon-Fri)
- **Currency Pair**: EUR/USD
- **Scheduler**: Active (`eurusd-london-scheduler`, every 5 min)

---

## 📊 Features

### Pattern Detection (6 Types)
✅ **Breakouts/Breakdowns** - With consolidation, volume surge, and time-of-day filters  
✅ **Retest Setups** - Support/resistance with role reversal logic  
✅ **Inside Bars** - VWAP/EMA/trend-aligned high-probability setups  
✅ **Pin Bars** - Hammer and Shooting Star rejection patterns  
✅ **Engulfing Candles** - Bullish/bearish reversal patterns with volume  

### Forex-Specific Features
✅ **Pip-Based Analytics** - All calculations in pips (not percentages)  
✅ **Round Number Support** - Psychological levels (00, 20, 50, 80 pips)  
✅ **London Session Optimization** - Opening range breakouts (08:00-08:30 GMT)  
✅ **4-Decimal Precision** - Proper forex pricing (e.g., 1.0950)  

### Risk Management
✅ **Per-Type Limits** - Max 10 alerts per signal type  
✅ **Per-Instrument Limits** - Max 15 alerts for EUR/USD  
✅ **Choppy Session Filter** - Blocks signals in low volatility markets  
✅ **Correlation Check** - Prevents herding (max 3 same-direction in 15m)  
✅ **Duplicate Prevention** - Fuzzy matching + level-based memory  

### Intelligence
✅ **Multi-Timeframe Analysis** - 5m (execution) + 15m (trend) + Daily (bias)  
✅ **AI-Powered Insights** - Groq LLM for contextual analysis  
✅ **Dynamic S/R Levels** - Automated support/resistance detection  
✅ **Finnhub Real-Time Data** - Professional forex data feed  

---

## 🏗️ Architecture

```
┌─────────────────┐
│ Cloud Scheduler │ (Every 5 min during London hours)
└────────┬────────┘
         │
         v
┌─────────────────────────────────────┐
│   Google Cloud Run (main.py)        │
├─────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐ │
│  │ Data Fetcher │  │   Technical  │ │
│  │ (Finnhub API)│→│   Analysis   │ │
│  └──────────────┘  └──────┬───────┘ │
│                            │          │
│                            v          │
│  ┌──────────────┐  ┌──────────────┐ │
│  │ AI Analyzer  │  │   Pattern    │ │
│  │   (Groq)     │←│  Detection   │ │
│  └──────────────┘  └──────┬───────┘ │
│                            │          │
│                            v          │
│  ┌──────────────┐  ┌──────────────┐ │
│  │ Risk Manager │  │Trade Tracker │ │
│  │  (Filters)   │  │ (Firestore)  │ │
│  └──────────────┘  └──────┬───────┘ │
└────────────────────────────┼────────┘
                             │
                             v
                    ┌────────────────┐
                    │ Telegram Bot   │
                    │ (Alerts/Stats) │
                    └────────────────┘
```

---

## 📁 Project Structure

```
eurusd-london-agent/
├── analysis_module/
│   └── technical.py              # Pattern detection & TA (forex-adapted)
├── ai_module/
│   └── groq_analyzer.py         # AI analysis
├── data_module/
│   ├── fetcher.py                # Finnhub forex data
│   ├── persistence.py            # Daily stats
│   └── trade_tracker.py         # Trade tracking
├── telegram_module/
│   └── bot_handler.py           # Alerts & summaries
├── config/
│   └── settings.py              # EUR/USD configuration
├── main.py                      # Orchestrator
├── deploy.sh                    # Deployment script
├── requirements.txt             # Dependencies
├── .env.example                 # Environment template
└── README.md                    # This file
```

---

## 🧑 Setup & Deployment

### Prerequisites
- Python 3.11+
- Finnhub API Key (get from [finnhub.io](https://finnhub.io))
- Groq API Key (get from [groq.com](https://groq.com))
- Google Cloud account with:
  - Cloud Run API enabled
  - Firestore database created
  - Cloud Scheduler configured
- Telegram Bot Token (separate from NIFTY agent)

### Installation

```bash
# Clone repository
cd /Users/praveent/eurusd-london-agent

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys and credentials
```

### Deploy to Production

```bash
# 1. Update deploy.sh with your GCP project ID
# 2. Create .env.yaml from .env.yaml.example with your credentials
# 3. Deploy
chmod +x deploy.sh
./deploy.sh
```

###  Cloud Scheduler Configuration

Schedule every 5 minutes during London session:
```
# Cron expression (GMT time)
*/5 8-15 * * 1-5

# Or use gcloud command:
gcloud scheduler jobs create http eurusd-agent-trigger \\
  --schedule="*/5 8-15 * * 1-5" \\
  --uri="YOUR_CLOUD_RUN_URL" \\
  --time-zone="Europe/London" \\
  --http-method=POST
```

---

## ⚙️ Configuration

Key parameters in `config/settings.py`:

```python
# Trading
MIN_SIGNAL_CONFIDENCE = 65           # Minimum confidence %
MIN_RISK_REWARD_RATIO = 1.5          # Minimum R:R
BREAKOUT_CONFIRMATION_PIPS = 5       # Breakout buffer (pips)
RETEST_ZONE_PIPS = 10                # Retest proximity (pips)

# Risk Management
MAX_ALERTS_PER_DAY = 999             # Rely on other filters
MAX_ALERTS_PER_TYPE = 10             # Per pattern limit
MAX_ALERTS_PER_INSTRUMENT = 15       # Per EUR/USD limit
MIN_ATR_PERCENT = 0.2                # Min volatility (0.2% ≈ 22 pips)

# London Session Hours (GMT)
TIME_ZONE = "Europe/London"
MARKET_OPEN_TIME = "08:00"
MARKET_CLOSE_TIME = "16:00"
```

---

## 📈 Trading Strategy

### London Session Focus
- **Opening Range**: 08:00-08:30 GMT (30-minute ORB)
- **Prime Trading**: 08:05-15:00 GMT
- **Avoid**: First 5 mins (volatility), last hour (pre-US session)

### Signal Types & Expected Performance
1. **Opening Range Breakout**: Highest probability (targeting 20-30 pips)
2. **Round Number Retest**: Strong forex-specific setup
3. **Pin Bars at Key Levels**: Rejection patterns
4. **Trend Continuation**: Inside bars + breakouts aligned with 15m trend

### Typical Day (Expected)
- **Alerts Generated**: 3-6 during London session
- **False Signals**: <20% (with all filters)
- **Average Risk:Reward**: 1.5:1 minimum
- **Typical TP**: 20-30 pips | SL: 10-15 pips

---

## 📊 Monitoring

### Cloud Run Logs
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=eurusd-london-agent" --limit 50 --format json
```

### Firestore Collections
- `eurusd_daily_stats`: Daily event counts
- `eurusd_trades`: Individual trade records with outcomes

### Telegram Notifications
- Real-time alerts during London hours (08:00-16:00 GMT)
- Daily summary at 16:05 GMT (London close)

---

## 🔄 Differences from NIFTY Agent

| Feature | NIFTY Agent | EUR/USD Agent |
|---------|-------------|---------------|
| **Data Source** | NSE API + yfinance | Finnhub API |
| **Trading Hours** | 09:15-15:30 IST | 08:00-16:00 GMT |
| **Timezone** | Asia/Kolkata | Europe/London |
| **Price Units** | Points (0.05 INR) | Pips (0.0001 USD) |
| **Price Format** | 2 decimals | 4 decimals |
| **S/R Clustering** | Percentage-based | Pip-based (5 pips) |
| **Round Numbers** | N/A | 00, 20, 50, 80 pips |
| **Opening Range** | 09:15-09:30 IST | 08:00-08:30 GMT |
| **Telegram Bot** | Shared | Separate |
| **GCP Project** | Shared | New project |

---

## 🛠️ Maintenance

### Regular Tasks
- Monitor Cloud Run logs weekly
- Review Firestore performance metrics monthly
- Adjust parameters for London session volatility patterns

### Troubleshooting
- **No alerts**: Check Cloud Scheduler, Finnhub API status, API key limits
- **Deployment fails**: Review Cloud Run logs
- **Telegram not sending**: Verify bot token in .env.yaml

---

## ⚠️ Disclaimer

This system is for informational and educational purposes only. It does not constitute financial advice. Forex trading involves significant risk of loss. Past performance does not guarantee future results. Use at your own risk.

---

**Built with**: Python, Finnhub API, Google Cloud Run, Firestore, Groq AI, Telegram Bot API

**Adapted from**: [NIFTY AI Trading Agent](../nifty-ai-trading-agent)

**Last Updated**: 2025-12-05  
**Maintained by**: Internal Development
