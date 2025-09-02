#!/bin/bash
# This script runs inside the Docker container to perform startup tasks

set -e

# Check if GCP credentials file exists
if [ ! -f "/app/gcp-credentials.json" ]; then
    echo "ERROR: GCP credentials file not found!"
    echo "Make sure to mount gcp-credentials.json as a volume in docker-compose.yml"
    exit 1
fi

# Print startup information
echo "Starting PricePulse API..."
echo "Environment: ${DATA_SOURCE:-unknown}"
echo "GCP Project: ${GCP_PROJECT_ID:-not set}"
echo "BigQuery Dataset: ${BIGQUERY_DATASET_ID:-not set}"

# Start the application
echo "Starting uvicorn server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} ${RELOAD_FLAG}
