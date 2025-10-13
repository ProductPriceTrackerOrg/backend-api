# Backend API Performance Optimization

This document outlines the performance optimizations implemented to address API timeouts and improve response times.

## Problem Statement

The frontend was experiencing timeout errors when making requests to certain API endpoints, with a timeout threshold of 20 seconds being exceeded.

Example error:

```
Error fetching personalized recommendations: timeout of 20000ms exceeded
Request timed out, returning fallback data
Using fallback recommendation data due to API error
GET /api/v1/home/recommendations?limit=4 200 in 21952ms
```

When a single page called multiple APIs, approximately 60% of those APIs would fail due to timeouts.

## Solution Implemented

### 1. Asynchronous Query Service

A new `AsyncQueryService` has been implemented to execute BigQuery queries concurrently, with proper timeout handling:

- Executes BigQuery queries in a thread pool to prevent blocking the event loop
- Implements configurable timeouts for each query (default: 15 seconds)
- Provides fallback data when a query times out or fails
- Supports executing multiple queries in parallel to maximize throughput

### 2. Enhanced Caching Strategy

The caching strategy has been improved:

- All high-cost endpoints use Redis caching with appropriate TTLs
- Cache keys are built to account for all query parameters that affect results
- Fallback to cached data when queries timeout or fail

### 3. Gunicorn Worker Configuration

The number of Gunicorn workers has been increased to handle more concurrent requests:

- Worker count increased from 1 to 4 workers
- Worker connections increased to 1000
- Timeout increased to 120 seconds for the worker processes
- Backlog increased to 2048 to accommodate more pending connections

### 4. Optimized Endpoint Implementation

Key endpoints have been refactored to use the new async query service:

- `/api/v1/home/recommendations` - The endpoint that was previously timing out
- `/api/v1/analytics/price-alerts` - Another analytics endpoint with complex queries

## How the Optimization Works

1. When a request comes in, the API first checks Redis cache for the data
2. If not in cache, it starts executing the required BigQuery queries in parallel
3. Each query has a timeout (shorter than the frontend timeout)
4. If a query times out, a predefined fallback strategy provides default data
5. Successful results are cached for future requests

## Additional Recommendations

To further optimize performance:

1. Consider implementing query result pagination for large datasets
2. Review and optimize complex SQL queries, especially those with multiple JOINs
3. Add database indexes for frequently queried columns
4. Consider implementing a background job to pre-cache common queries
5. Monitor Redis memory usage and configure eviction policies appropriately

## Configuring and Scaling

The optimization settings can be adjusted in:

- `app/services/async_query_service.py` - For query timeouts and thread pool size
- `docker-compose.yml` - For worker count
- `docker-entrypoint.sh` - For Gunicorn settings

To scale further:

1. Increase the Gunicorn worker count (set `WORKER_COUNT` environment variable)
2. Adjust the Redis cache TTL values based on data freshness requirements
3. Consider adding more Redis capacity or implementing Redis cluster
4. For truly large-scale deployments, consider implementing a load balancer with multiple API container instances

## Testing the Optimizations

To test the optimizations:

1. Run the Docker container with the updated code
2. Use a tool like Apache Bench or JMeter to simulate multiple concurrent users
3. Monitor response times and success rates
4. Check Redis cache hit rates to verify caching effectiveness
