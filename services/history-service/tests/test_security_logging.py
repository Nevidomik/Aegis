import logging

from history_service.security_logging import (
    MAX_PERSISTED_ERROR_MESSAGE_LENGTH,
    log_sanitized_exception,
    redact_sensitive_text,
    safe_persisted_error_message,
)

DATABASE_SECRET = "TEST_DATABASE_PASSWORD_DO_NOT_LOG"


def test_database_exception_keeps_traceback_without_secret(caplog) -> None:
    try:
        raise RuntimeError(f"password={DATABASE_SECRET}")
    except RuntimeError as error:
        with caplog.at_level(logging.ERROR):
            log_sanitized_exception(
                logging.getLogger("history.security.test"),
                "database_failure",
                error,
                request_id="6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
            )

    assert DATABASE_SECRET not in caplog.text
    assert "Traceback" in caplog.text
    assert "Sanitized RuntimeError" in caplog.text


def test_redaction_covers_headers_and_database_urls() -> None:
    value = (
        f"Authorization=Bearer-{DATABASE_SECRET} Cookie={DATABASE_SECRET} "
        f"database_url=mariadb://user:{DATABASE_SECRET}@db/aegis"
    )
    assert DATABASE_SECRET not in redact_sensitive_text(value)


def test_persisted_error_is_redacted_and_length_bounded() -> None:
    message = f"password={DATABASE_SECRET} " + ("x" * 1000)
    persisted = safe_persisted_error_message(message)

    assert DATABASE_SECRET not in persisted
    assert len(persisted) == MAX_PERSISTED_ERROR_MESSAGE_LENGTH
