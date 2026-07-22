from datetime import UTC, datetime

import httpx
import pytest
from provider_service.exceptions import (
    AbuseIPDBAuthenticationError,
    AbuseIPDBUnavailableError,
    RateLimitExceededError,
    UpstreamInvalidResponseError,
    UpstreamTimeoutError,
)
from provider_service.provider import AbuseIPDBProvider


def blacklist_response(
    items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "meta": {"generatedAt": "2026-07-22T12:00:00Z"},
        "data": items
        if items is not None
        else [
            {
                "ipAddress": "8.8.8.8",
                "abuseConfidenceScore": 100,
                "countryCode": "us",
                "lastReportedAt": "2026-07-22T11:47:00Z",
            },
            {
                "ipAddress": "2606:4700:4700:0:0:0:0:1111",
                "abuseConfidenceScore": 95,
                "countryCode": None,
                "lastReportedAt": None,
            },
        ],
    }


@pytest.mark.anyio
async def test_blacklist_sends_request_and_normalizes_complete_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v2/blacklist"
        assert dict(request.url.params) == {
            "confidenceMinimum": "90",
            "limit": "1000",
        }
        assert request.headers["Key"] == "test-key"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(
            200,
            json=blacklist_response(),
            headers={
                "X-RateLimit-Limit": "5",
                "X-RateLimit-Remaining": "4",
                "X-RateLimit-Reset": "1784764800",
                "Retry-After": "60",
            },
        )

    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        headers={"Key": "test-key", "Accept": "application/json"},
        transport=httpx.MockTransport(handler),
    ) as client:
        result = await AbuseIPDBProvider(client).blacklist(90, 1000)

    assert result.generated_at == datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    assert [item.ip_address for item in result.items] == [
        "8.8.8.8",
        "2606:4700:4700::1111",
    ]
    assert [item.ip_version for item in result.items] == [4, 6]
    assert result.items[0].country_code == "US"
    assert result.rate_limit.limit == 5
    assert result.rate_limit.remaining == 4
    assert result.rate_limit.reset_at == datetime.fromtimestamp(1784764800, tz=UTC)
    assert result.rate_limit.retry_after_seconds == 60


@pytest.mark.anyio
async def test_blacklist_accepts_empty_data_and_missing_rate_limit_headers() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=blacklist_response([]))
        ),
    ) as client:
        result = await AbuseIPDBProvider(client).blacklist(90, 1000)

    assert result.items == []
    assert result.rate_limit.model_dump() == {
        "limit": None,
        "remaining": None,
        "reset_at": None,
        "retry_after_seconds": None,
    }


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"data": []}),
        httpx.Response(
            200,
            json=blacklist_response(
                [{"ipAddress": "8.8.8.8", "abuseConfidenceScore": "100"}]
            ),
        ),
        httpx.Response(
            200,
            json=blacklist_response(
                [{"ipAddress": "not-an-ip", "abuseConfidenceScore": 100}]
            ),
        ),
    ],
)
@pytest.mark.anyio
async def test_blacklist_rejects_invalid_json_entry_schema_or_ip(
    response: httpx.Response,
) -> None:
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: response),
    ) as client:
        with pytest.raises(UpstreamInvalidResponseError):
            await AbuseIPDBProvider(client).blacklist(90, 1000)


@pytest.mark.anyio
async def test_blacklist_rejects_duplicate_normalized_ip_addresses() -> None:
    body = blacklist_response(
        [
            {"ipAddress": "2606:4700:4700::1111", "abuseConfidenceScore": 100},
            {
                "ipAddress": "2606:4700:4700:0:0:0:0:1111",
                "abuseConfidenceScore": 99,
            },
        ]
    )
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    ) as client:
        with pytest.raises(UpstreamInvalidResponseError):
            await AbuseIPDBProvider(client).blacklist(90, 1000)


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.anyio
async def test_blacklist_maps_authentication_failures(status_code: int) -> None:
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(status_code)),
    ) as client:
        with pytest.raises(AbuseIPDBAuthenticationError):
            await AbuseIPDBProvider(client).blacklist(90, 1000)


@pytest.mark.anyio
async def test_blacklist_rate_limit_error_preserves_retry_metadata() -> None:
    response = httpx.Response(
        429,
        headers={"Retry-After": "3600", "X-RateLimit-Reset": "1784764800"},
    )
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: response),
    ) as client:
        with pytest.raises(RateLimitExceededError) as captured:
            await AbuseIPDBProvider(client).blacklist(90, 1000)

    assert captured.value.retry_after_seconds == 3600
    assert captured.value.reset_at == datetime.fromtimestamp(1784764800, tz=UTC)


@pytest.mark.anyio
async def test_blacklist_maps_upstream_5xx() -> None:
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    ) as client:
        with pytest.raises(AbuseIPDBUnavailableError):
            await AbuseIPDBProvider(client).blacklist(90, 1000)


@pytest.mark.parametrize("failure", ["connection", "timeout"])
@pytest.mark.anyio
async def test_blacklist_maps_transport_failures(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        raise httpx.ConnectError("connection failed", request=request)

    expected = (
        UpstreamTimeoutError if failure == "timeout" else AbuseIPDBUnavailableError
    )
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(expected):
            await AbuseIPDBProvider(client).blacklist(90, 1000)


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("X-RateLimit-Limit", "invalid"),
        ("X-RateLimit-Remaining", "-1"),
        ("X-RateLimit-Reset", "invalid"),
        ("Retry-After", "tomorrow"),
    ],
)
@pytest.mark.anyio
async def test_blacklist_ignores_malformed_rate_limit_headers(
    header: str, value: str
) -> None:
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json=blacklist_response([]), headers={header: value}
            )
        ),
    ) as client:
        result = await AbuseIPDBProvider(client).blacklist(90, 1000)

    assert result.rate_limit.model_dump() == {
        "limit": None,
        "remaining": None,
        "reset_at": None,
        "retry_after_seconds": None,
    }


@pytest.mark.anyio
async def test_blacklist_ignores_contradictory_remaining_header() -> None:
    headers = {"X-RateLimit-Limit": "5", "X-RateLimit-Remaining": "6"}
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=blacklist_response([]), headers=headers)
        ),
    ) as client:
        result = await AbuseIPDBProvider(client).blacklist(90, 1000)

    assert result.rate_limit.limit == 5
    assert result.rate_limit.remaining is None


@pytest.mark.anyio
async def test_rate_limit_ignores_malformed_retry_constraints() -> None:
    response = httpx.Response(
        429,
        headers={"Retry-After": "tomorrow", "X-RateLimit-Reset": "invalid"},
    )
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(lambda _: response),
    ) as client:
        with pytest.raises(RateLimitExceededError) as captured:
            await AbuseIPDBProvider(client).blacklist(90, 1000)

    assert captured.value.retry_after_seconds is None
    assert captured.value.reset_at is None


@pytest.mark.anyio
async def test_blacklist_rejects_more_entries_than_requested() -> None:
    items: list[dict[str, object]] = [
        {"ipAddress": address, "abuseConfidenceScore": 100}
        for address in ("8.8.8.8", "1.1.1.1")
    ]
    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=blacklist_response(items))
        ),
    ) as client:
        with pytest.raises(UpstreamInvalidResponseError):
            await AbuseIPDBProvider(client).blacklist(90, 1)
