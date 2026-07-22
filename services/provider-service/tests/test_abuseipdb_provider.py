from ipaddress import ip_address

import httpx
import pytest
from provider_service.exceptions import (
    AbuseIPDBAuthenticationError,
    AbuseIPDBUnavailableError,
    RateLimitExceededError,
    UpstreamInvalidResponseError,
    UpstreamRequestRejectedError,
    UpstreamTimeoutError,
)
from provider_service.provider import AbuseIPDBProvider


def valid_response(ip_value: str = "8.8.8.8") -> dict[str, object]:
    return {
        "data": {
            "ipAddress": ip_value,
            "isPublic": True,
            "ipVersion": 6 if ":" in ip_value else 4,
            "isWhitelisted": None,
            "abuseConfidenceScore": 12,
            "countryCode": "US",
            "usageType": "Data Center/Web Hosting/Transit",
            "isp": "Example ISP",
            "domain": "example.test",
            "totalReports": 7,
            "numDistinctUsers": 3,
            "lastReportedAt": "2026-07-15T18:30:00Z",
        }
    }


@pytest.mark.anyio
async def test_lookup_sends_required_request_and_normalizes_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v2/check"
        assert dict(request.url.params) == {
            "ipAddress": "2606:4700:4700::1111",
            "maxAgeInDays": "90",
        }
        assert request.headers["Key"] == "test-key"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(
            200,
            json=valid_response("2606:4700:4700:0:0:0:0:1111"),
        )

    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        headers={"Key": "test-key", "Accept": "application/json"},
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        result = await AbuseIPDBProvider(client).lookup(
            ip_address("2606:4700:4700::1111"), 90
        )

    assert result.ip_address == "2606:4700:4700::1111"
    assert result.source == "AbuseIPDB"
    assert result.abuse_confidence_score == 12


@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (401, AbuseIPDBAuthenticationError),
        (403, AbuseIPDBAuthenticationError),
        (429, RateLimitExceededError),
        (400, UpstreamRequestRejectedError),
        (422, UpstreamRequestRejectedError),
        (500, AbuseIPDBUnavailableError),
        (503, AbuseIPDBUnavailableError),
        (302, UpstreamInvalidResponseError),
    ],
)
@pytest.mark.anyio
async def test_lookup_maps_upstream_statuses(
    status_code: int, exception_type: type[Exception]
) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(status_code, json={"errors": []})
    )
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test", transport=transport
    ) as client:
        with pytest.raises(exception_type):
            await AbuseIPDBProvider(client).lookup(ip_address("8.8.8.8"), 30)


@pytest.mark.anyio
async def test_lookup_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(UpstreamTimeoutError):
            await AbuseIPDBProvider(client).lookup(ip_address("8.8.8.8"), 30)


@pytest.mark.anyio
async def test_lookup_maps_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(AbuseIPDBUnavailableError):
            await AbuseIPDBProvider(client).lookup(ip_address("8.8.8.8"), 30)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"data": {"ipAddress": "8.8.8.8"}}),
        httpx.Response(200, json=valid_response("1.1.1.1")),
    ],
)
@pytest.mark.anyio
async def test_lookup_rejects_malformed_or_invalid_responses(
    response: httpx.Response,
) -> None:
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: response),
    ) as client:
        with pytest.raises(UpstreamInvalidResponseError):
            await AbuseIPDBProvider(client).lookup(ip_address("8.8.8.8"), 30)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("isPublic", 1),
        ("ipVersion", 6),
        ("abuseConfidenceScore", "12"),
        ("totalReports", 2_147_483_648),
        ("lastReportedAt", "2026-07-15T18:30:00"),
        ("isp", "x" * 256),
    ],
)
@pytest.mark.anyio
async def test_lookup_rejects_coerced_inconsistent_or_unbounded_fields(
    field: str, value: object
) -> None:
    body = valid_response()
    data = body["data"]
    assert isinstance(data, dict)
    data[field] = value
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    ) as client:
        with pytest.raises(UpstreamInvalidResponseError):
            await AbuseIPDBProvider(client).lookup(ip_address("8.8.8.8"), 30)
