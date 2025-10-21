"""
Supabase client for database operations.
Provides a singleton instance for accessing Supabase services.
"""
from supabase import create_client, Client
import logging
import socket
from urllib.parse import urlparse
import time
from app.config import settings

logger = logging.getLogger(__name__)

class SupabaseClientManager:
    """
    Manager for Supabase client with singleton pattern.
    """
    _instance = None

    def __init__(self):
        # First check DNS resolution to provide better error messages
        if settings.SUPABASE_URL:
            try:
                parsed_url = urlparse(settings.SUPABASE_URL)
                hostname = parsed_url.netloc
                
                # Try DNS resolution first to provide a better error message
                socket.gethostbyname(hostname)
            except socket.gaierror as dns_error:
                logger.error(f"DNS resolution failed for Supabase URL ({hostname}): {dns_error}")
                logger.error("Please check your internet connection and DNS settings")
                self.client = None
                self.enabled = False
                return
        
        # Proceed with client creation
        try:
            max_retries = 2
            retry_count = 0
            last_error = None
            
            # Try with retries to handle transient network issues
            while retry_count < max_retries:
                try:
                    self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
                    self.enabled = True
                    logger.info("Successfully initialized Supabase client")
                    return
                except Exception as retry_error:
                    last_error = retry_error
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"Supabase client creation failed (attempt {retry_count}), retrying...")
                        time.sleep(1)  # Short delay before retry
            
            # If we get here, all retries failed
            raise last_error
            
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            self.client = None
            self.enabled = False

    @classmethod
    def get_instance(cls) -> 'SupabaseClientManager':
        """Get the singleton instance of SupabaseClientManager"""
        if cls._instance is None:
            cls._instance = SupabaseClientManager()
        return cls._instance

    def get_client(self) -> Client:
        """Get the Supabase client instance"""
        if not self.enabled:
            raise ValueError("Supabase client is disabled due to configuration issues")
        if self.client is None:
            raise ValueError("Supabase client is not initialized or connection failed")
        return self.client

# Create a function to get the client, following the pattern used in app.api.deps
def get_supabase_client() -> Client:
    """
    Returns a Supabase client instance.
    Similar pattern to the BigQuery client in app.api.deps.
    
    Raises:
        ValueError: If the Supabase client is not available or not initialized
    """
    try:
        manager = SupabaseClientManager.get_instance()
        return manager.get_client()
    except ValueError as e:
        logger.error(f"Supabase client unavailable: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting Supabase client: {e}")
        raise ValueError(f"Failed to get Supabase client: {str(e)}")