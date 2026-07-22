"""Safe application and Provider dependency failures."""


class ApplicationError(Exception):
    """A failure safe to expose through the application API."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class InvalidIPAddressError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=400,
            code="INVALID_IP_ADDRESS",
            message="The supplied value is not a valid IP address.",
        )


class NonPublicIPAddressError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=400,
            code="NON_PUBLIC_IP_ADDRESS",
            message="The supplied IP address is not globally routable.",
        )


class ProviderServiceUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="BACKEND_UNAVAILABLE",
            message="The reputation service is temporarily unavailable.",
        )


class ProviderServiceInvalidResponseError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            status_code=502,
            code="BACKEND_INVALID_RESPONSE",
            message="The reputation service returned an invalid response.",
        )


PROXY_ERROR_MAP: dict[str, tuple[int, str, str]] = {
    "RATE_LIMIT_EXCEEDED": (
        429,
        "RATE_LIMIT_EXCEEDED",
        "The reputation provider rate limit has been exceeded.",
    ),
    "UPSTREAM_INVALID_RESPONSE": (
        502,
        "PROVIDER_INVALID_RESPONSE",
        "The reputation provider returned an invalid response.",
    ),
    "UPSTREAM_REQUEST_REJECTED": (
        502,
        "PROVIDER_REQUEST_REJECTED",
        "The reputation provider rejected the lookup request.",
    ),
    "ABUSEIPDB_AUTHENTICATION_FAILED": (
        503,
        "PROVIDER_AUTHENTICATION_FAILED",
        "The reputation provider rejected its credentials.",
    ),
    "ABUSEIPDB_UNAVAILABLE": (
        503,
        "PROVIDER_UNAVAILABLE",
        "The reputation provider is temporarily unavailable.",
    ),
    "UPSTREAM_TIMEOUT": (
        504,
        "PROVIDER_TIMEOUT",
        "The reputation provider timed out.",
    ),
}


def map_proxy_error(code: str) -> ApplicationError:
    """Translate a known internal proxy code into an application error."""
    mapped = PROXY_ERROR_MAP.get(code)
    if mapped is None:
        return ProviderServiceInvalidResponseError()
    status_code, application_code, message = mapped
    return ApplicationError(
        status_code=status_code,
        code=application_code,
        message=message,
    )
