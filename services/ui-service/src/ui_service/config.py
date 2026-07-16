"""Environment-backed UI configuration."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """UI dependency settings."""

    model_config = SettingsConfigDict(extra="ignore")

    backend_service_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8001")
    backend_timeout_seconds: float = Field(default=5.0, gt=0, le=60)


@lru_cache
def get_settings() -> Settings:
    """Return process-wide UI settings."""
    return Settings()
