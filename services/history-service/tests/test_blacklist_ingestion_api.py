from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from history_service.blacklist_ingestion import (
    BlacklistIngestionResult,
    get_blacklist_ingestion_service,
)
from history_service.config import Settings, get_settings
from history_service.models import BlacklistSnapshot
from httpx2 import AsyncClient

REQUEST_ID = "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
DELIVERY_ID = "662ecba0-8918-433d-bc75-b14de17851f1"
TOKEN = "provider-ingestion-token-at-least-32-characters"
NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)


def payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "delivery_id": DELIVERY_ID,
        "snapshot": {
            "provider": "AbuseIPDB",
            "generated_at": NOW.isoformat(),
            "fetched_at": NOW.isoformat(),
            "request": {"confidence_minimum": 90, "limit": 1000},
            "rate_limit": {
                "limit": 5,
                "remaining": 4,
                "reset_at": None,
                "retry_after_seconds": None,
            },
            "items": [
                {
                    "ip_address": "8.8.8.8",
                    "ip_version": 4,
                    "abuse_confidence_score": 100,
                    "country_code": "US",
                    "last_reported_at": NOW.isoformat(),
                }
            ],
        },
    }
    body.update(overrides)
    return body


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        mariadb_database="aegis_history",
        mariadb_user="history",
        mariadb_password="secret",
        provider_ingestion_token=TOKEN,
    )


@pytest.mark.anyio
async def test_valid_ingestion_returns_stable_receipt(
    client: AsyncClient, override_dependency: Any
) -> None:
    service = Mock()
    snapshot = BlacklistSnapshot(snapshot_id=42)
    service.ingest.return_value = BlacklistIngestionResult(snapshot, True, NOW)
    override_dependency(get_blacklist_ingestion_service, service)
    override_dependency(get_settings, configured_settings())

    response = await client.post(
        "/internal/v1/blacklist/snapshots",
        json=payload(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "X-Request-ID": REQUEST_ID,
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "delivery_id": DELIVERY_ID,
        "snapshot_id": 42,
        "status": "accepted",
        "received_at": "2026-07-23T09:00:00Z",
    }
    service.ingest.assert_called_once()


@pytest.mark.anyio
async def test_duplicate_delivery_returns_200(
    client: AsyncClient, override_dependency: Any
) -> None:
    service = Mock()
    service.ingest.return_value = BlacklistIngestionResult(
        BlacklistSnapshot(snapshot_id=42), False, NOW
    )
    override_dependency(get_blacklist_ingestion_service, service)
    override_dependency(get_settings, configured_settings())

    response = await client.post(
        "/internal/v1/blacklist/snapshots",
        json=payload(),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"


@pytest.mark.anyio
async def test_invalid_authentication_is_rejected_before_ingestion(
    client: AsyncClient, override_dependency: Any
) -> None:
    service = Mock()
    override_dependency(get_blacklist_ingestion_service, service)
    override_dependency(get_settings, configured_settings())

    response = await client.post(
        "/internal/v1/blacklist/snapshots",
        json=payload(),
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_PROVIDER_CREDENTIALS"
    assert TOKEN not in response.text
    service.ingest.assert_not_called()


@pytest.mark.anyio
async def test_invalid_payload_is_rejected_before_ingestion(
    client: AsyncClient, override_dependency: Any
) -> None:
    service = Mock()
    override_dependency(get_blacklist_ingestion_service, service)
    override_dependency(get_settings, configured_settings())
    invalid = payload()
    invalid["snapshot"]["items"][0]["ip_address"] = "10.0.0.1"

    response = await client.post(
        "/internal/v1/blacklist/snapshots",
        json=invalid,
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    service.ingest.assert_not_called()
