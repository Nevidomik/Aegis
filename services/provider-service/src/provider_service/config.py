"""Environment-backed Provider configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Provider dependency settings."""

    model_config = SettingsConfigDict(
        env_file=SERVICE_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    abuseipdb_base_url: AnyHttpUrl = AnyHttpUrl("https://api.abuseipdb.com")
    abuseipdb_api_key: SecretStr = Field(min_length=1)
    abuseipdb_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    abuseipdb_read_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    abuseipdb_write_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    abuseipdb_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    abuseipdb_operation_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    @field_validator("abuseipdb_base_url")
    @classmethod
    def require_https_abuseipdb_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("ABUSEIPDB_BASE_URL must use HTTPS.")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return process-wide Provider settings."""
    return Settings()
