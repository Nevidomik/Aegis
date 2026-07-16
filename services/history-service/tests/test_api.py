from typing import Any

import pytest
from history_service.schemas import HistoryListQuery
from history_service.service import (
    CreateResult,
    HistoryUnavailableError,
    ListResult,
)
from httpx2 import AsyncClient

from .conftest import check_payload, history_record


class FakeHistoryService:
    def __init__(self) -> None:
        self.created = True
        self.record = history_record()
        self.records = [self.record]
        self.total = 1
        self.requested_query: HistoryListQuery | None = None

    def create(self, _: object, __: object) -> CreateResult:
        return CreateResult(record=self.record, created=self.created)

    def get(self, _: object, history_id: int) -> object:
        return self.record if history_id == self.record.id else None

    def list(self, _: object, query: HistoryListQuery) -> ListResult:
        self.requested_query = query
        return ListResult(records=self.records, total=self.total)


@pytest.mark.anyio
async def test_create_returns_201_for_new_record_and_200_for_duplicate(
    client: AsyncClient, override_service: Any
) -> None:
    service = FakeHistoryService()
    override_service(service)

    created_response = await client.post("/internal/v1/checks", json=check_payload())
    service.created = False
    duplicate_response = await client.post("/internal/v1/checks", json=check_payload())

    assert created_response.status_code == 201
    assert duplicate_response.status_code == 200
    assert (
        created_response.json()["history_id"] == duplicate_response.json()["history_id"]
    )


@pytest.mark.anyio
async def test_list_uses_bounded_pagination_and_normalized_filter(
    client: AsyncClient, override_service: Any
) -> None:
    service = FakeHistoryService()
    override_service(service)

    response = await client.get(
        "/internal/v1/checks",
        params={"limit": 10, "offset": 2, "ip_address": "8.8.8.8"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert service.requested_query == HistoryListQuery(
        limit=10, offset=2, ip_address="8.8.8.8"
    )


@pytest.mark.anyio
async def test_get_returns_record_or_stable_not_found(
    client: AsyncClient, override_service: Any
) -> None:
    override_service(FakeHistoryService())

    found = await client.get("/internal/v1/checks/145")
    missing = await client.get(
        "/internal/v1/checks/999", headers={"X-Request-ID": "test-request"}
    )

    assert found.status_code == 200
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {
            "code": "HISTORY_RECORD_NOT_FOUND",
            "message": "The requested history record does not exist.",
            "request_id": "test-request",
        }
    }


@pytest.mark.anyio
async def test_invalid_request_uses_stable_error_envelope(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/internal/v1/checks",
        params={"limit": 101},
        headers={"X-Request-ID": "bad"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["error"]["request_id"] == "bad"


@pytest.mark.anyio
async def test_database_failure_is_hidden(
    client: AsyncClient, override_service: Any
) -> None:
    class UnavailableService(FakeHistoryService):
        def list(self, _: object, query: HistoryListQuery) -> ListResult:
            raise HistoryUnavailableError("sensitive database details")

    override_service(UnavailableService())

    response = await client.get(
        "/internal/v1/checks", headers={"X-Request-ID": "unavailable"}
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "HISTORY_UNAVAILABLE",
            "message": "History storage is temporarily unavailable.",
            "request_id": "unavailable",
        }
    }
    assert "sensitive" not in response.text
