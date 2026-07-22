"""Canonical validation and mapping for Provider Service error envelopes."""

from typing import NoReturn

import httpx
from pydantic import ValidationError

from history_service.exceptions import (
    ApplicationError,
    ProviderServiceInvalidResponseError,
)
from history_service.schemas import ProviderErrorResponse

PROVIDER_ERROR_MAP: dict[str, tuple[int, int, str, str]] = {
    "RATE_LIMIT_EXCEEDED": (
        429,
        429,
        "RATE_LIMIT_EXCEEDED",
        "The reputation provider rate limit has been exceeded.",
    ),
    "UPSTREAM_INVALID_RESPONSE": (
        502,
        502,
        "UPSTREAM_INVALID_RESPONSE",
        "The reputation provider returned an invalid response.",
    ),
    "UPSTREAM_REQUEST_REJECTED": (
        502,
        502,
        "UPSTREAM_REQUEST_REJECTED",
        "The reputation provider rejected the lookup request.",
    ),
    "UPSTREAM_AUTHENTICATION_FAILED": (
        503,
        503,
        "UPSTREAM_AUTHENTICATION_FAILED",
        "The reputation provider rejected its credentials.",
    ),
    "UPSTREAM_UNAVAILABLE": (
        503,
        503,
        "UPSTREAM_UNAVAILABLE",
        "The reputation provider is temporarily unavailable.",
    ),
    "UPSTREAM_TIMEOUT": (
        504,
        504,
        "UPSTREAM_TIMEOUT",
        "The reputation provider timed out.",
    ),
}


def raise_mapped_provider_error(
    response: httpx.Response, *, request_id: str
) -> NoReturn:
    """Validate one error envelope and raise its application-level equivalent."""
    try:
        envelope = ProviderErrorResponse.model_validate(response.json())
    except (ValueError, ValidationError) as error:
        raise ProviderServiceInvalidResponseError(
            code="PROVIDER_SERVICE_INVALID_RESPONSE"
        ) from error

    detail = envelope.error
    if detail.request_id != request_id:
        raise ProviderServiceInvalidResponseError(
            code="PROVIDER_SERVICE_INVALID_RESPONSE"
        )
    mapped = PROVIDER_ERROR_MAP.get(detail.code)
    if mapped is None or response.status_code != mapped[0]:
        raise ProviderServiceInvalidResponseError(
            code="PROVIDER_SERVICE_INVALID_RESPONSE"
        )

    _, application_status, application_code, message = mapped
    mapped_error = ApplicationError(
        status_code=application_status,
        code=application_code,
        message=message,
    )
    if detail.retry is not None:
        mapped_error.retry_after_seconds = detail.retry.retry_after_seconds
        mapped_error.reset_at = detail.retry.reset_at
    raise mapped_error
