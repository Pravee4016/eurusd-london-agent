#!/bin/bash
# Script to create/update Cloud Scheduler for EUR/USD London Agent

PROJECT_ID="nifty-trading-agent"
REGION="us-central1"
SERVICE_NAME="eurusd-london-agent"
JOB_NAME="eurusd-london-scheduler"
SERVICE_URL="https://eurusd-london-agent-499697087516.us-central1.run.app"

# Schedule: Every 5 minutes from 08:00 to 16:00 UTC (London Session)
# Mon-Fri
SCHEDULE="*/5 8-16 * * 1-5"

echo "⏰ creating Cloud Scheduler job: $JOB_NAME"
echo "   Target: $SERVICE_URL"
echo "   Schedule: $SCHEDULE (UTC)"

if gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$PROJECT_ID > /dev/null 2>&1; then
    echo "   Updating existing job..."
    gcloud scheduler jobs update http $JOB_NAME \
        --location=$REGION \
        --project=$PROJECT_ID \
        --schedule="$SCHEDULE" \
        --uri="$SERVICE_URL" \
        --http-method=POST \
        --time-zone="Etc/UTC"
else
    echo "   Creating new job..."
    gcloud scheduler jobs create http $JOB_NAME \
        --location=$REGION \
        --project=$PROJECT_ID \
        --schedule="$SCHEDULE" \
        --uri="$SERVICE_URL" \
        --http-method=POST \
        --time-zone="Etc/UTC"
fi

echo "✅ Scheduler setup complete!"
echo "   Run 'gcloud scheduler jobs run $JOB_NAME --location=$REGION' to test trigger manually."
