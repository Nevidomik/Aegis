from uuid import UUID

import pytest
from backend_service.exceptions import HistoryUnavailableError
from backend_service.history_client import get_history_client
from backend_service.schemas import CheckResponse, HistoryCheckCreate
from httpx2 import AsyncClient

from .conftest import FakeHistoryClient

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"


@pytest.mark.anyio
async def test_check_propagates_request_id_and_normalized_result(
    client: AsyncClient, history_client: FakeHistoryClient
) -> None:
    response = await client.post(
        "/api/v1/checks",
        json={
            "ip_address": "2606:4700:4700:0:0:0:0:1111",
            "max_age_days": 90,
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == REQUEST_ID
    assert response.json()["request_id"] == REQUEST_ID
    assert response.json()["ip_address"] == "2606:4700:4700::1111"
    assert response.json()["source"] == "FakeReputationProvider"
    assert history_client.request_id == REQUEST_ID
    assert history_client.payload is not None
    assert history_client.payload.ip_address == "2606:4700:4700::1111"


@pytest.mark.anyio
async def test_check_generates_request_id_when_absent(client: AsyncClient) -> None:
    response = await client.post("/api/v1/checks", json={"ip_address": "8.8.8.8"})

    assert response.status_code == 201
    generated = response.headers["X-Request-ID"]
    assert UUID(generated)
    assert response.json()["request_id"] == generated
    assert response.json()["max_age_days"] == 30


@pytest.mark.parametrize(
    ("ip_value", "code"),
    [
        ("not-an-ip", "INVALID_IP_ADDRESS"),
        ("192.168.1.1", "NON_PUBLIC_IP_ADDRESS"),
        ("::1", "NON_PUBLIC_IP_ADDRESS"),
    ],
)
@pytest.mark.anyio
async def test_invalid_ip_returns_application_error_without_persistence(
    client: AsyncClient,
    history_client: FakeHistoryClient,
    ip_value: str,
    code: str,
) -> None:
    response = await client.post(
        "/api/v1/checks",
        json={"ip_address": ip_value},
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == REQUEST_ID
    assert history_client.calls == 0


@pytest.mark.anyio
async def test_invalid_request_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/checks",
        json={"ip_address": "8.8.8.8"},
        headers={"X-Request-ID": "not-a-uuid"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST_ID"
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


@pytest.mark.anyio
async def test_invalid_schema_uses_stable_error(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/checks",
        json={"ip_address": "8.8.8.8", "max_age_days": 366},
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["error"]["request_id"] == REQUEST_ID


@pytest.mark.anyio
async def test_history_failure_becomes_safe_503(
    client: AsyncClient, override_dependency: object
) -> None:
    class UnavailableHistoryClient:
        async def save(
            self, payload: HistoryCheckCreate, *, request_id: str
        ) -> CheckResponse:
            raise HistoryUnavailableError

    override_dependency(get_history_client, UnavailableHistoryClient())  # type: ignore[operator]
    response = await client.post(
        "/api/v1/checks",
        json={"ip_address": "8.8.8.8"},
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "HISTORY_UNAVAILABLE",
            "message": "History storage is temporarily unavailable.",
            "request_id": REQUEST_ID,
        }
    }
