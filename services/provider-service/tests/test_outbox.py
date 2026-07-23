from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from provider_service.outbox import BlacklistOutbox
from provider_service.schemas import InternalBlacklistResponse

NOW = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)
DELIVERY_ID = UUID("662ecba0-8918-433d-bc75-b14de17851f1")


def snapshot() -> InternalBlacklistResponse:
    return InternalBlacklistResponse.model_validate(
        {
            "provider": "AbuseIPDB",
            "generated_at": NOW.isoformat(),
            "fetched_at": NOW.isoformat(),
            "request": {"confidence_minimum": 90, "limit": 1000},
            "rate_limit": {"limit": 5, "remaining": 4},
            "items": [
                {
                    "ip_address": "8.8.8.8",
                    "ip_version": 4,
                    "abuse_confidence_score": 100,
                    "country_code": "US",
                    "last_reported_at": NOW.isoformat(),
                }
            ],
        }
    )


def test_outbox_persists_pending_delivery_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    first = BlacklistOutbox(path)
    first.enqueue(delivery_id=DELIVERY_ID, snapshot=snapshot(), now=NOW)
    first.close()

    restarted = BlacklistOutbox(path)
    pending = restarted.next_pending(NOW)

    assert pending is not None
    assert pending.delivery.delivery_id == DELIVERY_ID
    assert pending.delivery.snapshot == snapshot()
    assert restarted.pending_count() == 1
    restarted.close()


def test_outbox_keeps_poll_and_delivery_clocks_separate(tmp_path: Path) -> None:
    outbox = BlacklistOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(delivery_id=DELIVERY_ID, snapshot=snapshot(), now=NOW)
    outbox.reschedule(DELIVERY_ID, attempts=1, next_attempt_at=NOW.replace(minute=1))
    outbox.set_poll_state(next_poll_at=NOW.replace(hour=15), failure_attempts=0)

    assert outbox.next_due_at() == NOW.replace(minute=1)
    assert outbox.get_next_poll_at() == NOW.replace(hour=15)
    outbox.close()


def test_delivered_provider_snapshot_is_compacted_and_not_enqueued_again(
    tmp_path: Path,
) -> None:
    outbox = BlacklistOutbox(tmp_path / "outbox.sqlite3")
    outbox.enqueue(delivery_id=DELIVERY_ID, snapshot=snapshot(), now=NOW)
    outbox.mark_delivered(DELIVERY_ID, delivered_at=NOW)
    outbox.enqueue(
        delivery_id=UUID("37938c12-df44-4f64-8aa5-7febc89df546"),
        snapshot=snapshot(),
        now=NOW,
    )

    assert outbox.pending_count() == 0
    outbox.close()
