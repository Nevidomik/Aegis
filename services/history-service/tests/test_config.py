from history_service.config import Settings


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
