"""
Cache service for performance optimization.
Implements Redis caching for frequently accessed data.
"""
import json
import time
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import redis

from app.config import settings

# Default cache settings
DEFAULT_CACHE_TTL = 600  # 10 minutes in seconds

# Configure logging
logger = logging.getLogger(__name__)


def _json_serializer(value: Any) -> Any:
    """Serialize unsupported types for JSON storage."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump")):
        return value.model_dump()
    if hasattr(value, "dict") and callable(getattr(value, "dict")):
        return value.dict()
    if isinstance(value, set):
        return list(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

class CacheService:
    """
    Service for caching data in Redis with TTL (Time-To-Live).
    """
    def __init__(self):
        # If Redis URL is available, use it; otherwise set redis_client to None
        self.debug = getattr(settings, 'CACHE_DEBUG', False)
        
        if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
            try:
                self.redis_client = redis.from_url(settings.REDIS_URL)
                self.enabled = True
                logger.info("Redis cache initialized successfully")
                if self.debug:
                    logger.info(f"Connected to Redis at {settings.REDIS_URL}")
            except Exception as e:
                logger.error(f"Failed to initialize Redis client: {e}")
                self.redis_client = None
                self.enabled = False
        else:
            logger.warning("Redis URL not provided, cache will be disabled")
            self.redis_client = None
            self.enabled = False
            
        # Track performance metrics
        self.hit_count = 0
        self.miss_count = 0

    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache by key.
        Returns None if the key does not exist or cache is disabled.
        """
        if not self.enabled or not self.redis_client:
            if self.debug:
                logger.info(f"Cache disabled, skipping get for key: {key}")
            return None
            
        start_time = time.time()
        try:
            value = self.redis_client.get(key)
            if value:
                self.hit_count += 1
                elapsed = time.time() - start_time
                if self.debug:
                    logger.info(f"CACHE HIT: {key} in {elapsed:.4f}s")
                return json.loads(value)
                
            # Cache miss
            self.miss_count += 1
            if self.debug:
                logger.info(f"CACHE MISS: {key}")
            return None
        except Exception as e:
            logger.error(f"Error reading from cache: {e}")
            return None

    def set(self, key: str, value: Any, ttl_seconds: int = DEFAULT_CACHE_TTL) -> bool:
        """
        Set a value in the cache with a TTL.
        Returns True on success, False on failure or if cache is disabled.
        """
        if not self.enabled or not self.redis_client:
            if self.debug:
                logger.info(f"Cache disabled, skipping set for key: {key}")
            return False
            
        start_time = time.time()
        try:
            serialized = json.dumps(value, default=_json_serializer)
            data_size = len(serialized)
            
            result = self.redis_client.setex(key, ttl_seconds, serialized)
            elapsed = time.time() - start_time
            
            if self.debug:
                if isinstance(value, list):
                    item_count = len(value)
                    logger.info(f"Cached {item_count} items with key: {key}, size: {data_size} bytes, TTL: {ttl_seconds}s in {elapsed:.4f}s")
                else:
                    logger.info(f"Cached key: {key}, size: {data_size} bytes, TTL: {ttl_seconds}s in {elapsed:.4f}s")
            
            return result
        except Exception as e:
            logger.error(f"Error writing to cache: {e}")
            return False

    def delete(self, key: str) -> bool:
        """
        Delete a key from the cache.
        Returns True on success, False on failure or if cache is disabled.
        """
        if not self.enabled or not self.redis_client:
            if self.debug:
                logger.info(f"Cache disabled, skipping delete for key: {key}")
            return False
            
        try:
            result = bool(self.redis_client.delete(key))
            if self.debug:
                if result:
                    logger.info(f"Successfully deleted cache key: {key}")
                else:
                    logger.info(f"Key not found for deletion: {key}")
            return result
        except Exception as e:
            logger.error(f"Error deleting from cache: {e}")
            return False

    def delete_pattern(self, pattern: str) -> bool:
        """
        Delete keys matching a pattern.
        Returns True if any keys were deleted, False otherwise.
        """
        if not self.enabled or not self.redis_client:
            if self.debug:
                logger.info(f"Cache disabled, skipping delete pattern: {pattern}")
            return False
            
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                result = bool(self.redis_client.delete(*keys))
                if self.debug:
                    logger.info(f"Deleted {len(keys)} keys matching pattern: {pattern}")
                return result
                
            if self.debug:
                logger.info(f"No keys found matching pattern: {pattern}")
            return False
        except Exception as e:
            logger.error(f"Error deleting pattern from cache: {e}")
            return False

    def flush(self) -> bool:
        """
        Flush the entire cache.
        Use with caution! This will delete all keys in the current database.
        """
        if not self.enabled or not self.redis_client:
            if self.debug:
                logger.info("Cache disabled, skipping flush")
            return False
            
        try:
            result = bool(self.redis_client.flushdb())
            if self.debug:
                logger.info("Successfully flushed entire cache database")
            return result
        except Exception as e:
            logger.error(f"Error flushing cache: {e}")
            return False
            
    def get_stats(self) -> Dict[str, Any]:
        """
        Returns cache statistics for monitoring and debugging.
        """
        if not self.enabled or not self.redis_client:
            return {"enabled": False, "status": "disabled"}
            
        try:
            total_requests = self.hit_count + self.miss_count
            hit_rate = (self.hit_count / total_requests) * 100 if total_requests > 0 else 0
            
            # Get Redis info
            info = self.redis_client.info()
            
            stats = {
                "enabled": self.enabled,
                "status": "connected",
                "hits": self.hit_count,
                "misses": self.miss_count,
                "total_requests": total_requests,
                "hit_rate_percent": round(hit_rate, 2),
                "redis_version": info.get("redis_version", "unknown"),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "connected_clients": info.get("connected_clients", "unknown"),
                "uptime_in_seconds": info.get("uptime_in_seconds", "unknown"),
                "total_keys": len(self.redis_client.keys("*")) if self.redis_client else 0
            }
            
            return stats
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {
                "enabled": self.enabled, 
                "status": "error",
                "error": str(e)
            }

# Create a singleton instance of the cache service
cache_service = CacheService()
