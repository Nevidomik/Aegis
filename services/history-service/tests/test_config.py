from history_service.config import SERVICE_ENV_FILE, Settings


def test_database_url_escapes_credentials_and_targets_mariadb() -> None:
    settings = Settings(
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
        provider_timeout_seconds=3,
    )

    assert str(settings.provider_service_url) == "http://provider.test/"
    assert settings.provider_timeout_seconds == 3


def test_blacklist_sync_configuration_has_safe_bounded_defaults() -> None:
    settings = Settings(
        mariadb_database="aegis_history",
        mariadb_user="history",
        mariadb_password="secret",
    )

    assert settings.blacklist_confidence_minimum == 90
    assert settings.blacklist_scheduler_enabled is False
    assert settings.blacklist_sync_interval_seconds == 21600
    assert settings.blacklist_maximum_temporary_attempts == 4
    assert settings.blacklist_maximum_jitter_seconds == 30
