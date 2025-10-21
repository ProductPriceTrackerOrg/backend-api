#!/bin/bash
# This script runs inside the Docker container to perform startup tasks

set -e

# Check if GCP credentials file exists
if [ ! -f "/app/gcp-credentials.json" ] && [ "${SKIP_GCP_CHECK}" != "true" ]; then
    echo "ERROR: GCP credentials file not found!"
    echo "Make sure to mount gcp-credentials.json as a volume in docker-compose.yml"
    echo "Or set SKIP_GCP_CHECK=true to bypass this check (for development only)"
    exit 1
elif [ ! -f "/app/gcp-credentials.json" ]; then
    echo "WARNING: GCP credentials file not found, but continuing as SKIP_GCP_CHECK is set"
fi

# Print startup information
echo "Starting PricePulse API..."
echo "Environment: ${DATA_SOURCE:-unknown}"
echo "GCP Project: ${GCP_PROJECT_ID:-not set}"
echo "BigQuery Dataset: ${BIGQUERY_DATASET_ID:-not set}"

# Start the application
echo "Starting gunicorn server with ${WORKER_COUNT:-6} workers..."
exec gunicorn -w ${WORKER_COUNT:-6} -k uvicorn.workers.UvicornWorker --timeout 120 --worker-connections=1000 --backlog=2048 -b 0.0.0.0:${PORT:-8000} app.main:app
