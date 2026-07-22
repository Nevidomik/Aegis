"""Environment-backed configuration for the History service."""

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

SERVICE_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """MariaDB connection settings."""

    model_config = SettingsConfigDict(
        env_file=SERVICE_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mariadb_host: str = "127.0.0.1"
    mariadb_port: int = Field(default=3306, ge=1, le=65535)
    mariadb_database: str
    mariadb_user: str
    mariadb_password: SecretStr
    provider_service_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8001")
    provider_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    def database_url(self) -> URL:
        """Build a safely escaped MariaDB connection URL."""
        return URL.create(
            drivername="mariadb+pymysql",
            username=self.mariadb_user,
            password=self.mariadb_password.get_secret_value(),
            host=self.mariadb_host,
            port=self.mariadb_port,
            database=self.mariadb_database,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()  # type: ignore[call-arg]
