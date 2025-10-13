"""
Asynchronous query executor service for BigQuery.
Implements concurrency for improved performance.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Union, Callable
import time
import logging
from functools import partial
from google.cloud import bigquery

from app.services.cache_service import cache_service
from app.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default timeout for queries in seconds
DEFAULT_QUERY_TIMEOUT = 15

# Thread pool for executing BigQuery queries (which are blocking operations)
_THREAD_POOL = ThreadPoolExecutor(max_workers=10)

class AsyncQueryService:
    """
    Service for executing BigQuery queries asynchronously with timeouts.
    Uses a thread pool to prevent blocking the event loop.
    """
    
    @staticmethod
    async def execute_query(
        bq_client: bigquery.Client,
        query: str,
        cache_key: Optional[str] = None,
        cache_ttl: int = 600,
        timeout: int = DEFAULT_QUERY_TIMEOUT,
        fallback_data: Optional[Any] = None,
        transform_func: Optional[Callable] = None
    ) -> Any:
        """
        Execute a BigQuery query asynchronously with timeout and caching.
        
        Args:
            bq_client: BigQuery client
            query: SQL query string
            cache_key: Redis cache key (if None, caching is disabled)
            cache_ttl: Time-to-live for cache in seconds
            timeout: Query timeout in seconds
            fallback_data: Data to return if the query times out or fails
            transform_func: Function to transform the query results
            
        Returns:
            Query results (or fallback data if the query fails/times out)
        """
        # Check cache first if cache_key is provided
        if cache_key:
            cached_data = cache_service.get(cache_key)
            if cached_data:
                logger.info(f"Cache hit for key: {cache_key}")
                return cached_data
        
        try:
            # Create a partial function with the query
            query_func = partial(AsyncQueryService._execute_bigquery, bq_client, query)
            
            # Execute the query in a thread pool with a timeout
            start_time = time.time()
            results = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(_THREAD_POOL, query_func),
                timeout=timeout
            )
            query_time = time.time() - start_time
            
            # Log query execution time
            logger.info(f"Query executed in {query_time:.2f} seconds")
            
            # Transform results if a transform function is provided
            if transform_func and results:
                results = transform_func(results)
            
            # Cache the results if caching is enabled
            if cache_key and results:
                cache_service.set(cache_key, results, ttl_seconds=cache_ttl)
            
            return results
        
        except asyncio.TimeoutError:
            logger.error(f"Query timed out after {timeout} seconds")
            return fallback_data
        except Exception as e:
            logger.error(f"Error executing query: {str(e)}")
            return fallback_data
    
    @staticmethod
    def _execute_bigquery(client: bigquery.Client, query: str) -> List[Dict]:
        """
        Execute a BigQuery query (blocking operation).
        This method is meant to be run in a thread pool.
        """
        query_job = client.query(query)
        return [dict(row) for row in query_job.result()]
    
    @staticmethod
    async def execute_queries_parallel(
        bq_client: bigquery.Client,
        query_configs: List[Dict]
    ) -> Dict[str, Any]:
        """
        Execute multiple queries in parallel.
        
        Args:
            bq_client: BigQuery client
            query_configs: List of query configuration dicts with keys:
                - query: SQL query string
                - result_key: Key for the result in the returned dict
                - cache_key: Optional Redis cache key
                - cache_ttl: Optional time-to-live for cache in seconds
                - timeout: Optional query timeout in seconds
                - fallback_data: Optional data to return if query fails/times out
                - transform_func: Optional function to transform the query results
                
        Returns:
            Dict with results of each query under its result_key
        """
        # Prepare the list of tasks
        tasks = []
        for config in query_configs:
            task = asyncio.create_task(
                AsyncQueryService.execute_query(
                    bq_client=bq_client,
                    query=config['query'],
                    cache_key=config.get('cache_key'),
                    cache_ttl=config.get('cache_ttl', 600),
                    timeout=config.get('timeout', DEFAULT_QUERY_TIMEOUT),
                    fallback_data=config.get('fallback_data'),
                    transform_func=config.get('transform_func')
                )
            )
            tasks.append((config['result_key'], task))
        
        # Execute all tasks in parallel
        results = {}
        for result_key, task in tasks:
            try:
                results[result_key] = await task
            except Exception as e:
                logger.error(f"Error executing task for {result_key}: {str(e)}")
                results[result_key] = None
        
        return results

# Create a singleton instance of the async query service
async_query_service = AsyncQueryService()