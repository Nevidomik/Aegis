"""Environment-backed Provider configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
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
    blacklist_polling_enabled: bool = False
    blacklist_poll_interval_seconds: int = Field(default=21600, ge=60)
    blacklist_confidence_minimum: int = Field(default=90, ge=0, le=100)
    blacklist_outbox_path: Path = Path("var/provider-blacklist-outbox.sqlite3")
    history_service_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8002")
    history_ingestion_token: SecretStr | None = Field(default=None, min_length=32)
    history_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    history_read_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    history_write_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    history_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    history_operation_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    history_delivery_retry_initial_seconds: int = Field(default=30, ge=1, le=3600)
    history_delivery_retry_maximum_seconds: int = Field(default=900, ge=1, le=21600)

    @field_validator("abuseipdb_base_url")
    @classmethod
    def require_https_abuseipdb_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("ABUSEIPDB_BASE_URL must use HTTPS.")
        return value

    @model_validator(mode="after")
    def validate_worker_configuration(self) -> Settings:
        if (
            self.history_delivery_retry_maximum_seconds
            < self.history_delivery_retry_initial_seconds
        ):
            raise ValueError(
                "History delivery retry maximum must not be below initial."
            )
        if self.blacklist_polling_enabled and self.history_ingestion_token is None:
            raise ValueError(
                "HISTORY_INGESTION_TOKEN is required when polling is enabled."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return process-wide Provider settings."""
    return Settings()
