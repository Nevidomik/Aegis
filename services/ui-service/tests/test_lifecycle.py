import httpx
import pytest
from ui_service.application_client import ApplicationClient
from ui_service.config import Settings
from ui_service.main import app, create_history_http_client, lifespan


def settings() -> Settings:
    return Settings(
        history_service_url="http://history.test",
        history_timeout_seconds=3,
    )


@pytest.mark.anyio
async def test_history_http_client_configuration() -> None:
    client = create_history_http_client(settings())
    try:
        assert client.base_url == httpx.URL("http://history.test")
        assert client.timeout.connect == 3
        assert client.follow_redirects is False
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_lifespan_reuses_one_application_client_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_client = create_history_http_client(settings())
    monkeypatch.setattr("ui_service.main.get_settings", settings)
    monkeypatch.setattr(
        "ui_service.main.create_history_http_client", lambda _: http_client
    )

    async with lifespan(app):
        first = app.state.application_client
        second = app.state.application_client
        assert isinstance(first, ApplicationClient)
        assert first is second
        assert first.client is http_client
        assert http_client.is_closed is False

    assert http_client.is_closed is True
