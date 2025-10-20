"""
Service for logging administrator actions to the audit trail.
This service writes structured data to the 'adminactivitylog' table in Supabase.
"""
import logging
import uuid
import re
from typing import Dict, Any, Optional

# Import the function to get our singleton Supabase client
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# UUID regex pattern for validation
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)

def validate_uuid(uuid_str: str) -> bool:
    """
    Validates if a string is a valid UUID format.
    
    Args:
        uuid_str: The string to validate as UUID.
        
    Returns:
        bool: True if valid UUID format, False otherwise.
    """
    if not uuid_str:
        return False
        
    return bool(UUID_PATTERN.match(uuid_str))

def log_admin_action(
    admin_user_id: str,
    action_type: str,
    target_entity_type: Optional[str] = None,
    target_entity_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """
    Writes a new structured entry to the adminactivitylog table.
    
    Args:
        admin_user_id: The UUID of the admin who performed the action.
        action_type: A standardized string for the action (e.g., 'UPDATE_USER_STATUS').
        target_entity_type: The type of object being changed (e.g., 'USER').
        target_entity_id: The ID of the object being changed.
        details: A JSON-compatible dictionary for extra context.
    """
    try:
        # Validate UUID format first
        if not validate_uuid(admin_user_id):
            logger.error(f"Invalid UUID format for admin_user_id: {admin_user_id}")
            logger.info("Admin actions must use a valid UUID that exists in the users table")
            return
            
        # Try to get the Supabase client with better error handling
        try:
            supabase = get_supabase_client()
        except Exception as client_error:
            logger.error(f"Failed to initialize Supabase client for audit logging: {client_error}")
            # We don't propagate this error since logging is non-critical
            return
        
        # Prepare the data payload for insertion
        log_entry = {
            'admin_user_id': admin_user_id,
            'action_type': action_type,
            'target_entity_type': target_entity_type,
            'target_entity_id': str(target_entity_id) if target_entity_id else None,
            'details_json': details,
            # Make sure we're setting the timestamp if the table expects it
            'activity_timestamp': 'now()'  # Use Postgres now() function
        }
        
        logger.info(f"Preparing to log admin action: {action_type} by admin: {admin_user_id}")
        logger.info(f"Log entry data: {log_entry}")
        
        # Insert a new row into our log table with timeout
        try:
            # First check if the table exists to provide better error messages
            try:
                check_query = supabase.table('adminactivitylog').select('*').limit(1).execute()
                logger.info(f"adminactivitylog table exists and is accessible")
            except Exception as table_error:
                logger.error(f"Error accessing adminactivitylog table: {table_error}")
                logger.error("The table might not exist or you don't have proper permissions")
                return
                
            # Now attempt to insert the record
            logger.info("Inserting record into adminactivitylog...")
            response = supabase.table('adminactivitylog').insert(log_entry).execute()
            
            if response.data:
                logger.info(f"Successfully logged admin action for {admin_user_id}: {action_type}")
                logger.info(f"Response data: {response.data}")
            else:
                logger.warning(f"Admin action logged but no data returned in response")
                
        except Exception as insert_error:
            error_msg = str(insert_error)
            logger.error(f"Failed to insert audit log entry: {error_msg}")
            
            # Check for foreign key violation
            if "violates foreign key constraint" in error_msg and "adminactivitylog_admin_user_id_fkey" in error_msg:
                logger.error(f"The admin_user_id ({admin_user_id}) does not exist in the profiles table")
                logger.error("Make sure the admin user exists in the database before logging actions")
                
                # Check if this admin exists in profiles
                try:
                    check_profile = supabase.table('profiles').select('user_id,email').eq('user_id', admin_user_id).execute()
                    if check_profile.data:
                        logger.info(f"Found user in profiles table: {check_profile.data}")
                    else:
                        logger.error(f"Admin {admin_user_id} not found in profiles table")
                except Exception as profile_error:
                    logger.error(f"Error checking profiles table: {profile_error}")
            
            # Non-critical failure, we continue without raising

    except Exception as e:
        # We log the error but don't raise an exception, as a failure to log
        # should not cause the main API action to fail.
        logger.error(f"Failed to log admin action: {e}")

