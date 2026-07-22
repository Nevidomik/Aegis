from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from history_service.blacklist_read import get_blacklist_read_service
from history_service.provider_client import get_provider_client
from history_service.schemas import (
    BlacklistEntryResponse,
    BlacklistLastError,
    BlacklistPage,
    BlacklistSnapshotList,
    BlacklistSnapshotSummary,
    BlacklistStatusResponse,
)
from httpx2 import AsyncClient

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def summary() -> BlacklistSnapshotSummary:
    return BlacklistSnapshotSummary(
        snapshot_id=42,
        provider="AbuseIPDB",
        provider_generated_at=NOW,
        fetched_at=NOW,
        confidence_minimum=90,
        requested_limit=1000,
        returned_count=1,
    )


def page() -> BlacklistPage:
    return BlacklistPage(
        snapshot=summary(),
        items=[
            BlacklistEntryResponse(
                ip_address="8.8.8.8",
                ip_version=4,
                abuse_confidence_score=100,
                country_code="US",
                last_reported_at=NOW,
            )
        ],
        limit=100,
        offset=0,
        total=1,
    )


@pytest.mark.anyio
async def test_blacklist_read_endpoints_never_call_provider(
    client: AsyncClient, override_dependency: Any
) -> None:
    service = Mock()
    service.status.return_value = BlacklistStatusResponse(
        state="ready",
        sync_in_progress=False,
        latest_snapshot_id=42,
        latest_provider_generated_at=NOW,
        latest_fetched_at=NOW,
        data_stale=False,
    )
    service.latest.return_value = page()
    service.snapshots.return_value = BlacklistSnapshotList(
        items=[summary()], limit=20, offset=0, total=1
    )
    service.snapshot.return_value = page()
    provider = Mock()
    override_dependency(get_blacklist_read_service, service)
    override_dependency(get_provider_client, provider)

    responses = [
        await client.get(
            "/api/v1/blacklist/status", headers={"X-Request-ID": REQUEST_ID}
        ),
        await client.get("/api/v1/blacklist", headers={"X-Request-ID": REQUEST_ID}),
        await client.get(
            "/api/v1/blacklist/snapshots", headers={"X-Request-ID": REQUEST_ID}
        ),
        await client.get(
            "/api/v1/blacklist/snapshots/42",
            headers={"X-Request-ID": REQUEST_ID},
        ),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert all(response.headers["X-Request-ID"] == REQUEST_ID for response in responses)
    provider.check.assert_not_called()
    provider.get_blacklist.assert_not_called()


@pytest.mark.anyio
async def test_blacklist_empty_and_missing_snapshot_return_safe_404(
    client: AsyncClient, override_dependency: Any
) -> None:
    service = Mock()
    service.latest.return_value = None
    service.snapshot.return_value = None
    override_dependency(get_blacklist_read_service, service)

    latest = await client.get("/api/v1/blacklist", headers={"X-Request-ID": REQUEST_ID})
    missing = await client.get(
        "/api/v1/blacklist/snapshots/999", headers={"X-Request-ID": REQUEST_ID}
    )

    assert latest.status_code == 404
    assert missing.status_code == 404
    assert latest.json()["error"]["code"] == "BLACKLIST_SNAPSHOT_NOT_FOUND"
    assert missing.json()["error"]["request_id"] == REQUEST_ID


@pytest.mark.anyio
@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=101",
        "offset=-1",
        "ip_version=5",
        "minimum_score=-1",
        "minimum_score=101",
        "country_code=us",
        "country_code=USA",
    ],
)
async def test_blacklist_entry_query_validation(
    client: AsyncClient, query: str
) -> None:
    response = await client.get(f"/api/v1/blacklist?{query}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
async def test_blacklist_snapshot_list_query_validation(
    client: AsyncClient, query: str
) -> None:
    response = await client.get(f"/api/v1/blacklist/snapshots?{query}")
    assert response.status_code == 422


def test_status_error_model_contains_only_safe_summary() -> None:
    result = BlacklistStatusResponse(
        state="degraded",
        sync_in_progress=False,
        latest_snapshot_id=42,
        latest_provider_generated_at=NOW,
        latest_fetched_at=NOW,
        data_stale=False,
        last_error=BlacklistLastError(
            code="UPSTREAM_TIMEOUT",
            message="The latest synchronization attempt failed.",
        ),
    )
    assert result.model_dump()["last_error"] == {
        "code": "UPSTREAM_TIMEOUT",
        "message": "The latest synchronization attempt failed.",
    }
