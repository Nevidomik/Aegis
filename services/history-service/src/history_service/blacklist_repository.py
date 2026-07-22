"""Persistence operations for complete blacklist snapshots and sync runs."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from history_service.models import (
    BlacklistSnapshot,
    BlacklistSnapshotEntry,
    BlacklistSyncRun,
)

TEMPORARY_SYNC_ERROR_CODES = {
    "PROVIDER_SERVICE_UNAVAILABLE",
    "UPSTREAM_UNAVAILABLE",
    "PROVIDER_UNAVAILABLE",
    "UPSTREAM_TIMEOUT",
    "PROVIDER_TIMEOUT",
    "DATABASE_UNAVAILABLE",
}


@dataclass(frozen=True)
class PersistedBlacklistSchedule:
    status: str
    next_attempt_at: datetime | None
    next_attempt_reason: str | None
    rate_limit_remaining: int | None
    rate_limit_reset_at: datetime | None


class BlacklistRepository:
    """Query and mutate blacklist records through a supplied session."""

    def add_snapshot(
        self,
        session: Session,
        snapshot: BlacklistSnapshot,
        entries: list[BlacklistSnapshotEntry],
    ) -> BlacklistSnapshot:
        snapshot.provider_generated_at = self._as_mariadb_utc(
            snapshot.provider_generated_at
        )
        snapshot.fetched_at = self._as_mariadb_utc(snapshot.fetched_at)
        snapshot.rate_limit_reset_at = self._as_mariadb_utc(
            snapshot.rate_limit_reset_at
        )
        for entry in entries:
            entry.last_reported_at = self._as_mariadb_utc(entry.last_reported_at)
        snapshot.entries.extend(entries)
        session.add(snapshot)
        session.flush()
        return snapshot

    def get_by_provider_generation(
        self,
        session: Session,
        *,
        provider: str,
        provider_generated_at: datetime,
    ) -> BlacklistSnapshot | None:
        statement = select(BlacklistSnapshot).where(
            BlacklistSnapshot.provider == provider,
            BlacklistSnapshot.provider_generated_at
            == self._as_mariadb_utc(provider_generated_at),
        )
        return session.scalar(statement)

    def get_snapshot(
        self, session: Session, snapshot_id: int
    ) -> BlacklistSnapshot | None:
        return session.get(BlacklistSnapshot, snapshot_id)

    def get_latest_snapshot(self, session: Session) -> BlacklistSnapshot | None:
        statement = (
            select(BlacklistSnapshot)
            .order_by(BlacklistSnapshot.snapshot_id.desc())
            .limit(1)
        )
        return session.scalar(statement)

    def list_snapshots(
        self, session: Session, *, limit: int, offset: int
    ) -> list[BlacklistSnapshot]:
        statement = (
            select(BlacklistSnapshot)
            .order_by(BlacklistSnapshot.snapshot_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(session.scalars(statement))

    def count_snapshots(self, session: Session) -> int:
        statement = select(func.count()).select_from(BlacklistSnapshot)
        return session.scalar(statement) or 0

    def list_entries(
        self,
        session: Session,
        *,
        snapshot_id: int,
        limit: int,
        offset: int,
        ip_version: int | None = None,
        minimum_score: int | None = None,
        country_code: str | None = None,
    ) -> list[BlacklistSnapshotEntry]:
        statement = select(BlacklistSnapshotEntry).where(
            BlacklistSnapshotEntry.snapshot_id == snapshot_id
        )
        statement = self._filter_entries(
            statement,
            ip_version=ip_version,
            minimum_score=minimum_score,
            country_code=country_code,
        )
        statement = (
            statement.order_by(
                BlacklistSnapshotEntry.abuse_confidence_score.desc(),
                BlacklistSnapshotEntry.last_reported_at.desc(),
                BlacklistSnapshotEntry.ip_address.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(session.scalars(statement))

    def count_entries(
        self,
        session: Session,
        *,
        snapshot_id: int,
        ip_version: int | None = None,
        minimum_score: int | None = None,
        country_code: str | None = None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(BlacklistSnapshotEntry)
            .where(BlacklistSnapshotEntry.snapshot_id == snapshot_id)
        )
        statement = self._filter_entries(
            statement,
            ip_version=ip_version,
            minimum_score=minimum_score,
            country_code=country_code,
        )
        return session.scalar(statement) or 0

    @staticmethod
    def _filter_entries(
        statement,
        *,
        ip_version: int | None,
        minimum_score: int | None,
        country_code: str | None,
    ):
        if ip_version is not None:
            statement = statement.where(BlacklistSnapshotEntry.ip_version == ip_version)
        if minimum_score is not None:
            statement = statement.where(
                BlacklistSnapshotEntry.abuse_confidence_score >= minimum_score
            )
        if country_code is not None:
            statement = statement.where(
                BlacklistSnapshotEntry.country_code == country_code
            )
        return statement

    def add_sync_run(self, session: Session, run: BlacklistSyncRun) -> BlacklistSyncRun:
        for field_name in (
            "started_at",
            "finished_at",
            "rate_limit_reset_at",
            "next_attempt_at",
        ):
            setattr(run, field_name, self._as_mariadb_utc(getattr(run, field_name)))
        session.add(run)
        session.flush()
        return run

    def get_latest_sync_run(self, session: Session) -> BlacklistSyncRun | None:
        statement = (
            select(BlacklistSyncRun)
            .order_by(BlacklistSyncRun.sync_run_id.desc())
            .limit(1)
        )
        return session.scalar(statement)

    def get_latest_successful_sync_run(
        self, session: Session
    ) -> BlacklistSyncRun | None:
        statement = (
            select(BlacklistSyncRun)
            .where(BlacklistSyncRun.status.in_(("succeeded", "duplicate")))
            .order_by(BlacklistSyncRun.sync_run_id.desc())
            .limit(1)
        )
        return session.scalar(statement)

    def get_sync_run_for_update(
        self, session: Session, sync_run_id: int
    ) -> BlacklistSyncRun | None:
        statement = (
            select(BlacklistSyncRun)
            .where(BlacklistSyncRun.sync_run_id == sync_run_id)
            .with_for_update()
        )
        return session.scalar(statement)

    def count_consecutive_temporary_failures(
        self, session: Session, *, before_sync_run_id: int, maximum: int
    ) -> int:
        statement = (
            select(BlacklistSyncRun.status, BlacklistSyncRun.error_code)
            .where(BlacklistSyncRun.sync_run_id < before_sync_run_id)
            .order_by(BlacklistSyncRun.sync_run_id.desc())
            .limit(maximum)
        )
        count = 0
        for status, error_code in session.execute(statement):
            if status != "failed" or error_code not in TEMPORARY_SYNC_ERROR_CODES:
                break
            count += 1
        return count

    def get_persisted_schedule(
        self, session: Session
    ) -> PersistedBlacklistSchedule | None:
        run = self.get_latest_sync_run(session)
        if run is None:
            return None
        return PersistedBlacklistSchedule(
            status=run.status,
            next_attempt_at=self._as_aware_utc(run.next_attempt_at),
            next_attempt_reason=run.next_attempt_reason,
            rate_limit_remaining=run.rate_limit_remaining,
            rate_limit_reset_at=self._as_aware_utc(run.rate_limit_reset_at),
        )

    @staticmethod
    def _as_mariadb_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Blacklist timestamps must include a timezone.")
        return value.astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def _as_aware_utc(value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None
