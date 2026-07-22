from ipaddress import ip_address

import pytest
from provider_service.provider import FakeReputationProvider


@pytest.mark.anyio
async def test_fake_provider_is_deterministic() -> None:
    provider = FakeReputationProvider()
    address = ip_address("2606:4700:4700::1111")

    first = await provider.lookup(address, 30)
    second = await provider.lookup(address, 30)

    assert first == second
    assert first.ip_address == "2606:4700:4700::1111"
    assert first.ip_version == 6
    assert first.source == "FakeReputationProvider"
