"""Standalone singleton worker for blacklist polling and durable delivery."""

import asyncio
import fcntl
import logging
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Protocol
from uuid import UUID, uuid4

import httpx

from provider_service.config import Settings, get_settings
from provider_service.exceptions import ApplicationError, RateLimitExceededError
from provider_service.history_client import HistoryDeliveryError, HistoryIngestionClient
from provider_service.main import create_abuseipdb_http_client
from provider_service.outbox import BlacklistOutbox
from provider_service.polling_policy import PollingPolicy
from provider_service.provider import AbuseIPDBProvider
from provider_service.schemas import (
    BlacklistSnapshotDelivery,
    InternalBlacklistRequest,
)
from provider_service.service import ReputationProvider, ReputationProxyService

logger = logging.getLogger(__name__)


class HistoryGateway(Protocol):
    async def deliver(self, delivery: BlacklistSnapshotDelivery) -> object: ...


@contextmanager
def singleton_worker_lock(outbox_path: Path) -> Iterator[None]:
    """Reject a second worker process regardless of API worker count."""
    lock_path = outbox_path.with_suffix(f"{outbox_path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle: IO[str] = lock_path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "Provider blacklist worker is already running."
            ) from error
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class BlacklistPollingWorker:
    """Run independent polling and durable History-delivery schedules."""

    def __init__(
        self,
        *,
        provider: ReputationProvider,
        history: HistoryGateway,
        outbox: BlacklistOutbox,
        policy: PollingPolicy,
        confidence_minimum: int = 90,
        clock: Callable[[], datetime] | None = None,
        delivery_id_factory: Callable[[], UUID] | None = None,
        service: ReputationProxyService | None = None,
    ) -> None:
        self.provider = provider
        self.history = history
        self.outbox = outbox
        self.policy = policy
        self.confidence_minimum = confidence_minimum
        self.clock = clock or (lambda: datetime.now(UTC))
        self.delivery_id_factory = delivery_id_factory or uuid4
        self.service = service or ReputationProxyService(clock=self.clock)

    async def tick(self) -> None:
        """Perform each independently due action at most once."""
        now = self.clock()
        next_poll_at = self.outbox.get_next_poll_at()
        if next_poll_at is None or next_poll_at <= now:
            await self._poll(now)
        await self._deliver_one(self.clock())

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            await self.tick()
            now = self.clock()
            due_times = [
                value
                for value in (
                    self.outbox.get_next_poll_at(),
                    self.outbox.next_due_at(),
                )
                if value is not None
            ]
            delay = (
                max(0.0, min((due - now).total_seconds() for due in due_times))
                if due_times
                else 60.0
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=min(delay, 60.0))
            except TimeoutError:
                continue

    async def _poll(self, now: datetime) -> None:
        try:
            snapshot = await self.service.blacklist(
                InternalBlacklistRequest(
                    confidence_minimum=self.confidence_minimum, limit=1000
                ),
                self.provider,
            )
        except RateLimitExceededError as error:
            next_poll_at = self.policy.after_rate_limit(
                now,
                retry_after_seconds=error.retry_after_seconds,
                reset_at=error.reset_at,
            )
            attempts = self.outbox.get_poll_failure_attempts() + 1
            self.outbox.set_poll_state(
                next_poll_at=next_poll_at, failure_attempts=attempts
            )
            return
        except ApplicationError:
            attempts = self.outbox.get_poll_failure_attempts() + 1
            self.outbox.set_poll_state(
                next_poll_at=self.policy.after_poll_failure(now, attempt=attempts),
                failure_attempts=attempts,
            )
            return

        self.outbox.enqueue(
            delivery_id=self.delivery_id_factory(), snapshot=snapshot, now=now
        )
        self.outbox.set_poll_state(
            next_poll_at=self.policy.after_success(
                now,
                remaining=snapshot.rate_limit.remaining,
                reset_at=snapshot.rate_limit.reset_at,
            ),
            failure_attempts=0,
        )

    async def _deliver_one(self, now: datetime) -> None:
        pending = self.outbox.next_pending(now)
        if pending is None:
            return
        try:
            await self.history.deliver(pending.delivery)
        except HistoryDeliveryError:
            attempts = pending.attempts + 1
            self.outbox.reschedule(
                pending.delivery.delivery_id,
                attempts=attempts,
                next_attempt_at=self.policy.after_delivery_failure(
                    now, attempt=attempts
                ),
            )
            return
        self.outbox.mark_delivered(
            pending.delivery.delivery_id, delivered_at=self.clock()
        )


def create_history_http_client(settings: Settings) -> httpx.AsyncClient:
    token = settings.history_ingestion_token
    if token is None:
        raise RuntimeError("History ingestion token is not configured.")
    return httpx.AsyncClient(
        base_url=str(settings.history_service_url).rstrip("/"),
        headers={"Authorization": f"Bearer {token.get_secret_value()}"},
        timeout=httpx.Timeout(
            connect=settings.history_connect_timeout_seconds,
            read=settings.history_read_timeout_seconds,
            write=settings.history_write_timeout_seconds,
            pool=settings.history_pool_timeout_seconds,
        ),
        follow_redirects=False,
    )


async def run_worker(settings: Settings, stop_event: asyncio.Event) -> None:
    if not settings.blacklist_polling_enabled:
        logger.info("provider_blacklist_polling_disabled")
        return
    with singleton_worker_lock(settings.blacklist_outbox_path):
        outbox = BlacklistOutbox(settings.blacklist_outbox_path)
        abuseipdb_client = create_abuseipdb_http_client(settings)
        history_http_client = create_history_http_client(settings)
        try:
            worker = BlacklistPollingWorker(
                provider=AbuseIPDBProvider(
                    abuseipdb_client,
                    operation_timeout_seconds=(
                        settings.abuseipdb_operation_timeout_seconds
                    ),
                ),
                history=HistoryIngestionClient(
                    history_http_client,
                    operation_timeout_seconds=(
                        settings.history_operation_timeout_seconds
                    ),
                ),
                outbox=outbox,
                policy=PollingPolicy(
                    interval_seconds=settings.blacklist_poll_interval_seconds,
                    delivery_initial_seconds=(
                        settings.history_delivery_retry_initial_seconds
                    ),
                    delivery_maximum_seconds=(
                        settings.history_delivery_retry_maximum_seconds
                    ),
                ),
                confidence_minimum=settings.blacklist_confidence_minimum,
            )
            await worker.run(stop_event)
        finally:
            await abuseipdb_client.aclose()
            await history_http_client.aclose()
            outbox.close()


def main() -> None:
    settings = get_settings()
    stop_event = asyncio.Event()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_number, stop_event.set)
    try:
        loop.run_until_complete(run_worker(settings, stop_event))
    finally:
        loop.close()
