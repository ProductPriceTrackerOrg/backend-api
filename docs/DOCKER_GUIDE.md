# PricePulse API Docker Guide

This document provides detailed instructions for setting up, running, and maintaining the PricePulse API using Docker.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Docker Environments](#docker-environments)
3. [Development Workflow](#development-workflow)
4. [Testing](#testing)
5. [Production Deployment](#production-deployment)
6. [Troubleshooting](#troubleshooting)

## Getting Started

### Prerequisites

- Docker installed on your system
- Docker Compose installed on your system
- GCP credentials file (gcp-credentials.json) for BigQuery access

### Initial Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/ProductPriceTrackerOrg/backend-api.git
   cd backend-api
   ```

2. Set up environment variables:

   ```bash
   cp .env.example .env
   ```

   Edit the `.env` file with your actual credentials.

3. Make helper scripts executable:

   ```bash
   chmod +x *.sh
   ```

4. Build and start the development container:

   ```bash
   docker-compose -f docker-compose.dev.yml up --build -d
   ```

5. Verify the API is running:
   ```bash
   curl http://localhost:8000/health
   ```

## Docker Environments

### Development Environment (docker-compose.dev.yml)

- Hot code reloading (changes take effect immediately)
- Volume mounts for local code
- Redis container included
- Extended logging and debugging

To use:

```bash
docker-compose -f docker-compose.dev.yml up -d
```

### Production Environment (docker-compose.yml)

- Optimized for performance and security
- No code reloading
- Minimal container exposure
- Enhanced healthchecks

To use:

```bash
docker-compose up -d
```

## Development Workflow

1. Start the development environment:

   ```bash
   ./docker-helper.sh up
   ```

2. Make code changes in your local editor - they will be automatically reflected in the container

3. View logs to see errors or output:

   ```bash
   ./docker-helper.sh logs
   ```

4. Run tests to verify changes:

   ```bash
   ./docker-test.sh
   ```

5. Stop the environment when done:
   ```bash
   ./docker-helper.sh down
   ```

## Testing

### Running Tests

To run all tests:

```bash
./docker-test.sh
```

To run specific tests:

```bash
./docker-test.sh tests/test_trending.py
```

### Debugging Tests

To debug tests interactively:

```bash
docker-compose exec api python -m pytest tests/test_file.py -v --pdb
```

## Production Deployment

### Building for Production

1. Update the `.env` file with production credentials (never commit this file)

2. Build the production image:

   ```bash
   docker-compose build
   ```

3. Start the production containers:
   ```bash
   docker-compose up -d
   ```

### Monitoring in Production

- Health check endpoint: `http://localhost:8000/health`
- View logs: `docker-compose logs -f`
- Container status: `docker-compose ps`

## Troubleshooting

### Common Issues

1. **BigQuery authentication errors**

   - Check that `gcp-credentials.json` is correctly mounted in the container
   - Verify the service account has the right permissions
   - Confirm environment variables are set correctly

2. **Container fails to start**

   - Check logs: `docker-compose logs api`
   - Verify port 8000 is not already in use
   - Check for Python dependency issues

3. **API returns 500 errors**
   - Check application logs for exceptions
   - Verify BigQuery dataset and tables exist
   - Test database connectivity

### Resetting the Environment

To completely reset the Docker environment:

```bash
docker-compose down
docker volume prune -f
docker-compose up --build -d
```
