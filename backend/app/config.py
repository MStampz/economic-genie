"""Settings, read from environment variables (or a .env file next to docker-compose.yml)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GENIE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://genie:genie@localhost:5432/genie"

    # Sessions
    session_cookie_name: str = "genie_session"
    session_days: int = 14
    # Set to true when served over HTTPS (hosted). Local http://localhost needs false.
    cookie_secure: bool = False

    # Login protection: lock an email after this many failed attempts within the window.
    login_max_failures: int = 8
    login_window_minutes: int = 15

    invite_valid_days: int = 7

    # Hidden features. The data model is prepared for the AI coach; its API stays off until it ships.
    feature_coach: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
