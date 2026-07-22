from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx2 import ASGITransport, AsyncClient
from provider_service.main import app
from provider_service.provider import FakeReputationProvider, get_reputation_provider


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async def reputation_provider_override() -> FakeReputationProvider:
        return FakeReputationProvider()

    app.dependency_overrides[get_reputation_provider] = reputation_provider_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def override_dependency() -> Iterator[Any]:
    def apply(dependency: object, replacement: object) -> None:
        async def override() -> object:
            return replacement

        app.dependency_overrides[dependency] = override

    yield apply
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
