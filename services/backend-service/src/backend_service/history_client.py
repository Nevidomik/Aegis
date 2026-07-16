"""HTTP client for the History service boundary."""

import httpx
from pydantic import ValidationError

from backend_service.config import Settings, get_settings
from backend_service.exceptions import (
    HistoryInvalidResponseError,
    HistoryRecordNotFoundError,
    HistoryUnavailableError,
)
from backend_service.schemas import (
    CheckResponse,
    HistoryCheckCreate,
    HistoryListResponse,
)


class HistoryClient:
    """Persist normalized checks through the History HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = str(settings.history_service_url).rstrip("/")
        self.timeout = settings.history_timeout_seconds

    async def save(
        self, payload: HistoryCheckCreate, *, request_id: str
    ) -> CheckResponse:
        response = await self._request(
            "POST",
            "/internal/v1/checks",
            request_id=request_id,
            json=payload.model_dump(mode="json"),
        )
        if response.status_code not in {200, 201}:
            self._raise_for_status(response.status_code)
        try:
            saved = CheckResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise HistoryInvalidResponseError from error
        if saved.request_id != payload.request_id:
            raise HistoryInvalidResponseError
        return saved

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        ip_address: str | None,
        request_id: str,
    ) -> HistoryListResponse:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if ip_address is not None:
            params["ip_address"] = ip_address
        response = await self._request(
            "GET",
            "/internal/v1/checks",
            request_id=request_id,
            params=params,
        )
        if response.status_code != 200:
            self._raise_for_status(response.status_code)
        try:
            page = HistoryListResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise HistoryInvalidResponseError from error
        if page.limit != limit or page.offset != offset:
            raise HistoryInvalidResponseError
        return page

    async def get(self, history_id: int, *, request_id: str) -> CheckResponse:
        response = await self._request(
            "GET",
            f"/internal/v1/checks/{history_id}",
            request_id=request_id,
        )
        if response.status_code != 200:
            self._raise_for_status(response.status_code, allow_not_found=True)
        try:
            return CheckResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise HistoryInvalidResponseError from error

    async def _request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        params: dict[str, str | int] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            ) as client:
                return await client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    headers={"X-Request-ID": request_id},
                )
        except httpx.RequestError as error:
            raise HistoryUnavailableError from error

    @staticmethod
    def _raise_for_status(status_code: int, *, allow_not_found: bool = False) -> None:
        if status_code == 404 and allow_not_found:
            raise HistoryRecordNotFoundError
        if status_code >= 500:
            raise HistoryUnavailableError
        raise HistoryInvalidResponseError


async def get_history_client() -> HistoryClient:
    return HistoryClient(get_settings())
