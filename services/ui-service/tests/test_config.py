from ui_service.config import SERVICE_ENV_FILE, Settings


def test_ui_env_file_is_absolute_and_service_local() -> None:
    assert SERVICE_ENV_FILE.is_absolute()
    assert SERVICE_ENV_FILE == Settings.model_config["env_file"]
    assert SERVICE_ENV_FILE.parent.name == "ui-service"


def test_ui_targets_history_service() -> None:
    settings = Settings(
        history_service_url="http://history.test",
        history_connect_timeout_seconds=1,
        history_read_timeout_seconds=2,
        history_write_timeout_seconds=3,
        history_pool_timeout_seconds=4,
        history_operation_timeout_seconds=5,
    )

    assert str(settings.history_service_url) == "http://history.test/"
    assert settings.history_connect_timeout_seconds == 1
    assert settings.history_read_timeout_seconds == 2
    assert settings.history_write_timeout_seconds == 3
    assert settings.history_pool_timeout_seconds == 4
    assert settings.history_operation_timeout_seconds == 5
