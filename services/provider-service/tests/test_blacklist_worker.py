from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from provider_service.blacklist_worker import (
    BlacklistPollingWorker,
    singleton_worker_lock,
)
from provider_service.exceptions import (
    RateLimitExceededError,
    UpstreamTimeoutError,
)
from provider_service.history_client import HistoryDeliveryError
from provider_service.outbox import BlacklistOutbox
from provider_service.polling_policy import PollingPolicy
from provider_service.schemas import BlacklistProviderResult, RateLimitMetadata

NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
DELIVERY_ID = UUID("662ecba0-8918-433d-bc75-b14de17851f1")


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeProvider:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def blacklist(
        self, confidence_minimum: int, limit: int
    ) -> BlacklistProviderResult:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, BlacklistProviderResult)
        return outcome


class FakeHistory:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = outcomes or [object()]
        self.deliveries = []

    async def deliver(self, delivery):
        self.deliveries.append(delivery)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def result(
    *,
    remaining: int | None = 4,
    reset_at: datetime | None = None,
) -> BlacklistProviderResult:
    return BlacklistProviderResult(
        generated_at=NOW,
        rate_limit=RateLimitMetadata(limit=5, remaining=remaining, reset_at=reset_at),
        items=[],
    )


def policy() -> PollingPolicy:
    return PollingPolicy(
        interval_seconds=21600,
        delivery_initial_seconds=30,
        delivery_maximum_seconds=900,
    )


def worker(
    path: Path,
    provider: FakeProvider,
    history: FakeHistory,
    clock: Clock,
) -> tuple[BlacklistPollingWorker, BlacklistOutbox]:
    outbox = BlacklistOutbox(path)
    return (
        BlacklistPollingWorker(
            provider=provider,
            history=history,
            outbox=outbox,
            policy=policy(),
            clock=clock,
            delivery_id_factory=lambda: DELIVERY_ID,
        ),
        outbox,
    )


def test_singleton_lock_rejects_second_worker(tmp_path: Path) -> None:
    outbox_path = tmp_path / "outbox.sqlite3"

    with singleton_worker_lock(outbox_path):
        with pytest.raises(RuntimeError, match="already running"):
            with singleton_worker_lock(outbox_path):
                pass


@pytest.mark.anyio
async def test_scheduled_polling_waits_until_persisted_due_time(
    tmp_path: Path,
) -> None:
    clock = Clock()
    provider = FakeProvider([result(), result()])
    current, outbox = worker(
        tmp_path / "outbox.sqlite3", provider, FakeHistory(), clock
    )

    await current.tick()
    await current.tick()
    assert provider.calls == 1

    clock.now += timedelta(hours=6)
    await current.tick()
    assert provider.calls == 2
    outbox.close()


@pytest.mark.anyio
async def test_429_honors_retry_after_and_reset(tmp_path: Path) -> None:
    clock = Clock()
    reset_at = NOW + timedelta(hours=2)
    provider = FakeProvider(
        [
            RateLimitExceededError(
                retry_after_seconds=3600,
                reset_at=reset_at,
            )
        ]
    )
    current, outbox = worker(
        tmp_path / "outbox.sqlite3", provider, FakeHistory(), clock
    )

    await current.tick()

    assert outbox.get_next_poll_at() == reset_at
    assert outbox.pending_count() == 0
    outbox.close()


@pytest.mark.anyio
async def test_upstream_timeout_uses_poll_retry_without_outbox_entry(
    tmp_path: Path,
) -> None:
    clock = Clock()
    current, outbox = worker(
        tmp_path / "outbox.sqlite3",
        FakeProvider([UpstreamTimeoutError()]),
        FakeHistory(),
        clock,
    )

    await current.tick()

    assert outbox.get_next_poll_at() == NOW + timedelta(minutes=5)
    assert outbox.pending_count() == 0
    outbox.close()


@pytest.mark.anyio
async def test_history_outage_preserves_snapshot_then_recovers(
    tmp_path: Path,
) -> None:
    clock = Clock()
    history = FakeHistory([HistoryDeliveryError(), object()])
    current, outbox = worker(
        tmp_path / "outbox.sqlite3", FakeProvider([result()]), history, clock
    )

    await current.tick()
    assert outbox.pending_count() == 1
    assert outbox.get_next_poll_at() == NOW + timedelta(hours=6)
    assert outbox.next_due_at() == NOW + timedelta(seconds=30)

    outbox.close()
    clock.now += timedelta(seconds=30)
    restarted, recovered_outbox = worker(
        tmp_path / "outbox.sqlite3", FakeProvider([result()]), history, clock
    )
    await restarted.tick()

    assert recovered_outbox.pending_count() == 0
    assert len(history.deliveries) == 2
    recovered_outbox.close()
