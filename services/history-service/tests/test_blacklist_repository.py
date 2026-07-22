from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from history_service.blacklist_repository import BlacklistRepository
from history_service.models import (
    Base,
    BlacklistSnapshot,
    BlacklistSnapshotEntry,
    BlacklistSyncRun,
)
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

GENERATED_AT = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
FETCHED_AT = datetime(2026, 7, 22, 12, 0, 2, tzinfo=UTC)


def snapshot() -> BlacklistSnapshot:
    return BlacklistSnapshot(
        provider="AbuseIPDB",
        provider_generated_at=GENERATED_AT,
        fetched_at=FETCHED_AT,
        confidence_minimum=90,
        requested_limit=1000,
        returned_count=2,
        rate_limit_limit=5,
        rate_limit_remaining=4,
    )


def entries() -> list[BlacklistSnapshotEntry]:
    return [
        BlacklistSnapshotEntry(
            ip_address="8.8.8.8",
            ip_version=4,
            abuse_confidence_score=100,
            country_code="US",
            last_reported_at=FETCHED_AT,
        ),
        BlacklistSnapshotEntry(
            ip_address="2606:4700:4700::1111",
            ip_version=6,
            abuse_confidence_score=95,
            country_code=None,
            last_reported_at=None,
        ),
    ]


def test_add_snapshot_builds_relationship_and_flushes_without_commit() -> None:
    session = Mock(spec=Session)
    record = snapshot()
    records = entries()

    result = BlacklistRepository().add_snapshot(session, record, records)

    assert result is record
    assert record.entries == records
    assert all(entry.snapshot is record for entry in records)
    assert record.provider_generated_at == GENERATED_AT.replace(tzinfo=None)
    assert record.fetched_at == FETCHED_AT.replace(tzinfo=None)
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_duplicate_constraints_and_foreign_key_cascades_are_declared() -> None:
    snapshots = Base.metadata.tables["blacklist_snapshots"]
    entries_table = Base.metadata.tables["blacklist_snapshot_entries"]
    runs = Base.metadata.tables["blacklist_sync_runs"]

    assert any(
        index.name == "uq_blacklist_snapshots_provider_generated" and index.unique
        for index in snapshots.indexes
    )
    assert any(
        index.name == "uq_blacklist_entries_snapshot_ip" and index.unique
        for index in entries_table.indexes
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and [column.name for column in constraint.columns] == ["request_id"]
        for constraint in runs.constraints
    )

    entry_fk = next(iter(entries_table.foreign_keys))
    run_fk = next(iter(runs.foreign_keys))
    assert entry_fk.ondelete == "CASCADE"
    assert run_fk.ondelete == "SET NULL"


def test_entry_query_uses_documented_ordering_and_pagination() -> None:
    session = Mock(spec=Session)
    session.scalars.return_value = []

    result = BlacklistRepository().list_entries(
        session, snapshot_id=42, limit=100, offset=10
    )

    assert result == []
    statement = session.scalars.call_args.args[0]
    sql = str(statement)
    assert "abuse_confidence_score DESC" in sql
    assert "last_reported_at DESC" in sql
    assert "ip_address ASC" in sql
    assert statement._limit_clause.value == 100
    assert statement._offset_clause.value == 10


def test_entry_queries_apply_all_filters_to_page_and_count() -> None:
    session = Mock(spec=Session)
    session.scalars.return_value = []
    session.scalar.return_value = 0
    repository = BlacklistRepository()

    repository.list_entries(
        session,
        snapshot_id=42,
        limit=100,
        offset=0,
        ip_version=6,
        minimum_score=95,
        country_code="US",
    )
    repository.count_entries(
        session,
        snapshot_id=42,
        ip_version=6,
        minimum_score=95,
        country_code="US",
    )

    page_sql = str(session.scalars.call_args.args[0])
    count_sql = str(session.scalar.call_args.args[0])
    for sql in (page_sql, count_sql):
        assert "ip_version" in sql
        assert "abuse_confidence_score" in sql
        assert "country_code" in sql


def test_snapshot_query_uses_descending_identity_and_pagination() -> None:
    session = Mock(spec=Session)
    session.scalars.return_value = []

    BlacklistRepository().list_snapshots(session, limit=20, offset=40)

    statement = session.scalars.call_args.args[0]
    assert "snapshot_id DESC" in str(statement)
    assert statement._limit_clause.value == 20
    assert statement._offset_clause.value == 40


def test_failed_flush_is_rolled_back_by_transaction_owner() -> None:
    session = Mock(spec=Session)
    session.flush.side_effect = IntegrityError("insert", {}, Exception("duplicate"))

    with pytest.raises(IntegrityError):
        BlacklistRepository().add_snapshot(session, snapshot(), entries())
    session.rollback()

    session.rollback.assert_called_once_with()
    session.commit.assert_not_called()


def test_sync_run_relationship_and_timestamp_normalization() -> None:
    session = Mock(spec=Session)
    record = snapshot()
    run = BlacklistSyncRun(
        request_id="6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
        status="succeeded",
        started_at=GENERATED_AT,
        finished_at=FETCHED_AT,
        confidence_minimum=90,
        requested_limit=1000,
        snapshot=record,
    )

    BlacklistRepository().add_sync_run(session, run)

    assert run.snapshot is record
    assert run in record.sync_runs
    assert run.started_at == GENERATED_AT.replace(tzinfo=None)
    assert run.finished_at == FETCHED_AT.replace(tzinfo=None)
    session.add.assert_called_once_with(run)
    session.flush.assert_called_once_with()
