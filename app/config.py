from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Loads environment variables from the .env file.
    Ensures that the required variables are present.
    """
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_JWT_SECRET: str

    model_config = SettingsConfigDict(env_file=".env")

# Create a single, importable instance of the settings
settings = Settings()