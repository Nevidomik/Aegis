"""Application-specific Provider failures."""

from datetime import datetime


class ApplicationError(Exception):
    """A safe failure that can be returned through the public API."""

    status_code: int
    code: str
    message: str

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class UpstreamTimeoutError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=504,
            code="UPSTREAM_TIMEOUT",
            message="The reputation provider timed out.",
        )


class AbuseIPDBAuthenticationError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="UPSTREAM_AUTHENTICATION_FAILED",
            message="The reputation provider rejected its credentials.",
        )


class RateLimitExceededError(ApplicationError):
    def __init__(
        self,
        *,
        retry_after_seconds: int | None = None,
        reset_at: datetime | None = None,
    ) -> None:
        super().__init__(
            status_code=429,
            code="RATE_LIMIT_EXCEEDED",
            message="The reputation provider rate limit has been exceeded.",
        )
        self.retry_after_seconds = retry_after_seconds
        self.reset_at = reset_at


class UpstreamRequestRejectedError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code="UPSTREAM_REQUEST_REJECTED",
            message="The reputation provider rejected the lookup request.",
        )


class AbuseIPDBUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="UPSTREAM_UNAVAILABLE",
            message="The reputation provider is temporarily unavailable.",
        )


class UpstreamInvalidResponseError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code="UPSTREAM_INVALID_RESPONSE",
            message="The reputation provider returned an invalid response.",
        )
