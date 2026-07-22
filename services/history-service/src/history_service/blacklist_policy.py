"""Pure next-attempt policy for blacklist synchronization."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

SchedulingReason = Literal[
    "base_interval",
    "quota_reset",
    "rate_limit_retry_after",
    "rate_limit_reset",
    "rate_limit_fallback",
    "temporary_backoff_5m",
    "temporary_backoff_15m",
    "temporary_backoff_30m",
    "temporary_backoff_60m",
    "temporary_reset_floor",
    "temporary_failures_exhausted",
    "invalid_response_interval",
]

TEMPORARY_BACKOFFS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=30),
    timedelta(minutes=60),
)


@dataclass(frozen=True)
class NextAttemptDecision:
    """One deterministic scheduling decision."""

    next_attempt_at: datetime
    reason: SchedulingReason


class BlacklistNextAttemptPolicy:
    """Calculate synchronization timing without I/O, waiting, or randomness."""

    def __init__(
        self,
        *,
        interval_seconds: int,
        rate_limit_fallback_seconds: int | None = None,
        maximum_temporary_attempts: int = 4,
        maximum_jitter_seconds: int = 0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive.")
        if rate_limit_fallback_seconds is not None and rate_limit_fallback_seconds <= 0:
            raise ValueError("rate_limit_fallback_seconds must be positive.")
        if not 0 <= maximum_temporary_attempts <= len(TEMPORARY_BACKOFFS):
            raise ValueError("maximum_temporary_attempts must be between 0 and 4.")
        if maximum_jitter_seconds < 0:
            raise ValueError("maximum_jitter_seconds cannot be negative.")
        self.interval = timedelta(seconds=interval_seconds)
        self.rate_limit_fallback = timedelta(
            seconds=rate_limit_fallback_seconds or interval_seconds
        )
        self.maximum_temporary_attempts = maximum_temporary_attempts
        self.maximum_jitter_seconds = maximum_jitter_seconds

    def after_success(
        self,
        finished_at: datetime,
        *,
        remaining: int | None,
        reset_at: datetime | None,
        jitter_seconds: int = 0,
    ) -> NextAttemptDecision:
        finished = self._utc(finished_at)
        reset = self._optional_utc(reset_at)
        candidate = finished + self.interval
        reason: SchedulingReason = "base_interval"
        if remaining == 0 and reset is not None and reset > candidate:
            candidate = reset
            reason = "quota_reset"
        return self._decision(candidate, reason, jitter_seconds)

    def after_rate_limit(
        self,
        finished_at: datetime,
        *,
        retry_after_seconds: int | None,
        reset_at: datetime | None,
        jitter_seconds: int = 0,
    ) -> NextAttemptDecision:
        finished = self._utc(finished_at)
        reset = self._optional_utc(reset_at)
        if retry_after_seconds is not None:
            if retry_after_seconds < 0:
                raise ValueError("retry_after_seconds cannot be negative.")
            candidate = finished + timedelta(seconds=retry_after_seconds)
            reason: SchedulingReason = "rate_limit_retry_after"
        elif reset is not None:
            candidate = max(finished, reset)
            reason = "rate_limit_reset"
        else:
            candidate = finished + self.rate_limit_fallback
            reason = "rate_limit_fallback"
        return self._decision(candidate, reason, jitter_seconds)

    def after_temporary_failure(
        self,
        finished_at: datetime,
        *,
        attempt: int,
        reset_at: datetime | None = None,
        jitter_seconds: int = 0,
    ) -> NextAttemptDecision:
        if attempt < 1:
            raise ValueError("attempt must be at least 1.")
        finished = self._utc(finished_at)
        reset = self._optional_utc(reset_at)
        if attempt > self.maximum_temporary_attempts:
            candidate = finished + self.interval
            reason: SchedulingReason = "temporary_failures_exhausted"
        else:
            backoff = TEMPORARY_BACKOFFS[attempt - 1]
            candidate = finished + backoff
            reason = (
                "temporary_backoff_5m",
                "temporary_backoff_15m",
                "temporary_backoff_30m",
                "temporary_backoff_60m",
            )[attempt - 1]
        if reset is not None and reset > candidate:
            candidate = reset
            reason = "temporary_reset_floor"
        return self._decision(candidate, reason, jitter_seconds)

    def after_invalid_response(
        self, finished_at: datetime, *, jitter_seconds: int = 0
    ) -> NextAttemptDecision:
        finished = self._utc(finished_at)
        return self._decision(
            finished + self.interval,
            "invalid_response_interval",
            jitter_seconds,
        )

    def _decision(
        self,
        candidate: datetime,
        reason: SchedulingReason,
        jitter_seconds: int,
    ) -> NextAttemptDecision:
        if not 0 <= jitter_seconds <= self.maximum_jitter_seconds:
            raise ValueError("jitter_seconds is outside the configured bound.")
        return NextAttemptDecision(
            next_attempt_at=candidate + timedelta(seconds=jitter_seconds),
            reason=reason,
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Policy timestamps must include a timezone.")
        return value.astimezone(UTC)

    @classmethod
    def _optional_utc(cls, value: datetime | None) -> datetime | None:
        return cls._utc(value) if value is not None else None
