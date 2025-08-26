from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Loads environment variables from the .env file.
    Ensures that the required variables are present.
    """
    # Supabase settings
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_JWT_SECRET: str
    
    # GCP settings
    GCP_PROJECT_ID: str
    BIGQUERY_DATASET_ID: str
    DATA_SOURCE: str = "bigquery"  # Default value

    model_config = SettingsConfigDict(env_file=".env")

# Create a single, importable instance of the settings
settings = Settings()