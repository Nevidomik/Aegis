from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from backend_service.exceptions import HistoryRecordNotFoundError
from backend_service.history_client import get_history_client
from backend_service.main import app
from backend_service.provider import FakeReputationProvider, get_reputation_provider
from backend_service.schemas import (
    CheckResponse,
    HistoryCheckCreate,
    HistoryListResponse,
)
from httpx2 import ASGITransport, AsyncClient


class FakeHistoryClient:
    def __init__(self) -> None:
        self.payload: HistoryCheckCreate | None = None
        self.request_id: str | None = None
        self.calls = 0
        self.list_request: dict[str, object] | None = None
        self.get_request: dict[str, object] | None = None
        self.records: list[CheckResponse] = []

    async def save(
        self, payload: HistoryCheckCreate, *, request_id: str
    ) -> CheckResponse:
        self.calls += 1
        self.payload = payload
        self.request_id = request_id
        record = CheckResponse(history_id=145, **payload.model_dump())
        self.records = [record]
        return record

    async def list(
        self,
        *,
        limit: int,
        offset: int,
        ip_address: str | None,
        request_id: str,
    ) -> HistoryListResponse:
        self.list_request = {
            "limit": limit,
            "offset": offset,
            "ip_address": ip_address,
            "request_id": request_id,
        }
        return HistoryListResponse(
            items=self.records,
            limit=limit,
            offset=offset,
            total=len(self.records),
        )

    async def get(self, history_id: int, *, request_id: str) -> CheckResponse:
        self.get_request = {"history_id": history_id, "request_id": request_id}
        for record in self.records:
            if record.history_id == history_id:
                return record
        raise HistoryRecordNotFoundError


@pytest.fixture
def history_client() -> FakeHistoryClient:
    return FakeHistoryClient()


@pytest.fixture
async def client(history_client: FakeHistoryClient) -> AsyncIterator[AsyncClient]:
    async def history_client_override() -> FakeHistoryClient:
        return history_client

    async def reputation_provider_override() -> FakeReputationProvider:
        return FakeReputationProvider()

    app.dependency_overrides[get_history_client] = history_client_override
    app.dependency_overrides[get_reputation_provider] = reputation_provider_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def override_dependency() -> Iterator[Any]:
    def apply(dependency: object, replacement: object) -> None:
        async def override() -> object:
            return replacement

        app.dependency_overrides[dependency] = override

    yield apply
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
