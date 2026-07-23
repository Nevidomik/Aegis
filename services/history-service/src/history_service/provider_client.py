"""Validated HTTP client for the internal Provider proxy boundary."""

import logging

import httpx
from fastapi import Request
from pydantic import ValidationError

from history_service.exceptions import (
    ProviderServiceInvalidResponseError,
    ProviderServiceUnavailableError,
)
from history_service.provider_error_contract import raise_mapped_provider_error
from history_service.schemas import (
    ProviderBlacklistRequest,
    ProviderBlacklistResponse,
    ProviderReputationRequest,
    ProviderReputationResponse,
)
from history_service.security_logging import log_sanitized_exception

logger = logging.getLogger(__name__)


class ProviderClient:
    """Call Provider's validated internal endpoints."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def check(
        self, payload: ProviderReputationRequest, *, request_id: str
    ) -> ProviderReputationResponse:
        try:
            response = self.client.post(
                "/internal/v1/reputation-checks",
                json=payload.model_dump(mode="json"),
                headers={"X-Request-ID": request_id},
            )
        except httpx.RequestError as error:
            log_sanitized_exception(
                logger, "provider_http_failure", error, request_id=request_id
            )
            raise ProviderServiceUnavailableError from error

        response_request_id = response.headers.get("X-Request-ID")
        if response_request_id != request_id:
            raise ProviderServiceInvalidResponseError

        if response.status_code >= 400:
            raise_mapped_provider_error(response, request_id=request_id)

        if response.status_code != 200:
            raise ProviderServiceInvalidResponseError
        try:
            result = ProviderReputationResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise ProviderServiceInvalidResponseError from error
        if (
            result.ip_address != payload.ip_address
            or result.max_age_days != payload.max_age_days
        ):
            raise ProviderServiceInvalidResponseError
        return result

    def get_blacklist(
        self, query: ProviderBlacklistRequest, *, request_id: str
    ) -> ProviderBlacklistResponse:
        """Retrieve and validate one complete normalized blacklist snapshot."""
        try:
            response = self.client.get(
                "/internal/v1/blacklist",
                params=query.model_dump(mode="json"),
                headers={"X-Request-ID": request_id},
            )
        except httpx.RequestError as error:
            log_sanitized_exception(
                logger, "provider_http_failure", error, request_id=request_id
            )
            raise ProviderServiceUnavailableError(
                code="PROVIDER_SERVICE_UNAVAILABLE"
            ) from error

        if response.headers.get("X-Request-ID") != request_id:
            raise ProviderServiceInvalidResponseError(
                code="PROVIDER_SERVICE_INVALID_RESPONSE"
            )

        if response.status_code >= 400:
            raise_mapped_provider_error(response, request_id=request_id)

        if response.status_code != 200:
            raise ProviderServiceInvalidResponseError(
                code="PROVIDER_SERVICE_INVALID_RESPONSE"
            )
        try:
            result = ProviderBlacklistResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise ProviderServiceInvalidResponseError(
                code="PROVIDER_SERVICE_INVALID_RESPONSE"
            ) from error
        if result.request.model_dump() != query.model_dump():
            raise ProviderServiceInvalidResponseError(
                code="PROVIDER_SERVICE_INVALID_RESPONSE"
            )
        addresses = [item.ip_address for item in result.items]
        if len(addresses) != len(set(addresses)):
            raise ProviderServiceInvalidResponseError(
                code="PROVIDER_SERVICE_INVALID_RESPONSE"
            )
        return result


def get_provider_client(request: Request) -> ProviderClient:
    return request.app.state.provider_client
