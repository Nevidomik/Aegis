import httpx
import pytest
from backend_service.config import Settings
from backend_service.history_client import HistoryClient
from backend_service.main import (
    app,
    create_abuseipdb_http_client,
    create_history_http_client,
    lifespan,
)
from backend_service.provider import AbuseIPDBProvider


def settings() -> Settings:
    return Settings(
        abuseipdb_api_key="test-key",
        abuseipdb_connect_timeout_seconds=1,
        abuseipdb_read_timeout_seconds=2,
        abuseipdb_write_timeout_seconds=3,
        abuseipdb_pool_timeout_seconds=4,
    )


@pytest.mark.anyio
async def test_http_client_has_fixed_security_and_timeout_configuration() -> None:
    client = create_abuseipdb_http_client(settings())
    try:
        assert client.base_url == httpx.URL("https://api.abuseipdb.com")
        assert client.headers["Accept"] == "application/json"
        assert client.headers["Key"] == "test-key"
        assert client.timeout.connect == 1
        assert client.timeout.read == 2
        assert client.timeout.write == 3
        assert client.timeout.pool == 4
        assert client.follow_redirects is False
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_history_client_has_separate_base_url_and_timeout() -> None:
    client = create_history_http_client(settings())
    try:
        assert client.base_url == httpx.URL("http://127.0.0.1:8002")
        assert client.timeout.connect == 5
        assert client.follow_redirects is False
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_lifespan_reuses_one_client_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    abuseipdb_client = create_abuseipdb_http_client(settings())
    history_http_client = create_history_http_client(settings())
    monkeypatch.setattr("backend_service.main.get_settings", settings)
    monkeypatch.setattr(
        "backend_service.main.create_abuseipdb_http_client", lambda _: abuseipdb_client
    )
    monkeypatch.setattr(
        "backend_service.main.create_history_http_client", lambda _: history_http_client
    )

    async with lifespan(app):
        provider = app.state.reputation_provider
        history = app.state.history_client
        assert isinstance(provider, AbuseIPDBProvider)
        assert isinstance(history, HistoryClient)
        assert app.state.reputation_provider is provider
        assert app.state.history_client is history
        assert provider.client is abuseipdb_client
        assert history.client is history_http_client
        assert provider.client is not history.client
        assert abuseipdb_client.is_closed is False
        assert history_http_client.is_closed is False

    assert abuseipdb_client.is_closed is True
    assert history_http_client.is_closed is True
