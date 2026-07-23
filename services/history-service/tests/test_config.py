from history_service.config import SERVICE_ENV_FILE, Settings


def test_database_url_escapes_credentials_and_targets_mariadb() -> None:
    settings = Settings(
        _env_file=None,
        mariadb_database="aegis_history",
        mariadb_user="history@service",
        mariadb_password="secret:/value",
    )

    url = settings.database_url()

    assert url.drivername == "mariadb+pymysql"
    assert url.database == "aegis_history"
    assert url.render_as_string(hide_password=True).startswith(
        "mariadb+pymysql://history%40service:***@"
    )
    assert settings.mariadb_password.get_secret_value() == "secret:/value"
    assert "secret:/value" not in repr(settings)


def test_history_env_file_is_absolute_and_service_local() -> None:
    assert SERVICE_ENV_FILE.is_absolute()
    assert SERVICE_ENV_FILE == Settings.model_config["env_file"]
    assert SERVICE_ENV_FILE.parent.name == "history-service"


def test_provider_configuration_is_separate_from_database_credentials() -> None:
    settings = Settings(
        mariadb_database="aegis_history",
        mariadb_user="history",
        mariadb_password="secret",
        provider_service_url="http://provider.test",
        provider_connect_timeout_seconds=1,
        provider_read_timeout_seconds=2,
        provider_write_timeout_seconds=3,
        provider_pool_timeout_seconds=4,
    )

    assert str(settings.provider_service_url) == "http://provider.test/"
    assert settings.provider_connect_timeout_seconds == 1
    assert settings.provider_read_timeout_seconds == 2
    assert settings.provider_write_timeout_seconds == 3
    assert settings.provider_pool_timeout_seconds == 4


def test_history_keeps_only_read_side_blacklist_configuration() -> None:
    settings = Settings(
        _env_file=None,
        mariadb_database="aegis_history",
        mariadb_user="history",
        mariadb_password="secret",
    )

    assert settings.blacklist_stale_after_seconds == 43200
    assert not hasattr(settings, "blacklist_scheduler_enabled")
    assert not hasattr(settings, "blacklist_sync_interval_seconds")
    assert settings.provider_ingestion_token is None


def test_provider_ingestion_token_is_secret_and_bounded() -> None:
    token = "provider-ingestion-token-at-least-32-characters"
    settings = Settings(
        _env_file=None,
        mariadb_database="aegis_history",
        mariadb_user="history",
        mariadb_password="secret",
        provider_ingestion_token=token,
    )

    assert settings.provider_ingestion_token is not None
    assert settings.provider_ingestion_token.get_secret_value() == token
    assert token not in repr(settings)
