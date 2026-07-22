"""Sensitive-value redaction and traceback-safe logging helpers."""

import logging
import re
from types import TracebackType

SENSITIVE_VALUE = "[REDACTED]"
SENSITIVE_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|cookie|password|secret|token|database_url|dsn)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
URL_CREDENTIAL_PATTERN = re.compile(r"(?P<scheme>\w+://)[^/@\s:]+:[^/@\s]+@")


def redact_sensitive_text(value: object) -> str:
    text = str(value)
    text = SENSITIVE_PATTERN.sub(rf"\1\2{SENSITIVE_VALUE}", text)
    return URL_CREDENTIAL_PATTERN.sub(rf"\g<scheme>{SENSITIVE_VALUE}@", text)


def sanitized_exc_info(
    error: BaseException,
) -> tuple[type[Exception], Exception, TracebackType | None]:
    safe_error = RuntimeError(f"Sanitized {type(error).__name__}")
    return RuntimeError, safe_error, error.__traceback__


def log_sanitized_exception(
    logger: logging.Logger, message: str, error: BaseException, *, request_id: str
) -> None:
    logger.error(
        redact_sensitive_text(message),
        extra={"request_id": request_id},
        exc_info=sanitized_exc_info(error),
    )
