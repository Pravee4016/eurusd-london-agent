# EUR/USD London Session Trading Agent - Project Status

**Last Updated:** December 5, 2025
**Status:** 🟢 LIVE / PRODUCTION

## 🚀 Live Deployment
- **Service URL:** `https://eurusd-london-agent-499697087516.us-central1.run.app`
- **Region:** `us-central1`
- **Platform:** Google Cloud Run
- **Scheduler:** `eurusd-london-scheduler` (Runs every 5 mins, 08:00 - 16:00 GMT)

---

## 🏗️ Architecture & Configuration
This agent is specifically adapted for the **London Trading Session** (08:00 - 16:00 GMT) and the **EUR/USD** forex pair.

### Key Components
1.  **Instrument**: `EURUSD` (Finnhub: `OANDA:EUR_USD`)
2.  **Timezone**: `Europe/London` (GMT/BST)
3.  **Data Source**: Finnhub API (Real-time Forex Data)
4.  **AI Model**: `llama-3.3-70b-versatile` (via Groq)
5.  **Notifications**: Telegram Bot (Separate form NIFTY agent)

### Verified Modules
| Module | Status | Notes |
| :--- | :--- | :--- |
| **Data Fetcher** | ✅ Verified | Finnhub integration working correctly. |
| **Analysis** | ✅ Verified | Breakout, Pin Bar, Engulfing, Inside Bar logic confirmed. |
| **Risk Manager** | ✅ Verified | Position sizing (1% risk), daily limits (5 trades). |
| **Telegram** | ✅ Verified | Startup msg, alerts, and summary verified. |
| **Deployment** | ✅ Verified | Cloud Run + Scheduler active. |

---

## 📂 Repository Info
- **Local Path:** `/Users/praveent/eurusd-london-agent`
- **Git Repo:** Initialized and committed (Dec 5)
- **Branch:** `main` (assumed)
- **Config Files:**
    - `.env`: Local secrets (do not commit)
    - `.env.yaml`: Cloud Run secrets (auto-generated)
    - `deploy.sh`: Deployment script
    - `setup_scheduler.sh`: Scheduler configuration script

---

## 🛠️ Maintenance & Operations

### 1. Monitor Logs
To view live logs from the agent:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=eurusd-london-agent" --limit 50 --format json
```

### 2. Manual Trigger
To run the agent immediately (outside schedule):
```bash
gcloud scheduler jobs run eurusd-london-scheduler --location=us-central1
```

### 3. Update & Redeploy
If you make code changes:
1. Edit files.
2. Commit to git: `git add . && git commit -m "Update"`
3. Run deployment:
   ```bash
   ./deploy.sh
   ```

### 4. Update Scheduler
If you need to change hours:
1. Edit `setup_scheduler.sh`.
2. Run `./setup_scheduler.sh`.

---

## 📝 Important Notes
- **Market Hours**: The agent ONLY runs between 08:00 and 16:00 GMT. Outside these hours, it will exit immediately.
- **Dry Run**: To test locally without waiting for market hours: `python3 main.py --dry-run`.
- **Secrets**: Keep `.env` safe. Do not commit it to public repos.

---
*Created by Antigravity Assistant*
