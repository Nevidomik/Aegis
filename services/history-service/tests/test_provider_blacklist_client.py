from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from history_service.exceptions import (
    ProviderServiceInvalidResponseError,
    ProviderServiceUnavailableError,
)
from history_service.provider_client import ProviderClient
from history_service.schemas import ProviderBlacklistRequest

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"


def valid_blacklist_response() -> dict[str, Any]:
    return {
        "provider": "AbuseIPDB",
        "generated_at": "2026-07-22T12:00:00Z",
        "fetched_at": "2026-07-22T12:00:02Z",
        "request": {"confidence_minimum": 90, "limit": 1000},
        "rate_limit": {
            "limit": 5,
            "remaining": 4,
            "reset_at": "2026-07-23T00:00:00Z",
            "retry_after_seconds": None,
        },
        "items": [
            {
                "ip_address": "8.8.8.8",
                "ip_version": 4,
                "abuse_confidence_score": 100,
                "country_code": "US",
                "last_reported_at": "2026-07-22T11:47:00Z",
            },
            {
                "ip_address": "2606:4700:4700::1111",
                "ip_version": 6,
                "abuse_confidence_score": 95,
                "country_code": None,
                "last_reported_at": None,
            },
        ],
    }


def call_with_response(response: httpx.Response) -> object:
    with httpx.Client(
        base_url="http://provider.test",
        transport=httpx.MockTransport(lambda _: response),
    ) as client:
        return ProviderClient(client).get_blacklist(
            ProviderBlacklistRequest(), request_id=REQUEST_ID
        )


def test_get_blacklist_calls_internal_endpoint_and_validates_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/internal/v1/blacklist"
        assert dict(request.url.params) == {
            "confidence_minimum": "90",
            "limit": "1000",
        }
        assert request.headers["X-Request-ID"] == REQUEST_ID
        return httpx.Response(
            200,
            json=valid_blacklist_response(),
            headers={"X-Request-ID": REQUEST_ID},
        )

    with httpx.Client(
        base_url="http://provider.test", transport=httpx.MockTransport(handler)
    ) as client:
        result = ProviderClient(client).get_blacklist(
            ProviderBlacklistRequest(), request_id=REQUEST_ID
        )

    assert result.generated_at == datetime(2026, 7, 22, 12, tzinfo=UTC)
    assert [item.ip_version for item in result.items] == [4, 6]


def test_get_blacklist_passes_explicit_query_parameters() -> None:
    payload = valid_blacklist_response()
    payload["request"] = {"confidence_minimum": 75, "limit": 50}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["confidence_minimum"] == "75"
        assert request.url.params["limit"] == "50"
        return httpx.Response(200, json=payload, headers={"X-Request-ID": REQUEST_ID})

    with httpx.Client(
        base_url="http://provider.test", transport=httpx.MockTransport(handler)
    ) as client:
        result = ProviderClient(client).get_blacklist(
            ProviderBlacklistRequest(confidence_minimum=75, limit=50),
            request_id=REQUEST_ID,
        )

    assert result.request.confidence_minimum == 75
    assert result.request.limit == 50


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"unexpected": True}),
        lambda body: body["request"].update({"unexpected": True}),
        lambda body: body["rate_limit"].update({"unexpected": True}),
        lambda body: body["items"][0].update({"unexpected": True}),
        lambda body: body["items"].append(deepcopy(body["items"][0])),
        lambda body: body["items"][1].update(
            {"ip_address": "2606:4700:4700:0:0:0:0:1111"}
        ),
        lambda body: body["items"][0].update({"ip_version": 6}),
        lambda body: body.update(
            {"request": {"confidence_minimum": 91, "limit": 1000}}
        ),
    ],
)
def test_get_blacklist_rejects_invalid_normalized_contract(mutate: Any) -> None:
    body = valid_blacklist_response()
    mutate(body)

    with pytest.raises(ProviderServiceInvalidResponseError) as captured:
        call_with_response(
            httpx.Response(200, json=body, headers={"X-Request-ID": REQUEST_ID})
        )

    assert captured.value.code == "PROVIDER_SERVICE_INVALID_RESPONSE"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json", headers={"X-Request-ID": REQUEST_ID}),
        httpx.Response(200, json=valid_blacklist_response()),
        httpx.Response(
            200,
            json=valid_blacklist_response(),
            headers={"X-Request-ID": "84d80e88-1fe5-4540-99b1-4e2e17645b3c"},
        ),
        httpx.Response(
            502,
            json={
                "error": {
                    "code": "UPSTREAM_INVALID_RESPONSE",
                    "message": "safe",
                    "request_id": REQUEST_ID,
                    "unexpected": True,
                }
            },
            headers={"X-Request-ID": REQUEST_ID},
        ),
    ],
)
def test_get_blacklist_maps_invalid_json_schema_and_request_id(
    response: httpx.Response,
) -> None:
    with pytest.raises(ProviderServiceInvalidResponseError) as captured:
        call_with_response(response)

    assert captured.value.code == "PROVIDER_SERVICE_INVALID_RESPONSE"


def test_get_blacklist_maps_connection_failure() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    with httpx.Client(
        base_url="http://provider.test", transport=httpx.MockTransport(fail)
    ) as client:
        with pytest.raises(ProviderServiceUnavailableError) as captured:
            ProviderClient(client).get_blacklist(
                ProviderBlacklistRequest(), request_id=REQUEST_ID
            )

    assert captured.value.code == "PROVIDER_SERVICE_UNAVAILABLE"


def test_get_blacklist_maps_provider_service_timeout() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timed out", request=request)

    with httpx.Client(
        base_url="http://provider.test", transport=httpx.MockTransport(fail)
    ) as client:
        with pytest.raises(ProviderServiceUnavailableError) as captured:
            ProviderClient(client).get_blacklist(
                ProviderBlacklistRequest(), request_id=REQUEST_ID
            )

    assert captured.value.code == "PROVIDER_SERVICE_UNAVAILABLE"


def test_get_blacklist_preserves_validated_rate_limit_retry_metadata() -> None:
    response = httpx.Response(
        429,
        json={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "The provider rate limit has been reached.",
                "request_id": REQUEST_ID,
                "retry": {
                    "retry_after_seconds": 3600,
                    "reset_at": "2026-07-23T00:00:00Z",
                },
            }
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    with pytest.raises(Exception) as captured:
        call_with_response(response)

    assert getattr(captured.value, "code") == "RATE_LIMIT_EXCEEDED"
    assert getattr(captured.value, "retry_after_seconds") == 3600
    assert getattr(captured.value, "reset_at") == datetime(2026, 7, 23, tzinfo=UTC)


def test_get_blacklist_rejects_malformed_retry_metadata() -> None:
    response = httpx.Response(
        429,
        json={
            "error": {
                "code": "RATE_LIMIT_EXCEEDED",
                "message": "safe",
                "request_id": REQUEST_ID,
                "retry": {"retry_after_seconds": -1, "reset_at": "not-a-date"},
            }
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    with pytest.raises(ProviderServiceInvalidResponseError) as captured:
        call_with_response(response)

    assert captured.value.code == "PROVIDER_SERVICE_INVALID_RESPONSE"


def test_get_blacklist_maps_unknown_provider_error_to_invalid_response() -> None:
    response = httpx.Response(
        502,
        json={
            "error": {
                "code": "UNKNOWN_INTERNAL_ERROR",
                "message": "safe",
                "request_id": REQUEST_ID,
            }
        },
        headers={"X-Request-ID": REQUEST_ID},
    )

    with pytest.raises(ProviderServiceInvalidResponseError) as captured:
        call_with_response(response)

    assert captured.value.code == "PROVIDER_SERVICE_INVALID_RESPONSE"
