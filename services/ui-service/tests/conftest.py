from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from httpx2 import ASGITransport, AsyncClient
from ui_service.application_client import (
    ApplicationClientError,
    get_application_client,
)
from ui_service.main import app
from ui_service.schemas import (
    BlacklistEntry,
    BlacklistPage,
    BlacklistSnapshotSummary,
    BlacklistStatus,
    CheckResult,
    HistoryPage,
)

REQUEST_ID = UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd")


def check_result(*, history_id: int = 145, ip_address: str = "8.8.8.8") -> CheckResult:
    return CheckResult(
        request_id=REQUEST_ID,
        history_id=history_id,
        ip_address=ip_address,
        ip_version=6 if ":" in ip_address else 4,
        is_public=True,
        is_whitelisted=None,
        abuse_confidence_score=12,
        country_code="US",
        usage_type="Data Center/Web Hosting/Transit",
        isp="Example ISP",
        domain="example.test",
        total_reports=7,
        num_distinct_users=3,
        last_reported_at=None,
        max_age_days=30,
        source="AbuseIPDB",
        checked_at=datetime(2026, 7, 15, 18, 30, tzinfo=UTC),
    )


class FakeApplicationClient:
    def __init__(self) -> None:
        self.result = check_result()
        self.history = HistoryPage(items=[self.result], limit=20, offset=0, total=1)
        self.check_error: str | None = None
        self.history_error: str | None = None
        self.check_request: dict[str, object] | None = None
        self.history_request_id: str | None = None
        self.ready_error: str | None = None
        self.ready_request_id: str | None = None
        self.blacklist_status_result = BlacklistStatus(
            state="ready",
            sync_in_progress=False,
            latest_snapshot_id=42,
            latest_provider_generated_at=datetime(2026, 7, 22, 12, tzinfo=UTC),
            latest_fetched_at=datetime(2026, 7, 22, 12, 0, 2, tzinfo=UTC),
            last_attempt_at=datetime(2026, 7, 22, 12, tzinfo=UTC),
            last_success_at=datetime(2026, 7, 22, 12, 0, 4, tzinfo=UTC),
            next_attempt_at=datetime(2026, 7, 22, 18, 0, 4, tzinfo=UTC),
            rate_limit_limit=5,
            rate_limit_remaining=4,
            rate_limit_reset_at=datetime(2026, 7, 23, tzinfo=UTC),
            data_stale=False,
            last_error=None,
        )
        self.blacklist_page = BlacklistPage(
            snapshot=BlacklistSnapshotSummary(
                snapshot_id=42,
                provider="AbuseIPDB",
                provider_generated_at=datetime(2026, 7, 22, 12, tzinfo=UTC),
                fetched_at=datetime(2026, 7, 22, 12, 0, 2, tzinfo=UTC),
                confidence_minimum=90,
                requested_limit=1000,
                returned_count=2,
            ),
            items=[
                BlacklistEntry(
                    ip_address="8.8.8.8",
                    ip_version=4,
                    abuse_confidence_score=100,
                    country_code="US",
                    last_reported_at=datetime(2026, 7, 22, 11, 47, tzinfo=UTC),
                ),
                BlacklistEntry(
                    ip_address="2606:4700:4700::1111",
                    ip_version=6,
                    abuse_confidence_score=95,
                    country_code=None,
                    last_reported_at=None,
                ),
            ],
            limit=100,
            offset=0,
            total=2,
        )
        self.blacklist_status_error: str | None = None
        self.blacklist_error: str | None = None
        self.blacklist_status_request_id: str | None = None
        self.blacklist_request: dict[str, object] | None = None

    async def ready(self, *, request_id: str) -> None:
        self.ready_request_id = request_id
        if self.ready_error is not None:
            raise ApplicationClientError(self.ready_error)

    async def check(
        self, *, ip_address: str, max_age_days: int, request_id: str
    ) -> CheckResult:
        self.check_request = {
            "ip_address": ip_address,
            "max_age_days": max_age_days,
            "request_id": request_id,
        }
        if self.check_error is not None:
            raise ApplicationClientError(self.check_error)
        return self.result.model_copy(
            update={"ip_address": ip_address, "max_age_days": max_age_days}
        )

    async def recent_history(self, *, request_id: str) -> HistoryPage:
        self.history_request_id = request_id
        if self.history_error is not None:
            raise ApplicationClientError(self.history_error)
        return self.history

    async def blacklist_status(self, *, request_id: str) -> BlacklistStatus:
        self.blacklist_status_request_id = request_id
        if self.blacklist_status_error is not None:
            raise ApplicationClientError(self.blacklist_status_error)
        return self.blacklist_status_result

    async def blacklist(
        self, *, limit: int, offset: int, request_id: str
    ) -> BlacklistPage:
        self.blacklist_request = {
            "limit": limit,
            "offset": offset,
            "request_id": request_id,
        }
        if self.blacklist_error is not None:
            raise ApplicationClientError(self.blacklist_error)
        return self.blacklist_page.model_copy(update={"limit": limit, "offset": offset})


@pytest.fixture
def application_client() -> FakeApplicationClient:
    return FakeApplicationClient()


@pytest.fixture
async def client(
    application_client: FakeApplicationClient,
) -> AsyncIterator[AsyncClient]:
    async def application_client_override() -> FakeApplicationClient:
        return application_client

    app.dependency_overrides[get_application_client] = application_client_override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
