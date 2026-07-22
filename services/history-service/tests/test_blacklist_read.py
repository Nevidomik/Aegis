from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from history_service.blacklist_read import BlacklistReadService
from history_service.models import (
    BlacklistSnapshot,
    BlacklistSnapshotEntry,
    BlacklistSyncRun,
)
from history_service.schemas import BlacklistEntryQuery, BlacklistSnapshotListQuery

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def snapshot(*, snapshot_id: int = 42, age_hours: int = 1) -> BlacklistSnapshot:
    generated = NOW - timedelta(hours=age_hours)
    return BlacklistSnapshot(
        snapshot_id=snapshot_id,
        provider="AbuseIPDB",
        provider_generated_at=generated.replace(tzinfo=None),
        fetched_at=(generated + timedelta(seconds=2)).replace(tzinfo=None),
        confidence_minimum=90,
        requested_limit=1000,
        returned_count=2,
    )


def entry(address: str, score: int) -> BlacklistSnapshotEntry:
    return BlacklistSnapshotEntry(
        entry_id=score,
        snapshot_id=42,
        ip_address=address,
        ip_version=6 if ":" in address else 4,
        abuse_confidence_score=score,
        country_code="US",
        last_reported_at=NOW.replace(tzinfo=None),
    )


def sync_run(status: str, *, error_code: str | None = None) -> BlacklistSyncRun:
    return BlacklistSyncRun(
        sync_run_id=7,
        request_id="6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
        status=status,
        started_at=(NOW - timedelta(minutes=1)).replace(tzinfo=None),
        finished_at=NOW.replace(tzinfo=None) if status != "running" else None,
        confidence_minimum=90,
        requested_limit=1000,
        next_attempt_at=(NOW + timedelta(hours=6)).replace(tzinfo=None),
        rate_limit_limit=5,
        rate_limit_remaining=4,
        error_code=error_code,
        error_message="database details that must never be returned",
    )


@pytest.mark.parametrize(
    ("record", "run", "age_hours", "expected_state", "stale"),
    [
        (None, None, 1, "empty", False),
        (None, sync_run("running"), 1, "syncing", False),
        (snapshot(), sync_run("succeeded"), 1, "ready", False),
        (snapshot(), sync_run("running"), 1, "syncing", False),
        (snapshot(age_hours=13), sync_run("succeeded"), 13, "stale", True),
        (
            snapshot(),
            sync_run("failed", error_code="UPSTREAM_TIMEOUT"),
            1,
            "degraded",
            False,
        ),
    ],
)
def test_status_states(
    record: BlacklistSnapshot | None,
    run: BlacklistSyncRun | None,
    age_hours: int,
    expected_state: str,
    stale: bool,
) -> None:
    repository = Mock()
    repository.get_latest_snapshot.return_value = record
    repository.get_latest_sync_run.return_value = run
    repository.get_latest_successful_sync_run.return_value = (
        sync_run("succeeded") if record is not None else None
    )
    service = BlacklistReadService(
        repository, stale_after_seconds=43200, clock=lambda: NOW
    )

    result = service.status(Mock())

    assert result.state == expected_state
    assert result.data_stale is stale
    if expected_state == "degraded":
        assert result.latest_snapshot_id == 42
        assert result.last_error is not None
        assert result.last_error.code == "UPSTREAM_TIMEOUT"
        assert "database details" not in result.last_error.message


def test_latest_snapshot_filters_paginates_and_uses_constant_query_count() -> None:
    repository = Mock()
    repository.get_latest_snapshot.return_value = snapshot()
    repository.list_entries.return_value = [
        entry("8.8.8.8", 100),
        entry("2606:4700:4700::1111", 95),
    ]
    repository.count_entries.return_value = 12
    service = BlacklistReadService(repository, clock=lambda: NOW)
    query = BlacklistEntryQuery(
        limit=2, offset=4, ip_version=4, minimum_score=95, country_code="US"
    )

    result = service.latest(Mock(), query)

    assert result is not None
    assert len(result.items) == 2
    assert result.total == 12
    repository.get_latest_snapshot.assert_called_once()
    repository.list_entries.assert_called_once_with(
        repository.get_latest_snapshot.call_args.args[0],
        snapshot_id=42,
        limit=2,
        offset=4,
        ip_version=4,
        minimum_score=95,
        country_code="US",
    )
    repository.count_entries.assert_called_once()
    assert (
        sum(
            method.call_count
            for method in (
                repository.get_latest_snapshot,
                repository.list_entries,
                repository.count_entries,
            )
        )
        == 3
    )


def test_snapshot_lists_are_paginated_and_ordered_by_repository() -> None:
    repository = Mock()
    repository.list_snapshots.return_value = [snapshot(snapshot_id=43), snapshot()]
    repository.count_snapshots.return_value = 9
    service = BlacklistReadService(repository, clock=lambda: NOW)

    result = service.snapshots(Mock(), BlacklistSnapshotListQuery(limit=2, offset=2))

    assert [item.snapshot_id for item in result.items] == [43, 42]
    assert result.total == 9
    repository.list_snapshots.assert_called_once()
    repository.count_snapshots.assert_called_once()


def test_empty_latest_and_missing_snapshot_return_none() -> None:
    repository = Mock()
    repository.get_latest_snapshot.return_value = None
    repository.get_snapshot.return_value = None
    service = BlacklistReadService(repository, clock=lambda: NOW)
    query = BlacklistEntryQuery()

    assert service.latest(Mock(), query) is None
    assert service.snapshot(Mock(), 999, query) is None
    repository.list_entries.assert_not_called()
    repository.count_entries.assert_not_called()
