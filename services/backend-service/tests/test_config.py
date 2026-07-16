import pytest
from backend_service.config import Settings
from pydantic import ValidationError


def test_api_key_is_required_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABUSEIPDB_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings()

    monkeypatch.setenv("ABUSEIPDB_API_KEY", "environment-secret")
    settings = Settings()

    assert settings.abuseipdb_api_key.get_secret_value() == "environment-secret"
    assert "environment-secret" not in repr(settings)


def test_abuseipdb_base_url_must_use_https() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            abuseipdb_api_key="test-key",
            abuseipdb_base_url="http://api.abuseipdb.test",
        )
