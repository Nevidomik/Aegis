import httpx
import pytest
from history_service.config import Settings
from history_service.main import app, create_provider_http_client, lifespan


def settings() -> Settings:
    return Settings(
        mariadb_database="aegis_history",
        mariadb_user="history",
        mariadb_password="secret",
        provider_service_url="http://provider.test",
        provider_timeout_seconds=3,
    )


def test_provider_http_client_has_fixed_base_url_and_timeout() -> None:
    client = create_provider_http_client(settings())
    try:
        assert client.base_url == httpx.URL("http://provider.test")
        assert client.timeout.connect == 3
        assert client.follow_redirects is False
    finally:
        client.close()


@pytest.mark.anyio
async def test_lifespan_reuses_and_closes_provider_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_client = create_provider_http_client(settings())
    monkeypatch.setattr("history_service.main.get_settings", settings)
    monkeypatch.setattr(
        "history_service.main.create_provider_http_client", lambda _: http_client
    )

    async with lifespan(app):
        first = app.state.provider_client
        assert app.state.provider_client is first
        assert first.client is http_client
        assert http_client.is_closed is False

    assert http_client.is_closed is True
