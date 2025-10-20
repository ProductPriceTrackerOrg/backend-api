"""
Script to test the admin promotion endpoint
"""

import os
import sys
import requests
import logging
import uuid
import json
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("endpoint-test")

# Add the parent directory to sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Load environment variables
load_dotenv()

# Import after env vars are loaded
from app.db.supabase_client import get_supabase_client

def test_make_admin_endpoint(api_url, test_user_id):
    """Test the make-admin endpoint"""
    
    # Endpoint URL
    endpoint = f"{api_url}/api/v1/admin/users/{test_user_id}/make-admin"
    
    # Add some basic authorization headers (this would be your real auth in production)
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer fake_token_for_testing"
    }
    
    logger.info(f"Testing endpoint: POST {endpoint}")
    
    try:
        # Make the request
        response = requests.post(endpoint, headers=headers)
        
        # Log the response
        logger.info(f"Response status code: {response.status_code}")
        
        try:
            response_data = response.json()
            logger.info(f"Response data: {json.dumps(response_data, indent=2)}")
        except:
            logger.info(f"Response text: {response.text}")
        
        # Check if successful
        if response.status_code == 200:
            logger.info("✅ Endpoint call was successful")
            return True
        else:
            logger.error(f"❌ Endpoint call failed with status {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error calling endpoint: {e}")
        return False

def verify_audit_log(test_user_id):
    """Verify that the admin action was logged"""
    try:
        supabase = get_supabase_client()
        
        # Look for the most recent PROMOTE_USER_TO_ADMIN action for this user
        response = supabase.table('adminactivitylog') \
            .select('*') \
            .eq('action_type', 'PROMOTE_USER_TO_ADMIN') \
            .eq('target_entity_id', test_user_id) \
            .order('activity_timestamp', desc=True) \
            .limit(1) \
            .execute()
            
        if response.data:
            log_entry = response.data[0]
            logger.info(f"✅ Found audit log entry: {log_entry}")
            return True
        else:
            logger.error(f"❌ No audit log entry found for promoting user {test_user_id} to admin")
            return False
    except Exception as e:
        logger.error(f"Error checking audit log: {e}")
        return False

def create_test_user():
    """Create a test user in the profiles table"""
    try:
        supabase = get_supabase_client()
        
        # Generate a random UUID for the test user
        test_user_id = str(uuid.uuid4())
        
        # Create a profile for this test user
        profile_data = {
            'user_id': test_user_id,
            'email': f"testuser_{test_user_id[:8]}@example.com",
            'full_name': 'Test User',
            'is_active': True
        }
        
        logger.info(f"Creating test user: {profile_data}")
        
        # Insert the test user
        response = supabase.table('profiles').insert(profile_data).execute()
        
        if response.data:
            logger.info(f"✅ Created test user: {response.data[0]}")
            return test_user_id
        else:
            logger.error("❌ Failed to create test user")
            return None
    except Exception as e:
        logger.error(f"Error creating test user: {e}")
        return None

if __name__ == "__main__":
    logger.info("=== Admin Promotion Endpoint Test ===")
    
    # API base URL - change if your API is running on a different host/port
    api_url = "http://localhost:8000"
    
    # Option 1: Create a new test user
    create_new_user = input("Create a new test user? (y/n): ").lower() == 'y'
    
    if create_new_user:
        test_user_id = create_test_user()
        if not test_user_id:
            logger.error("Aborting test as test user creation failed")
            sys.exit(1)
    else:
        # Option 2: Use an existing user ID
        test_user_id = input("Enter user ID to promote to admin: ")
    
    # Test the endpoint
    logger.info(f"Testing promotion of user {test_user_id} to admin role")
    endpoint_success = test_make_admin_endpoint(api_url, test_user_id)
    
    # If the endpoint call was successful, check the audit log
    if endpoint_success:
        logger.info("Checking audit log for admin promotion record...")
        log_success = verify_audit_log(test_user_id)
        
        if log_success:
            logger.info("✅✅ TEST PASSED: Admin promotion was logged successfully")
        else:
            logger.error("❌❌ TEST FAILED: Admin promotion was not logged")
    else:
        logger.error("❌ Endpoint test failed, skipping audit log check")