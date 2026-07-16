"""HTTP client for the only service boundary available to UI."""

import httpx
from fastapi import Request
from pydantic import BaseModel, ValidationError

from ui_service.schemas import (
    BackendErrorResponse,
    CheckResult,
    HistoryPage,
    ReadinessResponse,
)


class BackendClientError(Exception):
    """A readable and safe Backend failure for page rendering."""


class BackendClient:
    """Call only the documented Backend public API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def check(
        self, *, ip_address: str, max_age_days: int, request_id: str
    ) -> CheckResult:
        response = await self._request(
            "POST",
            "/api/v1/checks",
            request_id=request_id,
            json={"ip_address": ip_address, "max_age_days": max_age_days},
        )
        return self._validated_response(response, CheckResult)

    async def recent_history(self, *, request_id: str) -> HistoryPage:
        response = await self._request(
            "GET",
            "/api/v1/checks",
            request_id=request_id,
            params={"limit": 20, "offset": 0},
        )
        return self._validated_response(response, HistoryPage)

    async def ready(self, *, request_id: str) -> None:
        response = await self._request("GET", "/health/ready", request_id=request_id)
        self._validated_response(response, ReadinessResponse)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        params: dict[str, int] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        try:
            return await self.client.request(
                method,
                path,
                params=params,
                json=json,
                headers={"X-Request-ID": request_id},
            )
        except httpx.RequestError as error:
            raise BackendClientError(
                "Backend Service is unavailable. Please try again."
            ) from error

    @staticmethod
    def _validated_response[Model: BaseModel](
        response: httpx.Response, model: type[Model]
    ) -> Model:
        if response.status_code >= 400:
            try:
                error = BackendErrorResponse.model_validate(response.json())
            except ValueError, ValidationError:
                raise BackendClientError(
                    "Backend Service returned an unexpected error."
                ) from None
            raise BackendClientError(error.error.message)
        try:
            return model.model_validate(response.json())
        except ValueError, ValidationError:
            raise BackendClientError(
                "Backend Service returned an invalid response."
            ) from None


async def get_backend_client(request: Request) -> BackendClient:
    return request.app.state.backend_client
