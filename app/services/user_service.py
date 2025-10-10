"""
User service for operations related to user data.
Provides functions for retrieving user statistics and details.
"""
import logging
from typing import Dict, Any, Optional
from app.db.supabase_client import get_supabase_client
from app.services.cache_service import cache_service

logger = logging.getLogger(__name__)

# Cache keys
USER_COUNT_CACHE_KEY = "user_count_total"
USER_COUNT_CACHE_TTL = 3600  # 1 hour

def get_total_users_count() -> int:
    """
    Fetches the total number of users from Supabase.
    Uses caching to improve performance.
    
    Returns:
        int: The total number of users, or 0 if there was an error
    """
    # Try to get from cache first
    cached_count = cache_service.get(USER_COUNT_CACHE_KEY)
    if cached_count is not None:
        return cached_count
    
    try:
        # Get Supabase client
        supabase = get_supabase_client()
        
        # Query users table for count
        # Note: Adjust the table name if your users are stored differently
        response = supabase.table('profiles').select('*', count='exact').execute()
        
        # Get count from response
        total_users = response.count if hasattr(response, 'count') else 0
        
        # Convert to int to ensure it's a standard Python type
        user_count = int(total_users)
        
        # Cache the result
        cache_service.set(USER_COUNT_CACHE_KEY, user_count, USER_COUNT_CACHE_TTL)
        
        return user_count
    except Exception as e:
        logger.error(f"Error fetching user count from Supabase: {e}")
        return 0

def get_user_statistics() -> Dict[str, Any]:
    """
    Gets detailed user statistics for admin dashboards.
    
    Returns:
        Dict with user statistics
    """
    try:
        # Total user count
        total_users = get_total_users_count()
        
        # You can add more detailed statistics here as needed
        # For example: active users, users by role, etc.
        
        return {
            "totalUsers": total_users,
            "activeUsers": 0,  # Placeholder for future implementation
            "newUsersToday": 0  # Placeholder for future implementation
        }
    except Exception as e:
        logger.error(f"Error getting user statistics: {e}")
        return {
            "totalUsers": 0,
            "activeUsers": 0,
            "newUsersToday": 0,
            "error": str(e)
        }