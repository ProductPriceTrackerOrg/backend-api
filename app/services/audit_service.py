"""
Service for logging administrator actions to the audit trail.
This service writes structured data to the 'adminactivitylog' table in Supabase.
"""
import logging
from typing import Dict, Any, Optional

# Import the function to get our singleton Supabase client
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

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
        supabase = get_supabase_client()
        
        # Prepare the data payload for insertion
        log_entry = {
            'admin_user_id': admin_user_id,
            'action_type': action_type,
            'target_entity_type': target_entity_type,
            'target_entity_id': str(target_entity_id) if target_entity_id else None,
            'details_json': details
        }
        
        # Insert a new row into our log table
        response = supabase.table('adminactivitylog').insert(log_entry).execute()
        
        logger.info(f"Successfully logged admin action for {admin_user_id}: {action_type}")

    except Exception as e:
        # We log the error but don't raise an exception, as a failure to log
        # should not cause the main API action to fail.
        logger.error(f"Failed to log admin action: {e}")

