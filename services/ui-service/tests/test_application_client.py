from datetime import UTC, datetime

import httpx
import pytest
from ui_service.application_client import ApplicationClient, ApplicationClientError
from ui_service.schemas import BlacklistPage, BlacklistStatus, CheckResult

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"


def valid_result() -> dict[str, object]:
    return CheckResult(
        request_id=REQUEST_ID,
        history_id=145,
        ip_address="8.8.8.8",
        ip_version=4,
        is_public=True,
        is_whitelisted=None,
        abuse_confidence_score=12,
        country_code="US",
        usage_type=None,
        isp="Example ISP",
        domain=None,
        total_reports=7,
        num_distinct_users=3,
        last_reported_at=None,
        max_age_days=30,
        source="AbuseIPDB",
        checked_at=datetime(2026, 7, 15, 18, 30, tzinfo=UTC),
    ).model_dump(mode="json")


@pytest.mark.anyio
async def test_client_calls_only_history_application_endpoints() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/api/v1/checks":
            body: object = {
                "items": [valid_result()],
                "limit": 20,
                "offset": 0,
                "total": 1,
            }
        else:
            body = valid_result()
        return httpx.Response(
            200,
            json=body,
            headers={"X-Request-ID": REQUEST_ID},
        )

    async with httpx.AsyncClient(
        base_url="http://history.test", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = ApplicationClient(http_client)
        created = await client.check(
            ip_address="8.8.8.8", max_age_days=30, request_id=REQUEST_ID
        )
        history = await client.recent_history(request_id=REQUEST_ID)
        record = await client.history_record(145, request_id=REQUEST_ID)

    assert created.history_id == 145
    assert history.total == 1
    assert record.history_id == 145
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/api/v1/checks"),
        ("GET", "/api/v1/checks"),
        ("GET", "/api/v1/checks/145"),
    ]
    assert all(request.headers["X-Request-ID"] == REQUEST_ID for request in requests)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ip_version", 6),
        ("ip_address", "192.168.1.1"),
        ("total_reports", "7"),
        ("checked_at", "2026-07-15T18:30:00"),
        ("isp", "x" * 256),
    ],
)
def test_application_response_rejects_invalid_dependency_fields(
    field: str, value: object
) -> None:
    body = valid_result()
    body[field] = value
    response = httpx.Response(
        200,
        json=body,
        headers={"X-Request-ID": REQUEST_ID},
    )

    with pytest.raises(ApplicationClientError, match="invalid response"):
        ApplicationClient._validated_response(
            response, CheckResult, request_id=REQUEST_ID
        )


def test_application_error_rejects_mismatched_request_id() -> None:
    response = httpx.Response(
        503,
        json={
            "error": {
                "code": "BACKEND_UNAVAILABLE",
                "message": "Please try again.",
                "request_id": "00000000-0000-0000-0000-000000000000",
            }
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    with pytest.raises(ApplicationClientError, match="invalid response"):
        ApplicationClient._validated_response(
            response, CheckResult, request_id=REQUEST_ID
        )


@pytest.mark.anyio
async def test_client_calls_history_blacklist_endpoints() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/status"):
            body: object = {
                "state": "ready",
                "sync_in_progress": False,
                "latest_snapshot_id": 42,
                "latest_provider_generated_at": "2026-07-22T12:00:00Z",
                "latest_fetched_at": "2026-07-22T12:00:02Z",
                "last_attempt_at": "2026-07-22T12:00:00Z",
                "last_success_at": "2026-07-22T12:00:04Z",
                "next_attempt_at": "2026-07-22T18:00:04Z",
                "rate_limit_limit": 5,
                "rate_limit_remaining": 4,
                "rate_limit_reset_at": "2026-07-23T00:00:00Z",
                "data_stale": False,
                "last_error": None,
            }
        else:
            body = {
                "snapshot": {
                    "snapshot_id": 42,
                    "provider": "AbuseIPDB",
                    "provider_generated_at": "2026-07-22T12:00:00Z",
                    "fetched_at": "2026-07-22T12:00:02Z",
                    "confidence_minimum": 90,
                    "requested_limit": 1000,
                    "returned_count": 1,
                },
                "items": [
                    {
                        "ip_address": "2606:4700:4700::1111",
                        "ip_version": 6,
                        "abuse_confidence_score": 95,
                        "country_code": None,
                        "last_reported_at": None,
                    }
                ],
                "limit": 100,
                "offset": 100,
                "total": 201,
            }
        return httpx.Response(200, json=body, headers={"X-Request-ID": REQUEST_ID})

    async with httpx.AsyncClient(
        base_url="http://history.test", transport=httpx.MockTransport(handler)
    ) as http_client:
        client = ApplicationClient(http_client)
        status = await client.blacklist_status(request_id=REQUEST_ID)
        page = await client.blacklist(limit=100, offset=100, request_id=REQUEST_ID)

    assert isinstance(status, BlacklistStatus)
    assert isinstance(page, BlacklistPage)
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/v1/blacklist/status"),
        ("GET", "/api/v1/blacklist"),
    ]
    assert dict(requests[1].url.params) == {"limit": "100", "offset": "100"}
    assert all(request.headers["X-Request-ID"] == REQUEST_ID for request in requests)
