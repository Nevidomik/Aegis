from ui_service.config import SERVICE_ENV_FILE, Settings


def test_ui_env_file_is_absolute_and_service_local() -> None:
    assert SERVICE_ENV_FILE.is_absolute()
    assert SERVICE_ENV_FILE == Settings.model_config["env_file"]
    assert SERVICE_ENV_FILE.parent.name == "ui-service"


def test_ui_targets_history_service() -> None:
    settings = Settings(
        history_service_url="http://history.test", history_timeout_seconds=3
    )

    assert str(settings.history_service_url) == "http://history.test/"
    assert settings.history_timeout_seconds == 3
