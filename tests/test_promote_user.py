"""
Test script for the promote_user_to_admin function.
This isolates the function to diagnose any issues.
"""
import logging
import os
import sys
import time
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Add the parent directory to sys.path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables from .env file
load_dotenv()

# Now import the required modules
from app.services.admin_service import promote_user_to_admin
from app.db.supabase_client import get_supabase_client

def test_supabase_connection():
    """Test basic Supabase connection"""
    logger.info("Testing Supabase connection...")
    
    try:
        supabase = get_supabase_client()
        logger.info("Successfully got Supabase client")
        
        # Test a simple query
        start_time = time.time()
        response = supabase.from_("roles").select("*").limit(1).execute()
        elapsed = time.time() - start_time
        
        logger.info(f"Connection successful! Query took {elapsed:.2f} seconds")
        logger.info(f"Retrieved data: {response.data}")
        return True
    except Exception as e:
        logger.error(f"Supabase connection failed: {e}")
        return False

def test_promote_user():
    """Test the promote_user_to_admin function"""
    # Use a test user ID - replace with a valid UUID from your database
    test_user_id = "0408ca8f-c3f6-4edd-adf5-9630eb992726"  # The same user ID from your error
    
    logger.info(f"Testing promote_user_to_admin for user ID: {test_user_id}")
    
    # Call the function
    result = promote_user_to_admin(user_id=test_user_id)
    
    # Log the result
    if "error" in result:
        logger.error(f"Error promoting user: {result['error']}")
    else:
        logger.info(f"Result: {result}")
    
    return result

if __name__ == "__main__":
    # First, test the basic Supabase connection
    connection_ok = test_supabase_connection()
    
    if connection_ok:
        logger.info("\n--- Testing promote_user_to_admin function ---")
        test_promote_user()
    else:
        logger.error("Skipping promote_user test due to connection failure")