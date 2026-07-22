import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from history_service.blacklist_repository import PersistedBlacklistSchedule
from history_service.blacklist_scheduler import BlacklistScheduler
from history_service.blacklist_sync import BlacklistSyncResult

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
REQUEST_ID = UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd")


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None


class ScheduleRepository:
    def __init__(self, schedules: list[PersistedBlacklistSchedule | None]) -> None:
        self.schedules = schedules
        self.reads = 0

    def get_persisted_schedule(self, session: Any):
        index = min(self.reads, len(self.schedules) - 1)
        self.reads += 1
        return self.schedules[index]


class FakeSyncService:
    def __init__(
        self,
        result: BlacklistSyncResult,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self.result = result
        self.stop_event = stop_event
        self.calls = 0

    def run_once(self, provider: object) -> BlacklistSyncResult:
        self.calls += 1
        if self.stop_event is not None:
            self.stop_event.set()
        return self.result


class RecordingWaiter:
    def __init__(self, *, stop_on_wait: bool = True) -> None:
        self.delays: list[float] = []
        self.stop_on_wait = stop_on_wait

    async def __call__(self, stop_event: asyncio.Event, seconds: float) -> bool:
        self.delays.append(seconds)
        if self.stop_on_wait:
            stop_event.set()
            return True
        return False


async def inline_runner(function, *args):
    return function(*args)


def result(
    *,
    status: str = "succeeded",
    next_attempt_at: datetime | None = None,
    reason: str | None = "base_interval",
) -> BlacklistSyncResult:
    return BlacklistSyncResult(
        request_id=REQUEST_ID,
        sync_run_id=1,
        status=status,  # type: ignore[arg-type]
        snapshot_id=2 if status == "succeeded" else None,
        started_at=NOW,
        finished_at=NOW,
        next_attempt_at=next_attempt_at,
        next_attempt_reason=reason,  # type: ignore[arg-type]
        error_code=None,
    )


def schedule(
    *,
    status: str = "succeeded",
    next_attempt_at: datetime | None,
    remaining: int | None = 4,
    reset_at: datetime | None = None,
) -> PersistedBlacklistSchedule:
    return PersistedBlacklistSchedule(
        status=status,
        next_attempt_at=next_attempt_at,
        next_attempt_reason="base_interval",
        rate_limit_remaining=remaining,
        rate_limit_reset_at=reset_at,
    )


def scheduler(
    repository: ScheduleRepository,
    sync_service: FakeSyncService,
    waiter: RecordingWaiter,
) -> BlacklistScheduler:
    return BlacklistScheduler(
        sync_service=sync_service,  # type: ignore[arg-type]
        provider=object(),  # type: ignore[arg-type]
        session_factory=FakeSession,  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        clock=lambda: NOW,
        runner=inline_runner,
        waiter=waiter,
    )


@pytest.mark.anyio
async def test_future_persisted_next_attempt_waits_without_syncing() -> None:
    repository = ScheduleRepository(
        [schedule(next_attempt_at=NOW + timedelta(hours=2))]
    )
    sync_service = FakeSyncService(result())
    waiter = RecordingWaiter()

    await scheduler(repository, sync_service, waiter).run(asyncio.Event())

    assert waiter.delays == [7200]
    assert sync_service.calls == 0


@pytest.mark.anyio
async def test_due_or_missing_schedule_runs_synchronization() -> None:
    for persisted in (None, schedule(next_attempt_at=NOW - timedelta(seconds=1))):
        stop_event = asyncio.Event()
        sync_service = FakeSyncService(result(), stop_event)
        instance = scheduler(
            ScheduleRepository([persisted]), sync_service, RecordingWaiter()
        )

        await instance.run(stop_event)

        assert sync_service.calls == 1


@pytest.mark.anyio
async def test_successful_attempt_rereads_and_waits_for_persisted_schedule() -> None:
    repository = ScheduleRepository(
        [None, schedule(next_attempt_at=NOW + timedelta(hours=6))]
    )
    sync_service = FakeSyncService(result(next_attempt_at=NOW + timedelta(hours=6)))
    waiter = RecordingWaiter()

    await scheduler(repository, sync_service, waiter).run(asyncio.Event())

    assert sync_service.calls == 1
    assert repository.reads == 2
    assert waiter.delays == [21600]


@pytest.mark.anyio
async def test_rate_limited_schedule_honors_later_reset() -> None:
    repository = ScheduleRepository(
        [
            None,
            schedule(
                status="rate_limited",
                next_attempt_at=NOW + timedelta(hours=1),
                remaining=0,
                reset_at=NOW + timedelta(hours=3),
            ),
        ]
    )
    sync_service = FakeSyncService(result(status="rate_limited"))
    waiter = RecordingWaiter()

    await scheduler(repository, sync_service, waiter).run(asyncio.Event())

    assert waiter.delays == [10800]
    assert sync_service.calls == 1


@pytest.mark.anyio
async def test_temporary_failure_uses_persisted_retry_time() -> None:
    repository = ScheduleRepository(
        [
            None,
            schedule(status="failed", next_attempt_at=NOW + timedelta(minutes=15)),
        ]
    )
    sync_service = FakeSyncService(result(status="failed"))
    waiter = RecordingWaiter()

    await scheduler(repository, sync_service, waiter).run(asyncio.Event())

    assert waiter.delays == [900]
    assert sync_service.calls == 1


@pytest.mark.anyio
async def test_graceful_shutdown_interrupts_wait() -> None:
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(
        BlacklistScheduler(
            sync_service=FakeSyncService(result()),  # type: ignore[arg-type]
            provider=object(),  # type: ignore[arg-type]
            session_factory=FakeSession,  # type: ignore[arg-type]
            repository=ScheduleRepository(  # type: ignore[arg-type]
                [schedule(next_attempt_at=NOW + timedelta(days=1))]
            ),
            clock=lambda: NOW,
            runner=inline_runner,
        ).run(stop_event)
    )
    await asyncio.sleep(0)

    stop_event.set()
    await scheduler_task

    assert scheduler_task.done()


@pytest.mark.anyio
async def test_cancellation_while_sleeping_is_not_swallowed() -> None:
    instance = BlacklistScheduler(
        sync_service=FakeSyncService(result()),  # type: ignore[arg-type]
        provider=object(),  # type: ignore[arg-type]
        session_factory=FakeSession,  # type: ignore[arg-type]
        repository=ScheduleRepository(  # type: ignore[arg-type]
            [schedule(next_attempt_at=NOW + timedelta(days=1))]
        ),
        clock=lambda: NOW,
        runner=inline_runner,
    )
    task = asyncio.create_task(instance.run(asyncio.Event()))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
