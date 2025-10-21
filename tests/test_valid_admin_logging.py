"""
Test script for validating admin activity logging with a valid admin UUID
"""

import sys
import os
import json
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("admin-log-test")

# Add the parent directory to sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Load environment variables
load_dotenv()

# Import after env vars are loaded
from app.services.audit_service import log_admin_action
from app.db.supabase_client import get_supabase_client

# Valid admin user UUID provided by you
VALID_ADMIN_UUID = "fb34e91c-7d7f-4ca8-bf6b-647603e1ad50"

def test_log_with_valid_admin():
    """Test logging with a valid admin UUID that exists in the users table"""
    logger.info(f"Testing log_admin_action with valid admin UUID: {VALID_ADMIN_UUID}")
    
    try:
        # Try to log an action with the valid admin UUID
        log_admin_action(
            admin_user_id=VALID_ADMIN_UUID,
            action_type="TEST_VALID_ADMIN",
            target_entity_type="TEST",
            target_entity_id="test123",
            details={"test": "Using valid admin UUID", "timestamp": "now()"}
        )
        
        # Wait a moment and check if it was logged
        import time
        time.sleep(2)
        
        # Check if the record was inserted
        supabase = get_supabase_client()
        response = supabase.table('adminactivitylog').select('*').eq('action_type', 'TEST_VALID_ADMIN').execute()
        
        if response.data:
            logger.info(f"SUCCESS! Test record found: {json.dumps(response.data[0], indent=2)}")
            return True
        else:
            logger.warning(f"Test record not found in adminactivitylog")
            return False
    except Exception as e:
        logger.error(f"Error in test_log_with_valid_admin: {e}")
        return False
        
def check_users_table():
    """Check if the admin user exists in the users table"""
    logger.info(f"Checking if admin user exists in users table: {VALID_ADMIN_UUID}")
    
    try:
        supabase = get_supabase_client()
        response = supabase.table('users').select('*').eq('id', VALID_ADMIN_UUID).execute()
        
        if response.data:
            user_data = response.data[0]
            # Remove sensitive fields for logging
            if 'password' in user_data:
                user_data.pop('password')
            if 'email' in user_data:
                # Mask email for privacy
                email = user_data['email']
                masked_email = email[:3] + '*****' + email[email.index('@'):]
                user_data['email'] = masked_email
                
            logger.info(f"User found in users table: {json.dumps(user_data, indent=2)}")
            return True
        else:
            logger.warning(f"User with ID {VALID_ADMIN_UUID} not found in users table")
            return False
    except Exception as e:
        logger.error(f"Error checking users table: {e}")
        return False
        
def verify_admin_role():
    """Check if the user has admin role"""
    logger.info(f"Verifying if user has admin role: {VALID_ADMIN_UUID}")
    
    try:
        supabase = get_supabase_client()
        response = supabase.table('users').select('role').eq('id', VALID_ADMIN_UUID).execute()
        
        if response.data:
            role = response.data[0].get('role')
            logger.info(f"User role: {role}")
            
            if role and role.lower() == 'admin':
                logger.info("User has admin role!")
                return True
            else:
                logger.warning(f"User does not have admin role. Current role: {role}")
                return False
        else:
            logger.warning(f"Could not retrieve role for user {VALID_ADMIN_UUID}")
            return False
    except Exception as e:
        logger.error(f"Error verifying admin role: {e}")
        return False

if __name__ == "__main__":
    logger.info("=== Testing Admin Activity Logging with Valid Admin UUID ===")
    
    # First check if the admin user exists
    user_exists = check_users_table()
    if not user_exists:
        logger.error("Cannot proceed with tests as the admin user doesn't exist in the users table")
        sys.exit(1)
        
    # Check if the user has admin role
    has_admin_role = verify_admin_role()
    if not has_admin_role:
        logger.warning("User does not have admin role, which might cause problems")
        
    # Test logging with valid admin
    log_success = test_log_with_valid_admin()
    
    # Report results
    logger.info("=== Test Results ===")
    logger.info(f"User Exists in users Table: {'PASSED' if user_exists else 'FAILED'}")
    logger.info(f"User Has Admin Role: {'PASSED' if has_admin_role else 'FAILED'}")
    logger.info(f"Admin Log Entry Created: {'PASSED' if log_success else 'FAILED'}")
    
    if all([user_exists, has_admin_role, log_success]):
        logger.info("All tests PASSED. Admin activity logging appears to be working correctly.")
    else:
        logger.error("Some tests FAILED. Admin activity logging has issues.")