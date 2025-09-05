# Docker Setup for PricePulse Backend API

This guide explains how to set up and run the PricePulse backend using Docker and Docker Compose.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed on your system
- [Docker Compose](https://docs.docker.com/compose/install/) installed on your system

## Quick Start

1. **Set up environment variables:**

   Copy the example env file to create your own:

   ```bash
   cp .env.example .env
   ```

   Edit the `.env` file with your actual credentials:

   - Supabase credentials
   - GCP project ID and BigQuery dataset ID
   - Any other required configuration

2. **Build and run the containers:**

   ```bash
   docker-compose up --build
   ```

   This command builds the Docker image and starts the service. The API will be available at http://localhost:9000.

3. **Access the API documentation:**

   Open your browser and navigate to:

   - Swagger UI: http://localhost:9000/docs
   - ReDoc: http://localhost:9000/redoc

## Running in Background

To run the containers in detached mode (in the background):

```bash
docker-compose up -d
```

## Stopping the Services

To stop the running containers:

```bash
docker-compose down
```

## Viewing Logs

To view the logs of the running containers:

```bash
docker-compose logs -f
```

To view logs for a specific service:

```bash
docker-compose logs -f api
```

## Container Structure

- **api**: The FastAPI application running on port 8000
- **redis** (optional): Redis cache service running on port 6379 (uncomment in docker-compose.yml to enable)

## Google Cloud Authentication

The application uses a service account to authenticate with Google Cloud. The credentials file (`gcp-credentials.json`) is mounted into the container as a read-only volume.

Make sure your service account has the necessary permissions to access BigQuery datasets and tables.

## Environment Variables

See the `.env.example` file for all required environment variables. Make sure to set these correctly in your `.env` file before running the containers.

## Development with Docker

For development purposes, you can modify the Docker Compose configuration to mount your local code directory into the container, enabling live code reloading:

```yaml
services:
  api:
    # ... existing configuration ...
    volumes:
      - ./:/app
      - ./gcp-credentials.json:/app/gcp-credentials.json:ro
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

This will enable the uvicorn server to reload whenever you make changes to your local code.
