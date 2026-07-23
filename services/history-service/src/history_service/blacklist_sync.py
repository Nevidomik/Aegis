"""One-shot blacklist synchronization orchestration."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from random import SystemRandom
from typing import Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from history_service.blacklist_policy import (
    BlacklistNextAttemptPolicy,
    NextAttemptDecision,
    SchedulingReason,
)
from history_service.blacklist_repository import BlacklistRepository
from history_service.exceptions import ApplicationError
from history_service.models import (
    BlacklistSnapshot,
    BlacklistSnapshotEntry,
    BlacklistSyncRun,
)
from history_service.schemas import (
    ProviderBlacklistRequest,
    ProviderBlacklistResponse,
)
from history_service.security_logging import safe_persisted_error_message

SyncStatus = Literal[
    "succeeded", "duplicate", "rate_limited", "failed", "already_running"
]


class BlacklistProviderGateway(Protocol):
    def get_blacklist(
        self, query: ProviderBlacklistRequest, *, request_id: str
    ) -> ProviderBlacklistResponse: ...


class SyncLock(Protocol):
    def acquire(self) -> AbstractContextManager[bool]: ...


class MariaDBBlacklistSyncLock:
    """Serialize blacklist mutations with a connection-scoped MariaDB lock."""

    def __init__(
        self, engine: Engine, lock_name: str = "aegis:history:blacklist-sync"
    ) -> None:
        self.engine = engine
        self.lock_name = lock_name

    @contextmanager
    def acquire(self) -> Iterator[bool]:
        with self.engine.connect() as connection:
            acquired = (
                connection.scalar(
                    text("SELECT GET_LOCK(:lock_name, 0)"),
                    {"lock_name": self.lock_name},
                )
                == 1
            )
            try:
                yield acquired
            finally:
                if acquired:
                    connection.scalar(
                        text("SELECT RELEASE_LOCK(:lock_name)"),
                        {"lock_name": self.lock_name},
                    )


@dataclass(frozen=True)
class BlacklistSyncResult:
    request_id: UUID
    sync_run_id: int | None
    status: SyncStatus
    snapshot_id: int | None
    started_at: datetime
    finished_at: datetime
    next_attempt_at: datetime | None
    next_attempt_reason: SchedulingReason | None
    error_code: str | None


class BlacklistSyncInfrastructureError(Exception):
    """Raised when MariaDB cannot reliably record synchronization state."""


SAFE_ERROR_MESSAGES = {
    "PROVIDER_SERVICE_UNAVAILABLE": (
        "Provider Service was unavailable during blacklist synchronization."
    ),
    "PROVIDER_SERVICE_INVALID_RESPONSE": (
        "Provider Service returned an invalid blacklist response."
    ),
    "RATE_LIMIT_EXCEEDED": (
        "The provider rate limit prevented blacklist synchronization."
    ),
    "UPSTREAM_UNAVAILABLE": "The reputation provider was temporarily unavailable.",
    "UPSTREAM_TIMEOUT": (
        "The reputation provider timed out during blacklist synchronization."
    ),
    "UPSTREAM_AUTHENTICATION_FAILED": (
        "The reputation provider rejected its credentials."
    ),
    "UPSTREAM_INVALID_RESPONSE": (
        "The reputation provider returned an invalid response."
    ),
    "UPSTREAM_REQUEST_REJECTED": (
        "The reputation provider rejected the blacklist request."
    ),
    "DATABASE_UNAVAILABLE": "Blacklist synchronization could not be saved.",
}


class BlacklistSyncService:
    """Perform exactly one coordinated blacklist synchronization attempt."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        sync_lock: SyncLock,
        confidence_minimum: int = 90,
        repository: BlacklistRepository | None = None,
        policy: BlacklistNextAttemptPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
        request_id_factory: Callable[[], UUID] | None = None,
        jitter_factory: Callable[[int], int] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.sync_lock = sync_lock
        self.confidence_minimum = confidence_minimum
        self.repository = repository or BlacklistRepository()
        self.policy = policy or BlacklistNextAttemptPolicy(
            interval_seconds=21600, maximum_jitter_seconds=0
        )
        self.clock = clock or (lambda: datetime.now(UTC))
        self.request_id_factory = request_id_factory or uuid4
        random = SystemRandom()
        self.jitter_factory = jitter_factory or (
            lambda maximum: random.randint(0, maximum)
        )

    def run_once(self, provider: BlacklistProviderGateway) -> BlacklistSyncResult:
        request_id = self.request_id_factory()
        started_at = self._now()
        with self.sync_lock.acquire() as acquired:
            if not acquired:
                return BlacklistSyncResult(
                    request_id=request_id,
                    sync_run_id=None,
                    status="already_running",
                    snapshot_id=None,
                    started_at=started_at,
                    finished_at=started_at,
                    next_attempt_at=None,
                    next_attempt_reason=None,
                    error_code="BLACKLIST_SYNC_ALREADY_RUNNING",
                )

            sync_run_id = self._register_run(request_id, started_at)
            query = ProviderBlacklistRequest(
                confidence_minimum=self.confidence_minimum, limit=1000
            )
            try:
                response = provider.get_blacklist(query, request_id=str(request_id))
            except ApplicationError as error:
                return self._finalize_provider_failure(
                    request_id=request_id,
                    sync_run_id=sync_run_id,
                    started_at=started_at,
                    error=error,
                )

            if len(response.items) > 1000:
                validation_error = ApplicationError(
                    status_code=502,
                    code="PROVIDER_SERVICE_INVALID_RESPONSE",
                    message="Provider Service returned an invalid blacklist response.",
                )
                return self._finalize_provider_failure(
                    request_id=request_id,
                    sync_run_id=sync_run_id,
                    started_at=started_at,
                    error=validation_error,
                )
            return self._persist_response(
                request_id=request_id,
                sync_run_id=sync_run_id,
                started_at=started_at,
                response=response,
            )

    def _register_run(self, request_id: UUID, started_at: datetime) -> int:
        with self.session_factory() as session:
            try:
                run = BlacklistSyncRun(
                    request_id=str(request_id),
                    status="running",
                    started_at=started_at,
                    confidence_minimum=self.confidence_minimum,
                    requested_limit=1000,
                )
                self.repository.add_sync_run(session, run)
                session.commit()
                return run.sync_run_id
            except SQLAlchemyError as error:
                session.rollback()
                raise BlacklistSyncInfrastructureError from error

    def _persist_response(
        self,
        *,
        request_id: UUID,
        sync_run_id: int,
        started_at: datetime,
        response: ProviderBlacklistResponse,
    ) -> BlacklistSyncResult:
        finished_at = self._now()
        decision = self.policy.after_success(
            finished_at,
            remaining=response.rate_limit.remaining,
            reset_at=response.rate_limit.reset_at,
            retry_after_seconds=response.rate_limit.retry_after_seconds,
            jitter_seconds=self._jitter(),
        )
        with self.session_factory() as session:
            try:
                run = self._load_run(session, sync_run_id)
                existing = self.repository.get_by_provider_generation(
                    session,
                    provider=response.provider,
                    provider_generated_at=response.generated_at,
                )
                if existing is not None:
                    self._finish_run(
                        run,
                        status="duplicate",
                        finished_at=finished_at,
                        decision=decision,
                        snapshot_id=existing.snapshot_id,
                        response=response,
                    )
                    session.commit()
                    return self._result(
                        request_id,
                        sync_run_id,
                        "duplicate",
                        existing.snapshot_id,
                        started_at,
                        finished_at,
                        decision,
                    )

                snapshot = BlacklistSnapshot(
                    provider=response.provider,
                    provider_generated_at=response.generated_at,
                    fetched_at=response.fetched_at,
                    confidence_minimum=response.request.confidence_minimum,
                    requested_limit=response.request.limit,
                    returned_count=len(response.items),
                    rate_limit_limit=response.rate_limit.limit,
                    rate_limit_remaining=response.rate_limit.remaining,
                    rate_limit_reset_at=response.rate_limit.reset_at,
                    retry_after_seconds=response.rate_limit.retry_after_seconds,
                )
                entries = [
                    BlacklistSnapshotEntry(
                        ip_address=item.ip_address,
                        ip_version=item.ip_version,
                        abuse_confidence_score=item.abuse_confidence_score,
                        country_code=item.country_code,
                        last_reported_at=item.last_reported_at,
                    )
                    for item in response.items
                ]
                self.repository.add_snapshot(session, snapshot, entries)
                self._finish_run(
                    run,
                    status="succeeded",
                    finished_at=finished_at,
                    decision=decision,
                    snapshot_id=snapshot.snapshot_id,
                    response=response,
                )
                session.commit()
                return self._result(
                    request_id,
                    sync_run_id,
                    "succeeded",
                    snapshot.snapshot_id,
                    started_at,
                    finished_at,
                    decision,
                )
            except SQLAlchemyError as error:
                session.rollback()
                return self._finalize_database_failure(
                    request_id=request_id,
                    sync_run_id=sync_run_id,
                    started_at=started_at,
                    cause=error,
                )

    def _finalize_provider_failure(
        self,
        *,
        request_id: UUID,
        sync_run_id: int,
        started_at: datetime,
        error: ApplicationError,
    ) -> BlacklistSyncResult:
        finished_at = self._now()
        is_rate_limited = error.code == "RATE_LIMIT_EXCEEDED"
        status: Literal["rate_limited", "failed"] = (
            "rate_limited" if is_rate_limited else "failed"
        )
        if is_rate_limited:
            decision = self.policy.after_rate_limit(
                finished_at,
                retry_after_seconds=error.retry_after_seconds,
                reset_at=error.reset_at,
                jitter_seconds=self._jitter(),
            )
        else:
            temporary = error.status_code in {503, 504}
            if temporary:
                decision = self.policy.after_temporary_failure(
                    finished_at,
                    attempt=self._temporary_attempt(sync_run_id),
                    reset_at=error.reset_at,
                    jitter_seconds=self._jitter(),
                )
            else:
                decision = self.policy.after_invalid_response(
                    finished_at, jitter_seconds=self._jitter()
                )
        with self.session_factory() as session:
            try:
                run = self._load_run(session, sync_run_id)
                run.status = status
                run.finished_at = self.repository._as_mariadb_utc(finished_at)
                run.provider_http_status = error.status_code
                run.retry_after_seconds = error.retry_after_seconds
                run.rate_limit_reset_at = self.repository._as_mariadb_utc(
                    error.reset_at
                )
                run.next_attempt_at = self.repository._as_mariadb_utc(
                    decision.next_attempt_at
                )
                run.next_attempt_reason = decision.reason
                run.error_code = error.code
                run.error_message = safe_persisted_error_message(
                    SAFE_ERROR_MESSAGES.get(
                        error.code, "Blacklist synchronization failed."
                    )
                )
                session.commit()
            except SQLAlchemyError as database_error:
                session.rollback()
                raise BlacklistSyncInfrastructureError from database_error
        return self._result(
            request_id,
            sync_run_id,
            status,
            None,
            started_at,
            finished_at,
            decision,
            error.code,
        )

    def _finalize_database_failure(
        self,
        *,
        request_id: UUID,
        sync_run_id: int,
        started_at: datetime,
        cause: SQLAlchemyError,
    ) -> BlacklistSyncResult:
        finished_at = self._now()
        decision = self.policy.after_temporary_failure(
            finished_at, attempt=1, jitter_seconds=self._jitter()
        )
        with self.session_factory() as session:
            try:
                run = self._load_run(session, sync_run_id)
                run.status = "failed"
                run.finished_at = self.repository._as_mariadb_utc(finished_at)
                run.next_attempt_at = self.repository._as_mariadb_utc(
                    decision.next_attempt_at
                )
                run.next_attempt_reason = decision.reason
                run.error_code = "DATABASE_UNAVAILABLE"
                run.error_message = safe_persisted_error_message(
                    SAFE_ERROR_MESSAGES["DATABASE_UNAVAILABLE"]
                )
                session.commit()
            except SQLAlchemyError as finalization_error:
                session.rollback()
                raise BlacklistSyncInfrastructureError from finalization_error
        _ = cause
        return self._result(
            request_id,
            sync_run_id,
            "failed",
            None,
            started_at,
            finished_at,
            decision,
            "DATABASE_UNAVAILABLE",
        )

    def _load_run(self, session: Session, sync_run_id: int) -> BlacklistSyncRun:
        run = self.repository.get_sync_run_for_update(session, sync_run_id)
        if run is None:
            raise BlacklistSyncInfrastructureError("Synchronization run disappeared.")
        return run

    def _finish_run(
        self,
        run: BlacklistSyncRun,
        *,
        status: Literal["succeeded", "duplicate"],
        finished_at: datetime,
        decision: NextAttemptDecision,
        snapshot_id: int,
        response: ProviderBlacklistResponse,
    ) -> None:
        run.status = status
        run.finished_at = self.repository._as_mariadb_utc(finished_at)
        run.snapshot_id = snapshot_id
        run.rate_limit_limit = response.rate_limit.limit
        run.rate_limit_remaining = response.rate_limit.remaining
        run.rate_limit_reset_at = self.repository._as_mariadb_utc(
            response.rate_limit.reset_at
        )
        run.retry_after_seconds = response.rate_limit.retry_after_seconds
        run.next_attempt_at = self.repository._as_mariadb_utc(decision.next_attempt_at)
        run.next_attempt_reason = decision.reason
        run.error_code = None
        run.error_message = None

    @staticmethod
    def _result(
        request_id: UUID,
        sync_run_id: int,
        status: SyncStatus,
        snapshot_id: int | None,
        started_at: datetime,
        finished_at: datetime,
        decision: NextAttemptDecision | None,
        error_code: str | None = None,
    ) -> BlacklistSyncResult:
        return BlacklistSyncResult(
            request_id=request_id,
            sync_run_id=sync_run_id,
            status=status,
            snapshot_id=snapshot_id,
            started_at=started_at,
            finished_at=finished_at,
            next_attempt_at=(
                decision.next_attempt_at if decision is not None else None
            ),
            next_attempt_reason=decision.reason if decision is not None else None,
            error_code=error_code,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Synchronization clock must return an aware datetime.")
        return value.astimezone(UTC)

    def _jitter(self) -> int:
        return self.jitter_factory(self.policy.maximum_jitter_seconds)

    def _temporary_attempt(self, sync_run_id: int) -> int:
        with self.session_factory() as session:
            try:
                previous = self.repository.count_consecutive_temporary_failures(
                    session,
                    before_sync_run_id=sync_run_id,
                    maximum=self.policy.maximum_temporary_attempts,
                )
                return previous + 1
            except SQLAlchemyError as error:
                raise BlacklistSyncInfrastructureError from error


def run_blacklist_sync(
    provider: BlacklistProviderGateway,
    service: BlacklistSyncService,
) -> BlacklistSyncResult:
    """Run a supplied one-shot synchronization service."""
    return service.run_once(provider)
