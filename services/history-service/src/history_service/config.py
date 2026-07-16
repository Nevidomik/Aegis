"""Environment-backed configuration for the History service."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """MariaDB connection settings."""

    model_config = SettingsConfigDict(extra="ignore")

    mariadb_host: str = "127.0.0.1"
    mariadb_port: int = Field(default=3306, ge=1, le=65535)
    mariadb_database: str
    mariadb_user: str
    mariadb_password: str

    def database_url(self) -> URL:
        """Build a safely escaped MariaDB connection URL."""
        return URL.create(
            drivername="mariadb+pymysql",
            username=self.mariadb_user,
            password=self.mariadb_password,
            host=self.mariadb_host,
            port=self.mariadb_port,
            database=self.mariadb_database,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()  # type: ignore[call-arg]
