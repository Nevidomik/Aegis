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
