from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):

    # Database
    database_url: str

    # Anthropic / Voyage
    anthropic_api_key: str
    voyage_api_key: str

    # Retrieval
    top_k: int = 5
    embedding_dim: int = 1024

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False

@lru_cache
def get_settings() -> Settings:
    return Settings()

# Why lru cache? 
# Settings load from env vars and .env on first call
# we want to cache the results, otherwise every function that calls get_settings() will have to re-read the environment
# In FastAPI, this pairs with dependency injection

# Why Pydantic BaseSettings and not os.getenv()?
# BaseSettings gives you type validation at startup. if an API key is missing, the app crashes immediately with a clear error instead of failing silently mid-request.