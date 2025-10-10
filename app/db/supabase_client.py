"""
Supabase client for database operations.
Provides a singleton instance for accessing Supabase services.
"""
from supabase import create_client, Client
import logging
from app.config import settings

logger = logging.getLogger(__name__)

class SupabaseClientManager:
    """
    Manager for Supabase client with singleton pattern.
    """
    _instance = None

    def __init__(self):
        try:
            self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            self.enabled = True
            logger.info("Successfully initialized Supabase client")
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
        if not self.enabled or self.client is None:
            raise ValueError("Supabase client is not available")
        return self.client

# Create a function to get the client, following the pattern used in app.api.deps
def get_supabase_client() -> Client:
    """
    Returns a Supabase client instance.
    Similar pattern to the BigQuery client in app.api.deps.
    """
    manager = SupabaseClientManager.get_instance()
    return manager.get_client()