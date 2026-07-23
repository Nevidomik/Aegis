from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest
from history_service.blacklist_ingestion import BlacklistIngestionService
from history_service.blacklist_repository import BlacklistRepository
from history_service.models import BlacklistSnapshot
from history_service.schemas import BlacklistSnapshotDelivery
from history_service.service import HistoryUnavailableError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

DELIVERY_ID = "662ecba0-8918-433d-bc75-b14de17851f1"
GENERATED_AT = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 7, 23, 9, 0, 2, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 7, 23, 9, 0, 3, tzinfo=UTC)


def item(address: str, score: int = 100) -> dict[str, Any]:
    return {
        "ip_address": address,
        "ip_version": 6 if ":" in address else 4,
        "abuse_confidence_score": score,
        "country_code": "US",
        "last_reported_at": FETCHED_AT.isoformat(),
    }


def delivery(
    items: list[dict[str, Any]] | None = None,
) -> BlacklistSnapshotDelivery:
    return BlacklistSnapshotDelivery.model_validate(
        {
            "delivery_id": DELIVERY_ID,
            "snapshot": {
                "provider": "AbuseIPDB",
                "generated_at": GENERATED_AT.isoformat(),
                "fetched_at": FETCHED_AT.isoformat(),
                "request": {"confidence_minimum": 90, "limit": 1000},
                "rate_limit": {"limit": 5, "remaining": 4},
                "items": items if items is not None else [item("8.8.8.8")],
            },
        }
    )


def test_valid_ingestion_commits_snapshot_and_entries_transactionally() -> None:
    session = Mock(spec=Session)
    repository = Mock(spec=BlacklistRepository)
    repository.get_by_delivery_id.return_value = None
    repository.get_previous_snapshot_ip_addresses.return_value = None
    service = BlacklistIngestionService(
        repository=repository, clock=lambda: RECEIVED_AT
    )

    result = service.ingest(session, delivery())

    assert result.created is True
    assert result.received_at == RECEIVED_AT
    snapshot, entries = repository.add_snapshot.call_args.args[1:]
    assert snapshot.delivery_id == DELIVERY_ID
    assert snapshot.fetched_at == FETCHED_AT
    assert snapshot.received_at == RECEIVED_AT
    assert snapshot.returned_count == 1
    assert snapshot.added_count is None
    assert snapshot.removed_count is None
    assert snapshot.turnover_percent is None
    assert entries[0].ip_address == "8.8.8.8"
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()


def test_duplicate_delivery_returns_existing_snapshot_without_writes() -> None:
    session = Mock(spec=Session)
    repository = Mock(spec=BlacklistRepository)
    existing = BlacklistSnapshot(
        snapshot_id=41,
        delivery_id=DELIVERY_ID,
        provider="AbuseIPDB",
        provider_generated_at=GENERATED_AT.replace(tzinfo=None),
        fetched_at=FETCHED_AT.replace(tzinfo=None),
        received_at=RECEIVED_AT.replace(tzinfo=None),
        confidence_minimum=90,
        requested_limit=1000,
        returned_count=1,
    )
    repository.get_by_delivery_id.return_value = existing
    repository._as_aware_utc.return_value = RECEIVED_AT
    service = BlacklistIngestionService(repository=repository)

    result = service.ingest(session, delivery())

    assert result.created is False
    assert result.snapshot is existing
    repository.add_snapshot.assert_not_called()
    repository.get_previous_snapshot_ip_addresses.assert_not_called()
    session.commit.assert_not_called()


def test_database_failure_rolls_back_whole_delivery() -> None:
    session = Mock(spec=Session)
    repository = Mock(spec=BlacklistRepository)
    repository.get_by_delivery_id.return_value = None
    repository.get_previous_snapshot_ip_addresses.return_value = None
    repository.add_snapshot.side_effect = OperationalError(
        "INSERT", {}, RuntimeError("database unavailable")
    )
    service = BlacklistIngestionService(
        repository=repository, clock=lambda: RECEIVED_AT
    )

    with pytest.raises(HistoryUnavailableError):
        service.ingest(session, delivery())

    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("previous", "current", "added", "removed", "turnover"),
    [
        (
            {"8.8.8.8", "1.1.1.1"},
            ["8.8.8.8", "1.1.1.1"],
            0,
            0,
            Decimal("0.00"),
        ),
        (
            {"8.8.8.8", "1.1.1.1"},
            ["9.9.9.9", "208.67.222.222"],
            2,
            2,
            Decimal("100.00"),
        ),
        (
            {"8.8.8.8", "1.1.1.1", "9.9.9.9"},
            ["8.8.8.8", "1.1.1.1", "208.67.222.222"],
            1,
            1,
            Decimal("33.33"),
        ),
    ],
)
def test_change_metrics_compare_unique_ip_sets(
    previous: set[str],
    current: list[str],
    added: int,
    removed: int,
    turnover: Decimal,
) -> None:
    session = Mock(spec=Session)
    repository = Mock(spec=BlacklistRepository)
    repository.get_by_delivery_id.return_value = None
    repository.get_previous_snapshot_ip_addresses.return_value = previous
    service = BlacklistIngestionService(
        repository=repository, clock=lambda: RECEIVED_AT
    )

    service.ingest(session, delivery([item(address) for address in current]))

    snapshot = repository.add_snapshot.call_args.args[1]
    assert snapshot.added_count == added
    assert snapshot.removed_count == removed
    assert snapshot.turnover_percent == turnover


def test_duplicate_payload_ips_are_deduplicated_before_metrics_and_storage() -> None:
    session = Mock(spec=Session)
    repository = Mock(spec=BlacklistRepository)
    repository.get_by_delivery_id.return_value = None
    repository.get_previous_snapshot_ip_addresses.return_value = {"1.1.1.1"}
    service = BlacklistIngestionService(
        repository=repository, clock=lambda: RECEIVED_AT
    )

    service.ingest(
        session,
        delivery(
            [
                item("8.8.8.8", 90),
                item("8.8.8.8", 100),
                item("1.1.1.1"),
            ]
        ),
    )

    snapshot, entries = repository.add_snapshot.call_args.args[1:]
    assert snapshot.returned_count == 2
    assert snapshot.added_count == 1
    assert snapshot.removed_count == 0
    assert snapshot.turnover_percent == Decimal("50.00")
    assert [entry.ip_address for entry in entries] == ["8.8.8.8", "1.1.1.1"]
    assert entries[0].abuse_confidence_score == 100


def test_turnover_percentage_rounds_half_up_to_two_decimal_places() -> None:
    current = [
        "8.8.8.8",
        "1.1.1.1",
        "9.9.9.9",
        "208.67.222.222",
        "8.8.4.4",
        "1.0.0.1",
    ]
    session = Mock(spec=Session)
    repository = Mock(spec=BlacklistRepository)
    repository.get_by_delivery_id.return_value = None
    repository.get_previous_snapshot_ip_addresses.return_value = set(current[:-1])
    service = BlacklistIngestionService(
        repository=repository, clock=lambda: RECEIVED_AT
    )

    service.ingest(session, delivery([item(address) for address in current]))

    snapshot = repository.add_snapshot.call_args.args[1]
    assert snapshot.added_count == 1
    assert snapshot.turnover_percent == Decimal("16.67")
