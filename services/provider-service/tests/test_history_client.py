from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from provider_service.history_client import (
    HistoryDeliveryError,
    HistoryIngestionClient,
)
from provider_service.schemas import BlacklistSnapshotDelivery

NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
DELIVERY_ID = UUID("662ecba0-8918-433d-bc75-b14de17851f1")


def delivery() -> BlacklistSnapshotDelivery:
    return BlacklistSnapshotDelivery.model_validate(
        {
            "delivery_id": str(DELIVERY_ID),
            "snapshot": {
                "provider": "AbuseIPDB",
                "generated_at": NOW.isoformat(),
                "fetched_at": NOW.isoformat(),
                "request": {"confidence_minimum": 90, "limit": 1000},
                "rate_limit": {},
                "items": [],
            },
        }
    )


@pytest.mark.anyio
async def test_duplicate_delivery_acknowledgement_is_accepted() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/v1/blacklist/snapshots"
        assert request.headers["Authorization"] == "Bearer history-secret"
        assert request.headers["X-Request-ID"] == str(DELIVERY_ID)
        return httpx.Response(
            200,
            json={
                "delivery_id": str(DELIVERY_ID),
                "snapshot_id": 42,
                "status": "duplicate",
                "received_at": NOW.isoformat(),
            },
        )

    async with httpx.AsyncClient(
        base_url="http://history.test",
        headers={"Authorization": "Bearer history-secret"},
        transport=httpx.MockTransport(handler),
    ) as client:
        receipt = await HistoryIngestionClient(
            client, operation_timeout_seconds=1
        ).deliver(delivery())

    assert receipt.status == "duplicate"
    assert receipt.snapshot_id == 42


@pytest.mark.anyio
async def test_history_unavailable_is_retryable() -> None:
    async with httpx.AsyncClient(
        base_url="http://history.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
    ) as client:
        with pytest.raises(HistoryDeliveryError):
            await HistoryIngestionClient(client, operation_timeout_seconds=1).deliver(
                delivery()
            )
