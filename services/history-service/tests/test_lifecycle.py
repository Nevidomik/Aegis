import httpx
import pytest
from history_service.config import Settings
from history_service.main import app, create_backend_http_client, lifespan


def settings() -> Settings:
    return Settings(
        mariadb_database="aegis_history",
        mariadb_user="history",
        mariadb_password="secret",
        backend_service_url="http://backend.test",
        backend_timeout_seconds=3,
    )


def test_backend_http_client_has_fixed_base_url_and_timeout() -> None:
    client = create_backend_http_client(settings())
    try:
        assert client.base_url == httpx.URL("http://backend.test")
        assert client.timeout.connect == 3
        assert client.follow_redirects is False
    finally:
        client.close()


@pytest.mark.anyio
async def test_lifespan_reuses_and_closes_backend_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_client = create_backend_http_client(settings())
    monkeypatch.setattr("history_service.main.get_settings", settings)
    monkeypatch.setattr(
        "history_service.main.create_backend_http_client", lambda _: http_client
    )

    async with lifespan(app):
        first = app.state.backend_client
        assert app.state.backend_client is first
        assert first.client is http_client
        assert http_client.is_closed is False

    assert http_client.is_closed is True
