"""Read-only application service for persisted blacklist resources."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from history_service.blacklist_repository import BlacklistRepository
from history_service.config import get_settings
from history_service.models import BlacklistSnapshot, BlacklistSyncRun
from history_service.schemas import (
    BlacklistEntryPageQuery,
    BlacklistEntryQuery,
    BlacklistEntryResponse,
    BlacklistLastError,
    BlacklistPage,
    BlacklistSnapshotList,
    BlacklistSnapshotListQuery,
    BlacklistSnapshotSummary,
    BlacklistStatusResponse,
)
from history_service.service import HistoryUnavailableError

FAILED_SYNC_STATUSES = {"failed", "rate_limited"}


class BlacklistReadService:
    """Read blacklist state from MariaDB without contacting Provider Service."""

    def __init__(
        self,
        repository: BlacklistRepository | None = None,
        *,
        stale_after_seconds: int = 43200,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository or BlacklistRepository()
        self.stale_after = timedelta(seconds=stale_after_seconds)
        self.clock = clock or (lambda: datetime.now(UTC))

    def status(self, session: Session) -> BlacklistStatusResponse:
        try:
            snapshot = self.repository.get_latest_snapshot(session)
            latest_run = self.repository.get_latest_sync_run(session)
            successful_run = self.repository.get_latest_successful_sync_run(session)
            return self._status_response(snapshot, latest_run, successful_run)
        except SQLAlchemyError as error:
            raise HistoryUnavailableError from error

    def latest(
        self, session: Session, query: BlacklistEntryQuery
    ) -> BlacklistPage | None:
        try:
            snapshot = self.repository.get_latest_snapshot(session)
            if snapshot is None:
                return None
            return self._page(session, snapshot, query)
        except SQLAlchemyError as error:
            raise HistoryUnavailableError from error

    def snapshots(
        self, session: Session, query: BlacklistSnapshotListQuery
    ) -> BlacklistSnapshotList:
        try:
            records = self.repository.list_snapshots(
                session, limit=query.limit, offset=query.offset
            )
            total = self.repository.count_snapshots(session)
            return BlacklistSnapshotList(
                items=[BlacklistSnapshotSummary.from_record(item) for item in records],
                limit=query.limit,
                offset=query.offset,
                total=total,
            )
        except SQLAlchemyError as error:
            raise HistoryUnavailableError from error

    def snapshot(
        self, session: Session, snapshot_id: int, query: BlacklistEntryPageQuery
    ) -> BlacklistPage | None:
        try:
            snapshot = self.repository.get_snapshot(session, snapshot_id)
            if snapshot is None:
                return None
            return self._page(session, snapshot, query)
        except SQLAlchemyError as error:
            raise HistoryUnavailableError from error

    def _page(
        self,
        session: Session,
        snapshot: BlacklistSnapshot,
        query: BlacklistEntryPageQuery,
    ) -> BlacklistPage:
        filters = {
            "ip_version": getattr(query, "ip_version", None),
            "minimum_score": getattr(query, "minimum_score", None),
            "country_code": getattr(query, "country_code", None),
        }
        entries = self.repository.list_entries(
            session,
            snapshot_id=snapshot.snapshot_id,
            limit=query.limit,
            offset=query.offset,
            **filters,
        )
        total = self.repository.count_entries(
            session, snapshot_id=snapshot.snapshot_id, **filters
        )
        return BlacklistPage(
            snapshot=BlacklistSnapshotSummary.from_record(snapshot),
            items=[BlacklistEntryResponse.from_record(item) for item in entries],
            limit=query.limit,
            offset=query.offset,
            total=total,
        )

    def _status_response(
        self,
        snapshot: BlacklistSnapshot | None,
        latest_run: BlacklistSyncRun | None,
        successful_run: BlacklistSyncRun | None,
    ) -> BlacklistStatusResponse:
        now = self._now()
        fetched_at = self._utc(snapshot.fetched_at) if snapshot is not None else None
        data_stale = fetched_at is not None and now - fetched_at > self.stale_after
        sync_in_progress = latest_run is not None and latest_run.status == "running"
        latest_failed = (
            latest_run is not None and latest_run.status in FAILED_SYNC_STATUSES
        )
        if sync_in_progress:
            state = "syncing"
        elif snapshot is None:
            state = "empty"
        elif latest_failed:
            state = "degraded"
        elif data_stale:
            state = "stale"
        else:
            state = "ready"

        last_error = None
        if (
            latest_failed
            and latest_run is not None
            and latest_run.error_code is not None
        ):
            last_error = BlacklistLastError(
                code=latest_run.error_code,
                message="The latest synchronization attempt failed.",
            )
        return BlacklistStatusResponse(
            state=state,
            sync_in_progress=sync_in_progress,
            latest_snapshot_id=(snapshot.snapshot_id if snapshot is not None else None),
            latest_provider_generated_at=(
                self._utc(snapshot.provider_generated_at)
                if snapshot is not None
                else None
            ),
            latest_fetched_at=fetched_at,
            last_attempt_at=(
                self._utc(latest_run.started_at) if latest_run is not None else None
            ),
            last_success_at=(
                self._utc(successful_run.finished_at)
                if successful_run is not None and successful_run.finished_at is not None
                else fetched_at
            ),
            next_attempt_at=(
                self._utc(latest_run.next_attempt_at)
                if latest_run is not None and latest_run.next_attempt_at is not None
                else None
            ),
            rate_limit_limit=(
                latest_run.rate_limit_limit if latest_run is not None else None
            ),
            rate_limit_remaining=(
                latest_run.rate_limit_remaining if latest_run is not None else None
            ),
            rate_limit_reset_at=(
                self._utc(latest_run.rate_limit_reset_at)
                if latest_run is not None and latest_run.rate_limit_reset_at is not None
                else None
            ),
            data_stale=data_stale,
            last_error=last_error,
        )

    def _now(self) -> datetime:
        return self._utc(self.clock())

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


blacklist_read_service = BlacklistReadService(
    stale_after_seconds=get_settings().blacklist_stale_after_seconds
)


def get_blacklist_read_service() -> BlacklistReadService:
    return blacklist_read_service
