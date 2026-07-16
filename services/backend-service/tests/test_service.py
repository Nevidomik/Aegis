from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from backend_service.exceptions import InvalidIPAddressError, NonPublicIPAddressError
from backend_service.provider import FakeReputationProvider
from backend_service.schemas import CheckRequest, CheckResponse
from backend_service.service import CheckService

REQUEST_ID = UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd")
CHECKED_AT = datetime(2026, 7, 15, 18, 30, tzinfo=UTC)


@pytest.mark.anyio
async def test_check_normalizes_and_persists_provider_result() -> None:
    history_client = Mock()

    async def save(payload: object, *, request_id: str) -> CheckResponse:
        return CheckResponse(history_id=145, **payload.model_dump())  # type: ignore[attr-defined]

    history_client.save = AsyncMock(side_effect=save)
    service = CheckService(clock=lambda: CHECKED_AT)

    response = await service.check(
        CheckRequest(ip_address="2606:4700:4700:0:0:0:0:1111"),
        REQUEST_ID,
        FakeReputationProvider(),
        history_client,
    )

    assert response.ip_address == "2606:4700:4700::1111"
    assert response.request_id == REQUEST_ID
    assert response.checked_at == CHECKED_AT
    history_client.save.assert_awaited_once()


@pytest.mark.parametrize(
    ("value", "exception_type"),
    [
        ("not-an-ip", InvalidIPAddressError),
        ("127.0.0.1", NonPublicIPAddressError),
        ("10.0.0.1", NonPublicIPAddressError),
        ("::1", NonPublicIPAddressError),
        ("fe80::1", NonPublicIPAddressError),
        ("224.0.0.1", NonPublicIPAddressError),
        ("0.0.0.0", NonPublicIPAddressError),
    ],
)
@pytest.mark.anyio
async def test_invalid_or_non_global_addresses_stop_before_dependencies(
    value: str, exception_type: type[Exception]
) -> None:
    provider = Mock(spec=FakeReputationProvider)
    provider.lookup = AsyncMock()
    history_client = Mock()
    history_client.save = AsyncMock()

    with pytest.raises(exception_type):
        await CheckService().check(
            CheckRequest(ip_address=value), REQUEST_ID, provider, history_client
        )

    provider.lookup.assert_not_awaited()
    history_client.save.assert_not_awaited()
