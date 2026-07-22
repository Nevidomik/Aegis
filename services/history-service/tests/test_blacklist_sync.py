from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from history_service.blacklist_repository import BlacklistRepository
from history_service.blacklist_sync import (
    BlacklistNextAttemptPolicy,
    BlacklistSyncService,
    run_blacklist_sync,
)
from history_service.exceptions import (
    ApplicationError,
    ProviderServiceInvalidResponseError,
    ProviderServiceUnavailableError,
)
from history_service.models import BlacklistSnapshot, BlacklistSyncRun
from history_service.schemas import ProviderBlacklistResponse
from sqlalchemy.exc import SQLAlchemyError

REQUEST_ID = UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd")
STARTED = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
FINISHED = datetime(2026, 7, 22, 12, 0, 2, tzinfo=UTC)


class FakeSession:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True
        self.state["commits"] += 1

    def rollback(self) -> None:
        self.rolled_back = True
        self.state["rollbacks"] += 1


class FakeRepository(BlacklistRepository):
    def __init__(
        self, *, fail_snapshot: bool = False, previous_temporary_failures: int = 0
    ) -> None:
        self.runs: dict[int, BlacklistSyncRun] = {}
        self.snapshots: list[BlacklistSnapshot] = []
        self.fail_snapshot = fail_snapshot
        self.partial_insert_attempted = False
        self.previous_temporary_failures = previous_temporary_failures

    def add_sync_run(self, session: Any, run: BlacklistSyncRun) -> BlacklistSyncRun:
        run.started_at = self._as_mariadb_utc(run.started_at)
        run.sync_run_id = len(self.runs) + 1
        self.runs[run.sync_run_id] = run
        return run

    def get_sync_run_for_update(
        self, session: Any, sync_run_id: int
    ) -> BlacklistSyncRun | None:
        return self.runs.get(sync_run_id)

    def get_by_provider_generation(
        self,
        session: Any,
        *,
        provider: str,
        provider_generated_at: datetime,
    ) -> BlacklistSnapshot | None:
        normalized = self._as_mariadb_utc(provider_generated_at)
        return next(
            (
                snapshot
                for snapshot in self.snapshots
                if snapshot.provider == provider
                and snapshot.provider_generated_at == normalized
            ),
            None,
        )

    def add_snapshot(
        self, session: Any, snapshot: BlacklistSnapshot, entries: list[Any]
    ) -> BlacklistSnapshot:
        self.partial_insert_attempted = bool(entries)
        if self.fail_snapshot:
            raise SQLAlchemyError("simulated database failure with secret details")
        snapshot.provider_generated_at = self._as_mariadb_utc(
            snapshot.provider_generated_at
        )
        snapshot.fetched_at = self._as_mariadb_utc(snapshot.fetched_at)
        snapshot.snapshot_id = len(self.snapshots) + 1
        snapshot.entries.extend(entries)
        self.snapshots.append(snapshot)
        return snapshot

    def count_consecutive_temporary_failures(
        self, session: Any, *, before_sync_run_id: int, maximum: int
    ) -> int:
        return min(self.previous_temporary_failures, maximum)


class FakeProvider:
    def __init__(
        self,
        response: ProviderBlacklistResponse | None = None,
        error: ApplicationError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[object, str]] = []

    def get_blacklist(self, query: object, *, request_id: str) -> Any:
        self.calls.append((query, request_id))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class FakeLock:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.released = False

    @contextmanager
    def acquire(self):
        try:
            yield self.acquired
        finally:
            self.released = True


def response(
    *,
    generated_at: datetime = STARTED,
    addresses: list[str] | None = None,
    remaining: int | None = 4,
    reset_at: datetime | None = None,
) -> ProviderBlacklistResponse:
    addresses = addresses if addresses is not None else ["8.8.8.8"]
    return ProviderBlacklistResponse.model_validate(
        {
            "provider": "AbuseIPDB",
            "generated_at": generated_at,
            "fetched_at": FINISHED,
            "request": {"confidence_minimum": 90, "limit": 1000},
            "rate_limit": {
                "limit": 5,
                "remaining": remaining,
                "reset_at": reset_at,
                "retry_after_seconds": None,
            },
            "items": [
                {
                    "ip_address": address,
                    "ip_version": 6 if ":" in address else 4,
                    "abuse_confidence_score": 95,
                    "country_code": "US",
                    "last_reported_at": STARTED,
                }
                for address in addresses
            ],
        }
    )


def build_service(
    repository: FakeRepository,
    *,
    lock: FakeLock | None = None,
) -> tuple[BlacklistSyncService, dict[str, Any]]:
    state = {"commits": 0, "rollbacks": 0}
    times = iter([STARTED, FINISHED, FINISHED + timedelta(seconds=1)])
    service = BlacklistSyncService(
        session_factory=lambda: FakeSession(state),  # type: ignore[arg-type]
        sync_lock=lock or FakeLock(),
        confidence_minimum=90,
        repository=repository,
        policy=BlacklistNextAttemptPolicy(
            interval_seconds=21600,
            rate_limit_fallback_seconds=21600,
            maximum_jitter_seconds=0,
        ),
        clock=lambda: next(times),
        request_id_factory=lambda: REQUEST_ID,
    )
    return service, state


@pytest.mark.parametrize(
    "addresses",
    [
        ["8.8.8.8", "2606:4700:4700::1111"],
        [],
        [f"8.0.{index // 256}.{index % 256}" for index in range(1000)],
    ],
)
def test_first_snapshot_persists_complete_valid_response(addresses: list[str]) -> None:
    repository = FakeRepository()
    service, state = build_service(repository)
    provider = FakeProvider(response(addresses=addresses))

    result = service.run_once(provider)

    assert result.status == "succeeded"
    assert result.request_id == REQUEST_ID
    assert len(repository.snapshots) == 1
    snapshot = repository.snapshots[0]
    assert snapshot.returned_count == len(addresses)
    assert [entry.ip_address for entry in snapshot.entries] == addresses
    assert provider.calls[0][1] == str(REQUEST_ID)
    query = provider.calls[0][0]
    assert getattr(query, "confidence_minimum") == 90
    assert getattr(query, "limit") == 1000
    assert repository.runs[1].status == "succeeded"
    assert repository.runs[1].next_attempt_reason == "base_interval"
    assert state["commits"] == 2


def test_duplicate_snapshot_reuses_existing_snapshot_without_entries() -> None:
    repository = FakeRepository()
    existing = BlacklistSnapshot(
        snapshot_id=42,
        provider="AbuseIPDB",
        provider_generated_at=STARTED.replace(tzinfo=None),
        fetched_at=FINISHED.replace(tzinfo=None),
        confidence_minimum=90,
        requested_limit=1000,
        returned_count=1,
    )
    repository.snapshots.append(existing)
    service, _ = build_service(repository)

    result = service.run_once(FakeProvider(response()))

    assert result.status == "duplicate"
    assert result.snapshot_id == 42
    assert repository.snapshots == [existing]
    assert repository.runs[1].snapshot_id == 42


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_delay"),
    [
        (
            ProviderServiceUnavailableError(code="PROVIDER_SERVICE_UNAVAILABLE"),
            "PROVIDER_SERVICE_UNAVAILABLE",
            timedelta(minutes=5),
        ),
        (
            ProviderServiceInvalidResponseError(
                code="PROVIDER_SERVICE_INVALID_RESPONSE"
            ),
            "PROVIDER_SERVICE_INVALID_RESPONSE",
            timedelta(hours=6),
        ),
        (
            ApplicationError(
                status_code=504,
                code="PROVIDER_TIMEOUT",
                message="provider timeout details",
            ),
            "PROVIDER_TIMEOUT",
            timedelta(minutes=5),
        ),
    ],
)
def test_provider_failures_preserve_snapshots_and_store_safe_error(
    error: ApplicationError, expected_code: str, expected_delay: timedelta
) -> None:
    repository = FakeRepository()
    old_snapshot = response(generated_at=STARTED - timedelta(days=1))
    repository.snapshots.append(
        BlacklistSnapshot(
            snapshot_id=9,
            provider=old_snapshot.provider,
            provider_generated_at=old_snapshot.generated_at.replace(tzinfo=None),
            fetched_at=old_snapshot.fetched_at.replace(tzinfo=None),
            confidence_minimum=90,
            requested_limit=1000,
            returned_count=1,
        )
    )
    service, _ = build_service(repository)

    result = service.run_once(FakeProvider(error=error))

    assert result.status == "failed"
    assert result.error_code == expected_code
    assert len(repository.snapshots) == 1
    run = repository.runs[1]
    assert run.error_code == expected_code
    assert "secret" not in (run.error_message or "")
    assert run.next_attempt_at == (FINISHED + expected_delay).replace(tzinfo=None)


def test_temporary_failures_beyond_maximum_use_normal_interval() -> None:
    repository = FakeRepository(previous_temporary_failures=4)
    service, _ = build_service(repository)
    error = ProviderServiceUnavailableError(code="PROVIDER_SERVICE_UNAVAILABLE")

    result = service.run_once(FakeProvider(error=error))

    assert result.next_attempt_at == FINISHED + timedelta(hours=6)
    assert result.next_attempt_reason == "temporary_failures_exhausted"
    assert repository.runs[1].next_attempt_reason == "temporary_failures_exhausted"


def test_rate_limit_preserves_retry_after_and_calculates_next_attempt() -> None:
    repository = FakeRepository()
    error = ApplicationError(
        status_code=429,
        code="RATE_LIMIT_EXCEEDED",
        message="raw internal message",
    )
    error.retry_after_seconds = 3600
    error.reset_at = STARTED + timedelta(hours=2)
    service, _ = build_service(repository)

    result = service.run_once(FakeProvider(error=error))

    assert result.status == "rate_limited"
    assert result.next_attempt_at == FINISHED + timedelta(hours=1)
    run = repository.runs[1]
    assert run.retry_after_seconds == 3600
    assert run.rate_limit_reset_at == error.reset_at.replace(tzinfo=None)
    assert run.error_message != error.message


def test_zero_remaining_quota_respects_later_reset_time() -> None:
    repository = FakeRepository()
    reset_at = FINISHED + timedelta(hours=8)
    service, _ = build_service(repository)

    result = service.run_once(FakeProvider(response(remaining=0, reset_at=reset_at)))

    assert result.next_attempt_at == reset_at
    assert repository.runs[1].rate_limit_remaining == 0


def test_database_failure_rolls_back_partial_snapshot_and_finalizes_run() -> None:
    repository = FakeRepository(fail_snapshot=True)
    service, state = build_service(repository)

    result = service.run_once(FakeProvider(response()))

    assert result.status == "failed"
    assert result.error_code == "DATABASE_UNAVAILABLE"
    assert repository.partial_insert_attempted
    assert repository.snapshots == []
    assert state["rollbacks"] == 1
    assert repository.runs[1].status == "failed"
    assert (
        repository.runs[1].error_message
        == "Blacklist synchronization could not be saved."
    )


def test_concurrent_attempt_does_not_create_run_or_call_provider() -> None:
    repository = FakeRepository()
    lock = FakeLock(acquired=False)
    service, state = build_service(repository, lock=lock)
    provider = FakeProvider(response())

    result = service.run_once(provider)

    assert result.status == "already_running"
    assert result.sync_run_id is None
    assert provider.calls == []
    assert repository.runs == {}
    assert state["commits"] == 0
    assert lock.released


def test_normal_application_function_runs_injected_single_attempt() -> None:
    repository = FakeRepository()
    service, _ = build_service(repository)

    result = run_blacklist_sync(FakeProvider(response()), service)

    assert result.status == "succeeded"
