"""
Cache service for performance optimization.
Implements Redis caching for frequently accessed data.
"""
import json
from typing import Any, Dict, List, Optional, Union
from datetime import timedelta
import redis

from app.config import settings

# Default cache settings
DEFAULT_CACHE_TTL = 600  # 10 minutes in seconds

class CacheService:
    """
    Service for caching data in Redis with TTL (Time-To-Live).
    """
    def __init__(self):
        # If Redis URL is available, use it; otherwise set redis_client to None
        if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
            try:
                self.redis_client = redis.from_url(settings.REDIS_URL)
                self.enabled = True
            except Exception as e:
                print(f"Failed to initialize Redis client: {e}")
                self.redis_client = None
                self.enabled = False
        else:
            self.redis_client = None
            self.enabled = False

    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache by key.
        Returns None if the key does not exist or cache is disabled.
        """
        if not self.enabled or not self.redis_client:
            return None
            
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            print(f"Error reading from cache: {e}")
            return None

    def set(self, key: str, value: Any, ttl_seconds: int = DEFAULT_CACHE_TTL) -> bool:
        """
        Set a value in the cache with a TTL.
        Returns True on success, False on failure or if cache is disabled.
        """
        if not self.enabled or not self.redis_client:
            return False
            
        try:
            serialized = json.dumps(value)
            return self.redis_client.setex(key, ttl_seconds, serialized)
        except Exception as e:
            print(f"Error writing to cache: {e}")
            return False

    def delete(self, key: str) -> bool:
        """
        Delete a key from the cache.
        Returns True on success, False on failure or if cache is disabled.
        """
        if not self.enabled or not self.redis_client:
            return False
            
        try:
            return bool(self.redis_client.delete(key))
        except Exception as e:
            print(f"Error deleting from cache: {e}")
            return False

    def delete_pattern(self, pattern: str) -> bool:
        """
        Delete keys matching a pattern.
        Returns True if any keys were deleted, False otherwise.
        """
        if not self.enabled or not self.redis_client:
            return False
            
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return bool(self.redis_client.delete(*keys))
            return False
        except Exception as e:
            print(f"Error deleting pattern from cache: {e}")
            return False

    def flush(self) -> bool:
        """
        Flush the entire cache.
        Use with caution! This will delete all keys in the current database.
        """
        if not self.enabled or not self.redis_client:
            return False
            
        try:
            return bool(self.redis_client.flushdb())
        except Exception as e:
            print(f"Error flushing cache: {e}")
            return False

# Create a singleton instance of the cache service
cache_service = CacheService()
