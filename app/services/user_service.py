"""
User service for operations related to user data.
Provides functions for retrieving user statistics and details.
"""
import logging
from typing import Dict, Any, Optional, List
from app.db.supabase_client import get_supabase_client
from app.services.cache_service import cache_service
from datetime import date, timedelta

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
        

# Function for User Sign-ups Chart 
def get_user_signups_over_time(start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """
    Fetches the number of user sign-ups per day over a given date range.
    """
    try:
        supabase = get_supabase_client()
        
        # The 'created_at' column is assumed to be in the 'profiles' table.
        # This query counts users grouped by the date part of their creation timestamp.
        # It filters for users created within the specified date range.
        response = supabase.rpc('get_daily_user_signups', {
            'start_date_param': str(start_date),
            'end_date_param': str(end_date)
        }).execute()

        data = response.data
        
        # The RPC will return a list like [{"signup_date": "2025-09-20", "signup_count": 35}]
        # We need to format it for the frontend.
        chart_data = [{"date": item['signup_date'], "signups": item['signup_count']} for item in data]
        
        # Optional: Fill in missing dates with 0 signups for a continuous line chart
        # This part can be added later if needed for UI perfection.

        return chart_data

    except Exception as e:
        logger.error(f"Error fetching user signups over time: {e}")
        return [{"error": str(e)}]

  
# ```

# **Important:** The query above uses a Supabase RPC (Remote Procedure Call). You need to create this function in your Supabase SQL Editor once.

# **Run this in Supabase SQL Editor:**
# ```sql
# CREATE OR REPLACE FUNCTION get_daily_user_signups(start_date_param date, end_date_param date)
# RETURNS TABLE (signup_date date, signup_count int) AS $$
# BEGIN
#     RETURN QUERY
#     SELECT DATE(created_at) AS signup_date, COUNT(*)::int AS signup_count
#     FROM auth.users -- Standard Supabase table for user creation dates
#     WHERE DATE(created_at) >= start_date_param AND DATE(created_at) <= end_date_param
#     GROUP BY DATE(created_at)
#     ORDER BY DATE(created_at);
# END;
# $$ LANGUAGE plpgsql;



# Function Get User List for User Management 
def get_users(search: Optional[str], is_active: Optional[bool], page: int, per_page: int) -> Dict[str, Any]:
    """
    Fetches a paginated list of users from the profiles table, 
    with optional search and status filters.
    """
    try:
        supabase = get_supabase_client()
        
        # Start building the query. We select all columns needed by the UI.
        query = supabase.table('profiles').select(
            'user_id, email, full_name, is_active',
            count='exact' # This tells Supabase to return the total count for pagination
        )
        
        # Apply search filter if a search term is provided.
        # It searches case-insensitively across 'full_name' and 'email'.
        if search:
            query = query.or_(f"full_name.ilike.%{search}%,email.ilike.%{search}%")
            
        # Apply status filter if 'active' or 'inactive' is specified.
        if is_active is not None:
            query = query.eq('is_active', is_active)
            
        # Apply pagination to fetch only the data for the current page.
        offset = (page - 1) * per_page
        query = query.range(offset, offset + per_page - 1).order('created_at', desc=True)
        
        # Execute the final query.
        response = query.execute()
        
        # Some users might have a null 'full_name'. The API model expects a string.
        # We'll replace any None values with an empty string to prevent validation errors.
        cleaned_users = []
        for user in response.data:
            if user.get('full_name') is None:
                user['full_name'] = ""
            cleaned_users.append(user)

        # Return the cleaned data in the format expected by the frontend.
        return {
            "users": cleaned_users,
            "total": response.count
        }
        

    except Exception as e:
        logger.error(f"Error fetching users list from Supabase: {e}")
        return {"error": str(e)}

# Function for Update a User's Status
def update_user_status(user_id: str, is_active: bool) -> Dict[str, Any]:
    """
    Updates the is_active status for a specific user in the profiles table.
    """
    try:
        supabase = get_supabase_client()
        
        # Perform the update operation on the 'profiles' table for the specified user_id.
        # We also select the 'email' of the updated record, which is useful for audit logging.
        response = supabase.table('profiles').update(
            {'is_active': is_active}
        ).eq('user_id', user_id).execute()
        
        # If the query didn't find a user with that ID, the data list will be empty.
        if not response.data:
            return {"error": f"User with ID {user_id} not found."}
            
        # Return the email of the updated user so the route can create a more descriptive log.
        return {"email": response.data[0]['email']}

    except Exception as e:
        logger.error(f"Error updating user status for {user_id}: {e}")
        return {"error": str(e)}

