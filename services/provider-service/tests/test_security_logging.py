import logging
from ipaddress import ip_address

import httpx
import pytest
from provider_service.exceptions import AbuseIPDBUnavailableError
from provider_service.provider import AbuseIPDBProvider
from provider_service.security_logging import log_sanitized_exception

API_SECRET = "TEST_ABUSEIPDB_SECRET_DO_NOT_LOG"


def test_http_exception_traceback_does_not_log_api_secret(caplog) -> None:
    try:
        raise RuntimeError(f"Authorization: Bearer {API_SECRET}")
    except RuntimeError as error:
        with caplog.at_level(logging.ERROR):
            log_sanitized_exception(
                logging.getLogger("provider.security.test"),
                "upstream_http_failure",
                error,
                request_id="6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
            )

    assert API_SECRET not in caplog.text
    assert "Traceback" in caplog.text
    assert "Sanitized RuntimeError" in caplog.text


@pytest.mark.anyio
async def test_real_http_failure_logging_redacts_api_secret(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"api_key={API_SECRET}", request=request)

    async with httpx.AsyncClient(
        base_url="https://api.abuseipdb.test",
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(connect=1, read=1, write=1, pool=1),
    ) as client:
        provider = AbuseIPDBProvider(client)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(AbuseIPDBUnavailableError):
                await provider.lookup(ip_address("8.8.8.8"), 30)

    assert API_SECRET not in caplog.text
    assert "Traceback" in caplog.text
