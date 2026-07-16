"""Environment-backed Backend configuration."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend dependency settings."""

    model_config = SettingsConfigDict(extra="ignore")

    history_service_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8002")
    history_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    abuseipdb_base_url: AnyHttpUrl = AnyHttpUrl("https://api.abuseipdb.com")
    abuseipdb_api_key: SecretStr = Field(min_length=1)
    abuseipdb_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    abuseipdb_read_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    abuseipdb_write_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    abuseipdb_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @field_validator("abuseipdb_base_url")
    @classmethod
    def require_https_abuseipdb_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("ABUSEIPDB_BASE_URL must use HTTPS.")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return process-wide Backend settings."""
    return Settings()
