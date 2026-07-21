"""Validated HTTP client for the internal Backend proxy boundary."""

import httpx
from fastapi import Request
from pydantic import ValidationError

from history_service.exceptions import (
    BackendInvalidResponseError,
    BackendUnavailableError,
    map_proxy_error,
)
from history_service.schemas import (
    BackendErrorResponse,
    BackendReputationRequest,
    BackendReputationResponse,
)


class BackendClient:
    """Call only Backend's internal reputation endpoint."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def check(
        self, payload: BackendReputationRequest, *, request_id: str
    ) -> BackendReputationResponse:
        try:
            response = self.client.post(
                "/internal/v1/reputation-checks",
                json=payload.model_dump(mode="json"),
                headers={"X-Request-ID": request_id},
            )
        except httpx.RequestError as error:
            raise BackendUnavailableError from error

        response_request_id = response.headers.get("X-Request-ID")
        if response_request_id != request_id:
            raise BackendInvalidResponseError

        if response.status_code >= 400:
            try:
                error_response = BackendErrorResponse.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                raise BackendInvalidResponseError from error
            if error_response.error.request_id != request_id:
                raise BackendInvalidResponseError
            raise map_proxy_error(error_response.error.code)

        if response.status_code != 200:
            raise BackendInvalidResponseError
        try:
            result = BackendReputationResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise BackendInvalidResponseError from error
        if (
            result.ip_address != payload.ip_address
            or result.max_age_days != payload.max_age_days
        ):
            raise BackendInvalidResponseError
        return result


def get_backend_client(request: Request) -> BackendClient:
    return request.app.state.backend_client
