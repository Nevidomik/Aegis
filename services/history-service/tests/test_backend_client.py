from datetime import UTC, datetime

import httpx
import pytest
from history_service.backend_client import BackendClient
from history_service.exceptions import (
    BackendInvalidResponseError,
    BackendUnavailableError,
)
from history_service.schemas import BackendReputationRequest

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"


def valid_response() -> dict[str, object]:
    return {
        "ip_address": "8.8.8.8",
        "ip_version": 4,
        "is_public": True,
        "is_whitelisted": None,
        "abuse_confidence_score": 12,
        "country_code": "US",
        "usage_type": None,
        "isp": "Example ISP",
        "domain": None,
        "total_reports": 7,
        "num_distinct_users": 3,
        "last_reported_at": None,
        "max_age_days": 90,
        "source": "AbuseIPDB",
        "checked_at": datetime(2026, 7, 15, 18, 30, tzinfo=UTC).isoformat(),
    }


def test_check_calls_only_internal_proxy_and_validates_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/internal/v1/reputation-checks"
        assert request.headers["X-Request-ID"] == REQUEST_ID
        assert request.read() == b'{"ip_address":"8.8.8.8","max_age_days":90}'
        return httpx.Response(
            200,
            json=valid_response(),
            headers={"X-Request-ID": REQUEST_ID},
        )

    with httpx.Client(
        base_url="http://backend.test", transport=httpx.MockTransport(handler)
    ) as client:
        result = BackendClient(client).check(
            BackendReputationRequest(ip_address="8.8.8.8", max_age_days=90),
            request_id=REQUEST_ID,
        )

    assert result.ip_address == "8.8.8.8"
    assert result.max_age_days == 90


@pytest.mark.parametrize(
    ("internal_code", "application_code", "status_code"),
    [
        ("RATE_LIMIT_EXCEEDED", "RATE_LIMIT_EXCEEDED", 429),
        ("UPSTREAM_INVALID_RESPONSE", "PROVIDER_INVALID_RESPONSE", 502),
        ("UPSTREAM_REQUEST_REJECTED", "PROVIDER_REQUEST_REJECTED", 502),
        (
            "ABUSEIPDB_AUTHENTICATION_FAILED",
            "PROVIDER_AUTHENTICATION_FAILED",
            503,
        ),
        ("ABUSEIPDB_UNAVAILABLE", "PROVIDER_UNAVAILABLE", 503),
        ("UPSTREAM_TIMEOUT", "PROVIDER_TIMEOUT", 504),
    ],
)
def test_check_maps_proxy_errors(
    internal_code: str, application_code: str, status_code: int
) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            status_code,
            json={
                "error": {
                    "code": internal_code,
                    "message": "internal detail",
                    "request_id": REQUEST_ID,
                }
            },
            headers={"X-Request-ID": REQUEST_ID},
        )
    )
    with httpx.Client(base_url="http://backend.test", transport=transport) as client:
        with pytest.raises(Exception) as captured:
            BackendClient(client).check(
                BackendReputationRequest(ip_address="8.8.8.8", max_age_days=90),
                request_id=REQUEST_ID,
            )

    error = captured.value
    assert getattr(error, "code") == application_code
    assert getattr(error, "status_code") == status_code
    assert "internal detail" not in str(error)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json", headers={"X-Request-ID": REQUEST_ID}),
        httpx.Response(200, json=valid_response()),
        httpx.Response(
            200,
            json={**valid_response(), "ip_address": "1.1.1.1"},
            headers={"X-Request-ID": REQUEST_ID},
        ),
        httpx.Response(
            502,
            json={
                "error": {"code": "UNKNOWN", "message": "x", "request_id": REQUEST_ID}
            },
            headers={"X-Request-ID": REQUEST_ID},
        ),
    ],
)
def test_check_rejects_invalid_or_inconsistent_proxy_responses(
    response: httpx.Response,
) -> None:
    with httpx.Client(
        base_url="http://backend.test",
        transport=httpx.MockTransport(lambda _: response),
    ) as client:
        with pytest.raises(BackendInvalidResponseError):
            BackendClient(client).check(
                BackendReputationRequest(ip_address="8.8.8.8", max_age_days=90),
                request_id=REQUEST_ID,
            )


def test_check_maps_transport_failure() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    with httpx.Client(
        base_url="http://backend.test", transport=httpx.MockTransport(fail)
    ) as client:
        with pytest.raises(BackendUnavailableError):
            BackendClient(client).check(
                BackendReputationRequest(ip_address="8.8.8.8", max_age_days=90),
                request_id=REQUEST_ID,
            )
