#!/bin/bash
# Deployment script for EUR/USD London Session Trading Agent
# Deploys to Google Cloud Run

set -e

PROJECT_ID="nifty-trading-agent"
SERVICE_NAME="eurusd-london-agent"
REGION="us-central1"

echo "🚀 Deploying EUR/USD London Session Trading Agent..."

# Build and deploy to Cloud Run
# Using --env-vars-file for cleaner configuration management
gcloud run deploy $SERVICE_NAME \
  --source . \
  --platform managed \
  --region $REGION \
  --project $PROJECT_ID \
  --memory 512Mi \
  --timeout 540s \
  --max-instances 1 \
  --env-vars-file .env.yaml \
  --allow-unauthenticated

echo "✅ Deployment complete!"
echo "Service URL: https://$SERVICE_NAME-$REGION.run.app"
