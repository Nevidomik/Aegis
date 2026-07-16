"""HTTP client for the History service boundary."""

import httpx
from pydantic import ValidationError

from backend_service.config import Settings, get_settings
from backend_service.exceptions import (
    HistoryInvalidResponseError,
    HistoryUnavailableError,
)
from backend_service.schemas import CheckResponse, HistoryCheckCreate


class HistoryClient:
    """Persist normalized checks through the History HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = str(settings.history_service_url).rstrip("/")
        self.timeout = settings.history_timeout_seconds

    async def save(
        self, payload: HistoryCheckCreate, *, request_id: str
    ) -> CheckResponse:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout
            ) as client:
                response = await client.post(
                    "/internal/v1/checks",
                    json=payload.model_dump(mode="json"),
                    headers={"X-Request-ID": request_id},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise HistoryUnavailableError from error

        if response.status_code not in {200, 201}:
            raise HistoryUnavailableError
        try:
            saved = CheckResponse.model_validate(response.json())
        except (ValueError, ValidationError) as error:
            raise HistoryInvalidResponseError from error
        if saved.request_id != payload.request_id:
            raise HistoryInvalidResponseError
        return saved


async def get_history_client() -> HistoryClient:
    return HistoryClient(get_settings())
