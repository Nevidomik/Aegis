from uuid import UUID

import pytest
from backend_service.exceptions import (
    AbuseIPDBAuthenticationError,
    AbuseIPDBUnavailableError,
    RateLimitExceededError,
    UpstreamInvalidResponseError,
    UpstreamRequestRejectedError,
    UpstreamTimeoutError,
)
from backend_service.provider import get_reputation_provider
from httpx2 import AsyncClient

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"


@pytest.mark.anyio
async def test_health_endpoints_are_local_and_preserve_request_id(
    client: AsyncClient,
) -> None:
    live = await client.get("/health/live", headers={"X-Request-ID": REQUEST_ID})
    ready = await client.get("/health/ready", headers={"X-Request-ID": REQUEST_ID})

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert live.headers["X-Request-ID"] == REQUEST_ID
    assert ready.headers["X-Request-ID"] == REQUEST_ID


@pytest.mark.anyio
async def test_internal_reputation_check_returns_strict_normalized_contract(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/internal/v1/reputation-checks",
        json={"ip_address": "2606:4700:4700::1111", "max_age_days": 90},
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == REQUEST_ID
    assert response.json()["ip_address"] == "2606:4700:4700::1111"
    assert response.json()["max_age_days"] == 90
    assert "checked_at" in response.json()
    assert "request_id" not in response.json()
    assert "history_id" not in response.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"ip_address": "2606:4700:4700:0:0:0:0:1111", "max_age_days": 90},
        {"ip_address": "127.0.0.1", "max_age_days": 90},
        {"ip_address": "8.8.8.8", "max_age_days": 0},
        {"ip_address": "8.8.8.8", "max_age_days": 90, "extra": True},
    ],
)
@pytest.mark.anyio
async def test_internal_reputation_check_rejects_invalid_contract(
    client: AsyncClient, payload: dict[str, object]
) -> None:
    response = await client.post(
        "/internal/v1/reputation-checks",
        json=payload,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "INVALID_REQUEST",
        "message": "The request did not satisfy the API contract.",
        "request_id": REQUEST_ID,
    }


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (RateLimitExceededError(), 429, "RATE_LIMIT_EXCEEDED"),
        (UpstreamInvalidResponseError(), 502, "UPSTREAM_INVALID_RESPONSE"),
        (UpstreamRequestRejectedError(), 502, "UPSTREAM_REQUEST_REJECTED"),
        (
            AbuseIPDBAuthenticationError(),
            503,
            "ABUSEIPDB_AUTHENTICATION_FAILED",
        ),
        (AbuseIPDBUnavailableError(), 503, "ABUSEIPDB_UNAVAILABLE"),
        (UpstreamTimeoutError(), 504, "UPSTREAM_TIMEOUT"),
    ],
)
@pytest.mark.anyio
async def test_internal_reputation_check_preserves_upstream_errors_and_request_id(
    client: AsyncClient,
    override_dependency: object,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    class FailingProvider:
        async def lookup(self, *_: object) -> object:
            raise error

    override_dependency(get_reputation_provider, FailingProvider())  # type: ignore[operator]
    response = await client.post(
        "/internal/v1/reputation-checks",
        json={"ip_address": "8.8.8.8", "max_age_days": 30},
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == status_code
    assert response.headers["X-Request-ID"] == REQUEST_ID
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == REQUEST_ID


@pytest.mark.anyio
async def test_request_id_middleware_generates_and_rejects_ids(
    client: AsyncClient,
) -> None:
    generated = await client.get("/health/live")
    invalid = await client.get("/health/live", headers={"X-Request-ID": "not-a-uuid"})

    assert generated.status_code == 200
    assert UUID(generated.headers["X-Request-ID"])
    assert invalid.status_code == 400
    assert UUID(invalid.headers["X-Request-ID"])
    assert invalid.headers["X-Request-ID"] == invalid.json()["error"]["request_id"]


@pytest.mark.anyio
async def test_public_application_routes_are_not_exposed(client: AsyncClient) -> None:
    create = await client.post("/api/v1/checks", json={"ip_address": "8.8.8.8"})
    listing = await client.get("/api/v1/checks")
    record = await client.get("/api/v1/checks/145")

    assert create.status_code == 404
    assert listing.status_code == 404
    assert record.status_code == 404
