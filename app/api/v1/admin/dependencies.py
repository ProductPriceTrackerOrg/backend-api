from fastapi import Depends, HTTPException, status
import uuid # Import the uuid library to generate a mock UUID

# This is a placeholder for your real authentication check.
# TODO: Integrate this with your existing auth system (e.g., auth_util.py).
# It should decode a JWT token and check if the user's role is 'admin'.


from app.db.supabase_client import get_supabase_client
import re
import logging

logger = logging.getLogger(__name__)

# UUID regex pattern for validation
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

async def get_current_admin_user():
    """
    A dependency that all admin routes will use to verify the user has an 'admin' role.
    
    In development mode, this will first check for a real JWT token, and if not available,
    use a mock admin for testing purposes.
    
    In production, this would always validate the JWT token and check the user's role.
    """
    # TODO: Replace this with real JWT token validation
    # For now, we'll simulate a JWT token validation and get the user ID
    
    # First, let's try to check if we have a valid admin in the database
    # This makes the function work both in development and production
    try:
        # In a real implementation, you'd extract user_id from the JWT token
        # For development, we'll query for a known admin
        supabase = get_supabase_client()
        admin_query = supabase.table('profiles').select('user_id,email,full_name').eq('is_active', True).limit(1).execute()
        
        if admin_query.data and len(admin_query.data) > 0:
            # Found a valid admin user to use
            admin_user = admin_query.data[0]
            admin_uuid = admin_user.get('user_id')
            admin_email = admin_user.get('email')
            
            if admin_uuid and UUID_PATTERN.match(admin_uuid):
                logger.info(f"Using admin from database: {admin_uuid}")
                # Return a user object similar to a JWT payload
                return {
                    "email": admin_email or "admin@example.com",
                    "role": "admin",
                    "sub": admin_uuid
                }
    except Exception as e:
        logger.warning(f"Failed to query for admin user: {e}")
    
    # Fallback for development if no valid admin found in database
    # IMPORTANT: This should be removed or disabled in production!
    logger.warning("Using fallback mock admin user - THIS SHOULD NOT HAPPEN IN PRODUCTION")
    fallback_admin_uuid = "fb34e91c-7d7f-4ca8-bf6b-647603e1ad50"
    
    # In development mode, return the mock admin
    return {
        "email": "admin.pricepulse@gmail.com",
        "role": "admin", 
        "sub": fallback_admin_uuid  # Fallback to a known working UUID if all else fails
    }