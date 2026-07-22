import logging

from ui_service.security_logging import log_sanitized_exception

COOKIE_SECRET = "TEST_ABUSEIPDB_SECRET_DO_NOT_LOG"


def test_unexpected_exception_traceback_does_not_log_cookie(caplog) -> None:
    try:
        raise RuntimeError(f"Cookie={COOKIE_SECRET}")
    except RuntimeError as error:
        with caplog.at_level(logging.ERROR):
            log_sanitized_exception(
                logging.getLogger("ui.security.test"),
                "unexpected_failure",
                error,
                request_id="6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
            )

    assert COOKIE_SECRET not in caplog.text
    assert "Traceback" in caplog.text
