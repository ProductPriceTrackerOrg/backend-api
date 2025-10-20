"""
Test script for diagnosing issues with admin activity logging
"""

import sys
import os
import time
import json
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("audit-test")

# Add the parent directory to sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Load environment variables
load_dotenv()

# Import after env vars are loaded
from app.services.audit_service import log_admin_action
from app.db.supabase_client import get_supabase_client

def test_table_existence():
    """Check if the adminactivitylog table exists and its schema"""
    logger.info("Testing adminactivitylog table existence...")
    
    try:
        # Get client
        supabase = get_supabase_client()
        
        # Check if the table exists by trying to select from it
        response = supabase.table('adminactivitylog').select('*').limit(1).execute()
        logger.info(f"Table exists with {len(response.data)} sample records")
        
        # If we have a record, show its structure
        if response.data:
            logger.info(f"Sample record structure: {json.dumps(response.data[0], indent=2)}")
        
        # Get column info by trying to access one record with all fields
        if not response.data:
            logger.info("No existing records found. Creating a test record to examine structure...")
            test_record = {
                'admin_user_id': 'test_user',
                'action_type': 'TEST_SCHEMA_CHECK',
                'target_entity_type': 'test',
                'target_entity_id': '0',
                'details_json': {'test': True}
            }
            insert_response = supabase.table('adminactivitylog').insert(test_record).execute()
            if insert_response.data:
                logger.info(f"Created test record with structure: {json.dumps(insert_response.data[0], indent=2)}")
                # Clean up test record
                supabase.table('adminactivitylog').delete().eq('action_type', 'TEST_SCHEMA_CHECK').execute()
            
        return True
    except Exception as e:
        logger.error(f"Error checking table: {str(e)}")
        return False

def test_log_direct_insert():
    """Test direct insertion into adminactivitylog table"""
    logger.info("Testing direct insertion into adminactivitylog...")
    
    try:
        # Get client
        supabase = get_supabase_client()
        
        # Create test record
        test_record = {
            'admin_user_id': 'test_direct_insert',
            'action_type': 'TEST_DIRECT_INSERT',
            'target_entity_type': 'test',
            'target_entity_id': '1',
            'details_json': {'method': 'direct_insert', 'timestamp': time.time()}
        }
        
        # Insert directly
        response = supabase.table('adminactivitylog').insert(test_record).execute()
        
        if response.data:
            logger.info(f"Direct insert successful: {json.dumps(response.data[0], indent=2)}")
            return True
        else:
            logger.warning("Direct insert returned no data")
            return False
    except Exception as e:
        logger.error(f"Error with direct insert: {str(e)}")
        return False

def test_audit_service():
    """Test the audit_service.log_admin_action function"""
    logger.info("Testing audit_service.log_admin_action function...")
    
    try:
        # Use the log_admin_action function
        log_admin_action(
            admin_user_id='test_service_user',
            action_type='TEST_SERVICE_FUNCTION',
            target_entity_type='test',
            target_entity_id='2',
            details={'method': 'service_function', 'timestamp': time.time()}
        )
        
        # Verify the record was inserted
        time.sleep(1)  # Give a moment for the insert to complete
        
        supabase = get_supabase_client()
        response = supabase.table('adminactivitylog').select('*').eq('action_type', 'TEST_SERVICE_FUNCTION').execute()
        
        if response.data:
            logger.info(f"Service function test record found: {json.dumps(response.data[0], indent=2)}")
            return True
        else:
            logger.warning("Service function test record not found")
            return False
    except Exception as e:
        logger.error(f"Error with service function test: {str(e)}")
        return False

def cleanup_test_records():
    """Clean up test records"""
    logger.info("Cleaning up test records...")
    
    try:
        supabase = get_supabase_client()
        
        # Delete all test records
        supabase.table('adminactivitylog').delete().like('action_type', 'TEST_%').execute()
        logger.info("Test records cleaned up")
    except Exception as e:
        logger.error(f"Error cleaning up test records: {str(e)}")

def test_admin_route_equivalent():
    """Simulate what happens in the admin route but without FastAPI dependencies"""
    logger.info("Testing equivalent of admin route logic...")
    
    try:
        # This is similar to what happens in routes.py for make-admin
        log_admin_action(
            admin_user_id='test_admin_user',
            action_type='make_admin',
            target_entity_type='user',
            target_entity_id='test_target_user',
            details={
                'method': 'simulated_route',
                'timestamp': time.time(),
                'description': 'Simulating the admin promotion endpoint'
            }
        )
        
        # Verify the record was inserted
        time.sleep(1)  # Give a moment for the insert to complete
        
        supabase = get_supabase_client()
        response = supabase.table('adminactivitylog').select('*').eq('action_type', 'make_admin').execute()
        
        if response.data:
            logger.info(f"Admin route simulation record found: {json.dumps(response.data[0], indent=2)}")
            return True
        else:
            logger.warning("Admin route simulation record not found")
            return False
    except Exception as e:
        logger.error(f"Error with admin route simulation: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("=== Starting Admin Activity Logging Tests ===")
    
    # Run tests
    table_exists = test_table_existence()
    
    if not table_exists:
        logger.error("Cannot proceed with tests as the adminactivitylog table doesn't exist or is not accessible")
        sys.exit(1)
    
    direct_insert = test_log_direct_insert()
    service_test = test_audit_service()
    route_test = test_admin_route_equivalent()
    
    # Report results
    logger.info("=== Test Results ===")
    logger.info(f"Table Existence Test: {'PASSED' if table_exists else 'FAILED'}")
    logger.info(f"Direct Insert Test: {'PASSED' if direct_insert else 'FAILED'}")
    logger.info(f"Service Function Test: {'PASSED' if service_test else 'FAILED'}")
    logger.info(f"Admin Route Simulation Test: {'PASSED' if route_test else 'FAILED'}")
    
    # Clean up
    cleanup_test_records()
    
    # Final assessment
    if all([table_exists, direct_insert, service_test, route_test]):
        logger.info("All tests PASSED. Admin activity logging appears to be working correctly.")
    else:
        logger.error("Some tests FAILED. Admin activity logging has issues.")