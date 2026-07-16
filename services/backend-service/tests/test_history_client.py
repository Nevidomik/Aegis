from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from backend_service.config import Settings
from backend_service.exceptions import (
    HistoryInvalidResponseError,
    HistoryRecordNotFoundError,
    HistoryUnavailableError,
)
from backend_service.history_client import HistoryClient
from backend_service.schemas import HistoryCheckCreate

REQUEST_ID = UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd")


def history_payload() -> HistoryCheckCreate:
    return HistoryCheckCreate(
        request_id=REQUEST_ID,
        ip_address="8.8.8.8",
        ip_version=4,
        is_public=True,
        is_whitelisted=False,
        abuse_confidence_score=10,
        country_code="ZZ",
        usage_type="Fake development data",
        isp="Aegis Fake Provider",
        domain=None,
        total_reports=2,
        num_distinct_users=1,
        last_reported_at=None,
        source="FakeReputationProvider",
        max_age_days=30,
        checked_at=datetime(2026, 7, 15, 18, 30, tzinfo=UTC),
    )


class FakeResponse:
    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.body = body

    def json(self) -> object:
        return self.body


class FakeAsyncClient:
    def __init__(self, response: FakeResponse | Exception, **_: Any) -> None:
        self.response = response
        self.headers: dict[str, str] | None = None
        self.json_body: object = None
        self.method: str | None = None
        self.path: str | None = None
        self.params: dict[str, str | int] | None = None

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None,
        json: object | None,
        headers: dict[str, str],
    ) -> FakeResponse:
        self.method = method
        self.path = path
        self.params = params
        self.headers = headers
        self.json_body = json
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def history_client() -> HistoryClient:
    return HistoryClient(
        Settings(
            history_service_url="http://history.test",
            history_timeout_seconds=2,
            abuseipdb_api_key="test-key",
        )
    )


@pytest.mark.anyio
async def test_save_forwards_request_id_and_validates_response(
    monkeypatch: Any,
) -> None:
    payload = history_payload()
    response_body = {"history_id": 145, **payload.model_dump(mode="json")}
    fake_client = FakeAsyncClient(FakeResponse(201, response_body))
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    saved = await history_client().save(payload, request_id=str(REQUEST_ID))

    assert saved.history_id == 145
    assert fake_client.headers == {"X-Request-ID": str(REQUEST_ID)}
    assert fake_client.json_body == payload.model_dump(mode="json")
    assert fake_client.method == "POST"
    assert fake_client.path == "/internal/v1/checks"


@pytest.mark.anyio
async def test_save_maps_timeout_to_history_unavailable(monkeypatch: Any) -> None:
    request = httpx.Request("POST", "http://history.test/internal/v1/checks")
    fake_client = FakeAsyncClient(httpx.ReadTimeout("timeout", request=request))
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    with pytest.raises(HistoryUnavailableError):
        await history_client().save(history_payload(), request_id=str(REQUEST_ID))


@pytest.mark.anyio
async def test_save_rejects_invalid_history_response(monkeypatch: Any) -> None:
    fake_client = FakeAsyncClient(FakeResponse(201, {"unexpected": "body"}))
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    with pytest.raises(HistoryInvalidResponseError):
        await history_client().save(history_payload(), request_id=str(REQUEST_ID))


@pytest.mark.anyio
async def test_list_forwards_query_and_validates_page(monkeypatch: Any) -> None:
    payload = history_payload()
    record = {"history_id": 145, **payload.model_dump(mode="json")}
    fake_client = FakeAsyncClient(
        FakeResponse(
            200,
            {"items": [record], "limit": 10, "offset": 2, "total": 1},
        )
    )
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    page = await history_client().list(
        limit=10,
        offset=2,
        ip_address="8.8.8.8",
        request_id=str(REQUEST_ID),
    )

    assert page.total == 1
    assert page.items[0].history_id == 145
    assert fake_client.method == "GET"
    assert fake_client.path == "/internal/v1/checks"
    assert fake_client.params == {
        "limit": 10,
        "offset": 2,
        "ip_address": "8.8.8.8",
    }
    assert fake_client.headers == {"X-Request-ID": str(REQUEST_ID)}


@pytest.mark.anyio
async def test_get_forwards_id_and_validates_record(monkeypatch: Any) -> None:
    payload = history_payload()
    record = {"history_id": 145, **payload.model_dump(mode="json")}
    fake_client = FakeAsyncClient(FakeResponse(200, record))
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    saved = await history_client().get(145, request_id=str(REQUEST_ID))

    assert saved.history_id == 145
    assert fake_client.method == "GET"
    assert fake_client.path == "/internal/v1/checks/145"
    assert fake_client.params is None
    assert fake_client.headers == {"X-Request-ID": str(REQUEST_ID)}


@pytest.mark.anyio
async def test_get_maps_history_not_found(monkeypatch: Any) -> None:
    fake_client = FakeAsyncClient(FakeResponse(404, {"error": {}}))
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    with pytest.raises(HistoryRecordNotFoundError):
        await history_client().get(999, request_id=str(REQUEST_ID))


@pytest.mark.anyio
async def test_list_maps_5xx_to_unavailable(monkeypatch: Any) -> None:
    fake_client = FakeAsyncClient(FakeResponse(503, {"error": {}}))
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    with pytest.raises(HistoryUnavailableError):
        await history_client().list(
            limit=20,
            offset=0,
            ip_address=None,
            request_id=str(REQUEST_ID),
        )


@pytest.mark.anyio
async def test_list_rejects_malformed_history_page(monkeypatch: Any) -> None:
    fake_client = FakeAsyncClient(FakeResponse(200, {"items": "invalid"}))
    monkeypatch.setattr(
        "backend_service.history_client.httpx.AsyncClient", lambda **_: fake_client
    )

    with pytest.raises(HistoryInvalidResponseError):
        await history_client().list(
            limit=20,
            offset=0,
            ip_address=None,
            request_id=str(REQUEST_ID),
        )
