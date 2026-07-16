import pytest
from backend_service.config import SERVICE_ENV_FILE, Settings
from pydantic import ValidationError


def test_api_key_is_required_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABUSEIPDB_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("ABUSEIPDB_API_KEY", "environment-secret")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.abuseipdb_api_key.get_secret_value() == "environment-secret"
    assert "environment-secret" not in repr(settings)


def test_abuseipdb_base_url_must_use_https() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            _env_file=None,
            abuseipdb_api_key="test-key",
            abuseipdb_base_url="http://api.abuseipdb.test",
        )


def test_backend_env_file_is_absolute_and_service_local() -> None:
    assert SERVICE_ENV_FILE.is_absolute()
    assert SERVICE_ENV_FILE == Settings.model_config["env_file"]
    assert SERVICE_ENV_FILE.parent.name == "backend-service"
