"""
Service for fetching data pipeline run information from the Supabase database.
"""
import logging
from typing import Dict, Any, Optional
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

def get_latest_pipeline_run() -> Optional[Dict[str, Any]]:
    """
    Fetches the most recent entry from the 'pipelinerunlog' table.
    
    This function connects to Supabase and retrieves the complete record
    for the latest pipeline run.

    Returns:
        A dictionary containing all the details of the latest run, 
        or None if no runs are found in the log table.
    """
    try:
        # Get the Supabase client from our singleton manager
        supabase = get_supabase_client()
        
        # Build the query:
        # 1. Select all columns (*) to provide complete information.
        # 2. Order by the 'run_timestamp' in descending order to get the newest run first.
        # 3. Limit the result to just 1 record.
        response = supabase.table('pipelinerunlog').select('*').order('run_timestamp', desc=True).limit(1).execute()
        
        # If the query returned any data, return the first (and only) record.
        if response.data:
            return response.data[0]
        else:
            # If the log table is empty, return None.
            logger.info("No pipeline run logs found in the database.")
            return None

    except Exception as e:
        # If any error occurs (e.g., table not found, connection issue),
        # log the error and return None to prevent the API from crashing.
        logger.error(f"Error fetching latest pipeline run from Supabase: {e}")
        return None

