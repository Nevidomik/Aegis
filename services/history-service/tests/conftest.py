from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock
from uuid import UUID

import fastapi.dependencies.utils
import fastapi.routing
import pytest
from history_service.blacklist_read import get_blacklist_read_service
from history_service.database import get_session
from history_service.main import app
from history_service.models import IpCheckHistory
from history_service.provider_client import get_provider_client
from history_service.service import get_application_service, get_history_service
from httpx2 import ASGITransport, AsyncClient

REQUEST_ID = UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd")


def check_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": str(REQUEST_ID),
        "ip_address": "8.8.8.8",
        "ip_version": 4,
        "is_public": True,
        "is_whitelisted": None,
        "abuse_confidence_score": 0,
        "country_code": "US",
        "usage_type": "Data Center/Web Hosting/Transit",
        "isp": "Google LLC",
        "domain": "google.com",
        "total_reports": 0,
        "num_distinct_users": 0,
        "last_reported_at": None,
        "max_age_days": 90,
        "source": "AbuseIPDB",
        "checked_at": "2026-07-15T18:30:00Z",
    }
    payload.update(overrides)
    return payload


def history_record(*, history_id: int = 145) -> IpCheckHistory:
    return IpCheckHistory(
        id=history_id,
        request_id=str(REQUEST_ID),
        ip_address="8.8.8.8",
        ip_version=4,
        is_public=True,
        is_whitelisted=None,
        abuse_confidence_score=0,
        country_code="US",
        usage_type="Data Center/Web Hosting/Transit",
        isp="Google LLC",
        domain="google.com",
        total_reports=0,
        num_distinct_users=0,
        last_reported_at=None,
        max_age_days=90,
        source="AbuseIPDB",
        checked_at=datetime(2026, 7, 15, 18, 30, tzinfo=UTC).replace(tzinfo=None),
    )


@pytest.fixture
def session() -> Mock:
    return Mock()


@pytest.fixture
async def client(session: Mock) -> AsyncIterator[AsyncClient]:
    async def session_override() -> AsyncIterator[object]:
        yield session

    app.dependency_overrides[get_session] = session_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def execute_sync_routes_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid worker-thread restrictions in the test sandbox."""

    async def run_inline(function: Any, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    monkeypatch.setattr(fastapi.routing, "run_in_threadpool", run_inline)
    monkeypatch.setattr(fastapi.dependencies.utils, "run_in_threadpool", run_inline)


@pytest.fixture
def override_service() -> Iterator[Any]:
    def apply(service: object) -> None:
        async def service_override() -> object:
            return service

        app.dependency_overrides[get_history_service] = service_override

    yield apply
    app.dependency_overrides.pop(get_history_service, None)


@pytest.fixture
def override_dependency() -> Iterator[Any]:
    def apply(dependency: object, replacement: object) -> None:
        def dependency_override() -> object:
            return replacement

        app.dependency_overrides[dependency] = dependency_override

    yield apply
    app.dependency_overrides.pop(get_application_service, None)
    app.dependency_overrides.pop(get_provider_client, None)
    app.dependency_overrides.pop(get_blacklist_read_service, None)
