from datetime import UTC, datetime

import pytest
from provider_service.provider import FakeReputationProvider
from provider_service.schemas import InternalReputationRequest
from provider_service.service import ReputationProxyService

CHECKED_AT = datetime(2026, 7, 15, 18, 30, tzinfo=UTC)


@pytest.mark.anyio
async def test_internal_proxy_returns_normalized_result_without_persistence() -> None:
    response = await ReputationProxyService(clock=lambda: CHECKED_AT).check(
        InternalReputationRequest(ip_address="8.8.8.8", max_age_days=90),
        FakeReputationProvider(),
    )

    assert response.ip_address == "8.8.8.8"
    assert response.max_age_days == 90
    assert response.checked_at == CHECKED_AT
    assert response.source == "FakeReputationProvider"
    assert not hasattr(response, "history_id")
    assert not hasattr(response, "request_id")
