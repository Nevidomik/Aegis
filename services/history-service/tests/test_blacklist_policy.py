from datetime import UTC, datetime, timedelta, timezone

import pytest
from history_service.blacklist_policy import BlacklistNextAttemptPolicy

FINISHED = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def policy() -> BlacklistNextAttemptPolicy:
    return BlacklistNextAttemptPolicy(
        interval_seconds=21600,
        rate_limit_fallback_seconds=7200,
        maximum_temporary_attempts=4,
        maximum_jitter_seconds=30,
    )


@pytest.mark.parametrize(
    ("remaining", "reset_at", "expected", "reason"),
    [
        (4, None, FINISHED + timedelta(hours=6), "base_interval"),
        (0, None, FINISHED + timedelta(hours=6), "base_interval"),
        (
            0,
            FINISHED + timedelta(hours=5),
            FINISHED + timedelta(hours=6),
            "base_interval",
        ),
        (
            0,
            FINISHED + timedelta(hours=6),
            FINISHED + timedelta(hours=6),
            "base_interval",
        ),
        (
            0,
            FINISHED + timedelta(hours=8),
            FINISHED + timedelta(hours=8),
            "quota_reset",
        ),
    ],
)
def test_success_branches(
    policy: BlacklistNextAttemptPolicy,
    remaining: int,
    reset_at: datetime | None,
    expected: datetime,
    reason: str,
) -> None:
    decision = policy.after_success(
        FINISHED, remaining=remaining, reset_at=reset_at, jitter_seconds=0
    )
    assert decision.next_attempt_at == expected
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("retry_after", "reset_at", "expected", "reason"),
    [
        (
            3600,
            FINISHED + timedelta(hours=8),
            FINISHED + timedelta(hours=1),
            "rate_limit_retry_after",
        ),
        (0, FINISHED + timedelta(hours=8), FINISHED, "rate_limit_retry_after"),
        (
            None,
            FINISHED + timedelta(hours=8),
            FINISHED + timedelta(hours=8),
            "rate_limit_reset",
        ),
        (None, FINISHED - timedelta(minutes=1), FINISHED, "rate_limit_reset"),
        (None, None, FINISHED + timedelta(hours=2), "rate_limit_fallback"),
    ],
)
def test_rate_limit_priority(
    policy: BlacklistNextAttemptPolicy,
    retry_after: int | None,
    reset_at: datetime | None,
    expected: datetime,
    reason: str,
) -> None:
    decision = policy.after_rate_limit(
        FINISHED,
        retry_after_seconds=retry_after,
        reset_at=reset_at,
        jitter_seconds=0,
    )
    assert decision.next_attempt_at == expected
    assert decision.reason == reason


@pytest.mark.parametrize(
    ("attempt", "delay", "reason"),
    [
        (1, timedelta(minutes=5), "temporary_backoff_5m"),
        (2, timedelta(minutes=15), "temporary_backoff_15m"),
        (3, timedelta(minutes=30), "temporary_backoff_30m"),
        (4, timedelta(minutes=60), "temporary_backoff_60m"),
        (5, timedelta(hours=6), "temporary_failures_exhausted"),
        (100, timedelta(hours=6), "temporary_failures_exhausted"),
    ],
)
def test_temporary_failure_progression(
    policy: BlacklistNextAttemptPolicy,
    attempt: int,
    delay: timedelta,
    reason: str,
) -> None:
    decision = policy.after_temporary_failure(
        FINISHED, attempt=attempt, jitter_seconds=0
    )
    assert decision.next_attempt_at == FINISHED + delay
    assert decision.reason == reason


def test_known_reset_cannot_be_bypassed_by_backoff(
    policy: BlacklistNextAttemptPolicy,
) -> None:
    reset_at = FINISHED + timedelta(hours=3)
    decision = policy.after_temporary_failure(
        FINISHED, attempt=1, reset_at=reset_at, jitter_seconds=0
    )
    assert decision.next_attempt_at == reset_at
    assert decision.reason == "temporary_reset_floor"


def test_invalid_response_uses_normal_interval(
    policy: BlacklistNextAttemptPolicy,
) -> None:
    decision = policy.after_invalid_response(FINISHED, jitter_seconds=0)
    assert decision.next_attempt_at == FINISHED + timedelta(hours=6)
    assert decision.reason == "invalid_response_interval"


@pytest.mark.parametrize("jitter", [0, 1, 30])
def test_bounded_injected_jitter_is_deterministic(
    policy: BlacklistNextAttemptPolicy, jitter: int
) -> None:
    first = policy.after_success(
        FINISHED, remaining=1, reset_at=None, jitter_seconds=jitter
    )
    second = policy.after_success(
        FINISHED, remaining=1, reset_at=None, jitter_seconds=jitter
    )
    assert first == second
    assert first.next_attempt_at == FINISHED + timedelta(hours=6, seconds=jitter)


@pytest.mark.parametrize("jitter", [-1, 31])
def test_jitter_outside_bound_is_rejected(
    policy: BlacklistNextAttemptPolicy, jitter: int
) -> None:
    with pytest.raises(ValueError, match="jitter_seconds"):
        policy.after_success(
            FINISHED, remaining=1, reset_at=None, jitter_seconds=jitter
        )


@pytest.mark.parametrize(
    "operation",
    [
        lambda policy, value: policy.after_success(value, remaining=1, reset_at=None),
        lambda policy, value: policy.after_rate_limit(
            value, retry_after_seconds=None, reset_at=None
        ),
        lambda policy, value: policy.after_temporary_failure(value, attempt=1),
        lambda policy, value: policy.after_invalid_response(value),
    ],
)
def test_naive_input_is_rejected(policy, operation) -> None:
    with pytest.raises(ValueError, match="timezone"):
        operation(policy, FINISHED.replace(tzinfo=None))


def test_non_utc_input_and_reset_are_returned_as_utc(
    policy: BlacklistNextAttemptPolicy,
) -> None:
    offset = timezone(timedelta(hours=3))
    finished = FINISHED.astimezone(offset)
    reset = (FINISHED + timedelta(hours=8)).astimezone(offset)
    decision = policy.after_success(
        finished, remaining=0, reset_at=reset, jitter_seconds=0
    )
    assert decision.next_attempt_at == FINISHED + timedelta(hours=8)
    assert decision.next_attempt_at.tzinfo is UTC


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval_seconds": 0},
        {"interval_seconds": 1, "rate_limit_fallback_seconds": 0},
        {"interval_seconds": 1, "maximum_temporary_attempts": 5},
        {"interval_seconds": 1, "maximum_jitter_seconds": -1},
    ],
)
def test_configuration_boundaries_are_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        BlacklistNextAttemptPolicy(**kwargs)
