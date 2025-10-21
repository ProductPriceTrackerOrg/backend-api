"""
Test script for the audit_service module
This script tests if audit logging is working correctly
"""
import os
import sys
import time
import logging
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add the parent directory to sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

try:
    # Import from app
    from app.services.audit_service import log_admin_action
    from app.db.supabase_client import get_supabase_client
    
    logger.info("Testing audit_service log_admin_action functionality...")
    
    # Generate a test admin ID (this would be a real admin ID in production)
    test_admin_id = str(uuid.uuid4())
    
    # Test parameters
    test_action = "TEST_AUDIT_LOG"
    test_entity_type = "TEST_ENTITY"
    test_entity_id = "test-123"
    test_details = {"test_key": "test_value", "timestamp": time.time()}
    
    # Try to log an action
    try:
        logger.info(f"Logging test action with admin ID: {test_admin_id}")
        
        log_admin_action(
            admin_user_id=test_admin_id,
            action_type=test_action,
            target_entity_type=test_entity_type,
            target_entity_id=test_entity_id,
            details=test_details
        )
        
        # Now verify it was logged properly
        logger.info("Verifying log entry was created...")
        supabase = get_supabase_client()
        
        # Query for our test entry
        response = supabase.table('adminactivitylog').select("*").eq('admin_user_id', test_admin_id).eq('action_type', test_action).limit(1).execute()
        
        if response.data:
            logger.info(f"✅ Successfully found log entry: {response.data}")
        else:
            logger.error("❌ Log entry not found! The audit logging is not working correctly.")
            
        # Let's check if the adminactivitylog table exists and its structure
        logger.info("\nChecking adminactivitylog table structure...")
        
        try:
            # This is a simple query to check if the table exists and get some rows
            structure_query = supabase.table('adminactivitylog').select("*").limit(5).execute()
            
            if structure_query.data:
                logger.info(f"Found {len(structure_query.data)} existing log entries.")
                logger.info(f"Example log entry: {structure_query.data[0]}")
                logger.info(f"Table columns: {list(structure_query.data[0].keys())}")
            else:
                logger.info("Table exists but no rows found.")
        except Exception as table_error:
            logger.error(f"Error accessing adminactivitylog table: {table_error}")
            logger.error("This suggests the table might not exist or has incorrect permissions.")
            
    except Exception as e:
        logger.error(f"Error during audit logging test: {e}")
        
except ImportError as e:
    logger.error(f"Import error: {e}")
    logger.error("Make sure you're running this script from the backend-api directory")
    sys.exit(1)
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    sys.exit(1)