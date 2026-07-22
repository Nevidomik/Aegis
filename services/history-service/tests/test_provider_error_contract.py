from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from history_service.exceptions import ProviderServiceInvalidResponseError
from history_service.provider_client import ProviderClient
from history_service.schemas import ProviderBlacklistRequest, ProviderReputationRequest

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
DOCUMENTED_ERRORS = [
    (422, "INVALID_REQUEST", "PROVIDER_SERVICE_INVALID_RESPONSE"),
    (429, "RATE_LIMIT_EXCEEDED", "RATE_LIMIT_EXCEEDED"),
    (502, "UPSTREAM_INVALID_RESPONSE", "UPSTREAM_INVALID_RESPONSE"),
    (502, "UPSTREAM_REQUEST_REJECTED", "UPSTREAM_REQUEST_REJECTED"),
    (503, "UPSTREAM_AUTHENTICATION_FAILED", "UPSTREAM_AUTHENTICATION_FAILED"),
    (503, "UPSTREAM_UNAVAILABLE", "UPSTREAM_UNAVAILABLE"),
    (504, "UPSTREAM_TIMEOUT", "UPSTREAM_TIMEOUT"),
]


def error_response(status_code: int, code: str) -> httpx.Response:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": "Validated internal detail.",
            "request_id": REQUEST_ID,
        }
    }
    if code == "RATE_LIMIT_EXCEEDED":
        body["error"]["retry"] = {
            "retry_after_seconds": 60,
            "reset_at": "2026-07-23T00:00:00Z",
        }
    return httpx.Response(status_code, json=body, headers={"X-Request-ID": REQUEST_ID})


def invoke(flow: str, response: httpx.Response) -> None:
    with httpx.Client(
        base_url="http://provider.test",
        transport=httpx.MockTransport(lambda _: response),
    ) as client:
        provider = ProviderClient(client)
        if flow == "manual":
            provider.check(
                ProviderReputationRequest(ip_address="8.8.8.8", max_age_days=30),
                request_id=REQUEST_ID,
            )
        else:
            provider.get_blacklist(ProviderBlacklistRequest(), request_id=REQUEST_ID)


@pytest.mark.parametrize("flow", ["manual", "blacklist"])
@pytest.mark.parametrize(
    ("provider_status", "provider_code", "application_code"), DOCUMENTED_ERRORS
)
def test_every_documented_provider_error_is_mapped_in_both_flows(
    flow: str,
    provider_status: int,
    provider_code: str,
    application_code: str,
) -> None:
    with pytest.raises(Exception) as captured:
        invoke(flow, error_response(provider_status, provider_code))

    error = captured.value
    assert getattr(error, "code") == application_code
    if provider_code == "INVALID_REQUEST":
        assert isinstance(error, ProviderServiceInvalidResponseError)
        assert getattr(error, "status_code") == 502
    else:
        assert getattr(error, "status_code") == provider_status
    if provider_code == "RATE_LIMIT_EXCEEDED":
        assert getattr(error, "retry_after_seconds") == 60
        assert getattr(error, "reset_at") == datetime(2026, 7, 23, tzinfo=UTC)


@pytest.mark.parametrize("flow", ["manual", "blacklist"])
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            502,
            json={
                "error": {
                    "code": "UNKNOWN_PROVIDER_CODE",
                    "message": "unknown",
                    "request_id": REQUEST_ID,
                }
            },
            headers={"X-Request-ID": REQUEST_ID},
        ),
        httpx.Response(
            503,
            json={
                "error": {
                    "code": "UPSTREAM_TIMEOUT",
                    "message": "wrong status",
                    "request_id": REQUEST_ID,
                }
            },
            headers={"X-Request-ID": REQUEST_ID},
        ),
        httpx.Response(502, content=b"not-json", headers={"X-Request-ID": REQUEST_ID}),
    ],
)
def test_unknown_mismatched_and_invalid_errors_are_invalid_responses(
    flow: str, response: httpx.Response
) -> None:
    with pytest.raises(ProviderServiceInvalidResponseError) as captured:
        invoke(flow, response)

    assert captured.value.code == "PROVIDER_SERVICE_INVALID_RESPONSE"
