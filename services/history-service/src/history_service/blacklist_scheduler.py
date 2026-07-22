"""Interruptible in-process scheduling for one-shot blacklist synchronization."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from history_service.blacklist_repository import (
    BlacklistRepository,
    PersistedBlacklistSchedule,
)
from history_service.blacklist_sync import (
    BlacklistProviderGateway,
    BlacklistSyncInfrastructureError,
    BlacklistSyncResult,
    BlacklistSyncService,
)

logger = logging.getLogger(__name__)

SyncRunner = Callable[..., Awaitable[Any]]
Waiter = Callable[[asyncio.Event, float], Awaitable[bool]]


async def run_in_thread(function: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.to_thread(function, *args)


async def interruptible_wait(stop_event: asyncio.Event, seconds: float) -> bool:
    """Return true when shutdown interrupts the wait."""
    if seconds <= 0:
        return stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


class BlacklistScheduler:
    """Schedule repeated calls to the existing single-run use case."""

    def __init__(
        self,
        *,
        sync_service: BlacklistSyncService,
        provider: BlacklistProviderGateway,
        session_factory: Callable[[], Session],
        repository: BlacklistRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        runner: SyncRunner = run_in_thread,
        waiter: Waiter = interruptible_wait,
        coordination_delay_seconds: int = 30,
        infrastructure_delay_seconds: int = 300,
        sync_deadline_seconds: float = 30.0,
    ) -> None:
        self.sync_service = sync_service
        self.provider = provider
        self.session_factory = session_factory
        self.repository = repository or BlacklistRepository()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.runner = runner
        self.waiter = waiter
        self.coordination_delay_seconds = coordination_delay_seconds
        self.infrastructure_delay_seconds = infrastructure_delay_seconds
        self.sync_deadline_seconds = sync_deadline_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("blacklist_scheduler_started")
        try:
            while not stop_event.is_set():
                try:
                    schedule = await self.runner(self._read_schedule)
                except SQLAlchemyError:
                    logger.error(
                        "blacklist_scheduler_schedule_read_failed",
                        extra={"error_code": "DATABASE_UNAVAILABLE"},
                    )
                    if await self.waiter(stop_event, self.infrastructure_delay_seconds):
                        break
                    continue

                due_at = self.effective_due_at(schedule)
                delay = max(0.0, (due_at - self._now()).total_seconds())
                if delay and await self.waiter(stop_event, delay):
                    break
                if stop_event.is_set():
                    break

                logger.info("blacklist_sync_started")
                try:
                    async with asyncio.timeout(self.sync_deadline_seconds):
                        result: BlacklistSyncResult = await self.runner(
                            self.sync_service.run_once, self.provider
                        )
                except TimeoutError:
                    logger.error(
                        "blacklist_sync_deadline_exceeded",
                        extra={"error_code": "PROVIDER_SERVICE_UNAVAILABLE"},
                    )
                    if await self.waiter(stop_event, self.infrastructure_delay_seconds):
                        break
                    continue
                except BlacklistSyncInfrastructureError:
                    logger.error(
                        "blacklist_sync_failed",
                        extra={"error_code": "DATABASE_UNAVAILABLE"},
                    )
                    if await self.waiter(stop_event, self.infrastructure_delay_seconds):
                        break
                    continue

                self._log_result(result)
                if result.status == "already_running" and await self.waiter(
                    stop_event, self.coordination_delay_seconds
                ):
                    break
        finally:
            logger.info("blacklist_scheduler_stopped")

    def effective_due_at(self, schedule: PersistedBlacklistSchedule | None) -> datetime:
        now = self._now()
        if schedule is None or schedule.next_attempt_at is None:
            return now
        due_at = schedule.next_attempt_at
        if (
            schedule.status == "rate_limited" or schedule.rate_limit_remaining == 0
        ) and schedule.rate_limit_reset_at is not None:
            due_at = max(due_at, schedule.rate_limit_reset_at)
        return due_at

    def _read_schedule(self) -> PersistedBlacklistSchedule | None:
        with self.session_factory() as session:
            return self.repository.get_persisted_schedule(session)

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Scheduler clock must return an aware datetime.")
        return value.astimezone(UTC)

    @staticmethod
    def _log_result(result: BlacklistSyncResult) -> None:
        logger.info(
            "blacklist_sync_completed",
            extra={
                "request_id": str(result.request_id),
                "sync_run_id": result.sync_run_id,
                "status": result.status,
                "snapshot_id": result.snapshot_id,
                "next_attempt_at": (
                    result.next_attempt_at.isoformat()
                    if result.next_attempt_at is not None
                    else None
                ),
                "next_attempt_reason": result.next_attempt_reason,
                "error_code": result.error_code,
            },
        )
