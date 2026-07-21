"""Environment-backed UI configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """UI dependency settings."""

    model_config = SettingsConfigDict(
        env_file=SERVICE_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    history_service_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8002")
    history_timeout_seconds: float = Field(default=5.0, gt=0, le=60)


@lru_cache
def get_settings() -> Settings:
    """Return process-wide UI settings."""
    return Settings()
