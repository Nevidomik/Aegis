"""Internal reputation proxy orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import ip_address

from provider_service.provider import AbuseIPDBProvider
from provider_service.schemas import (
    InternalReputationRequest,
    InternalReputationResponse,
)


class ReputationProxyService:
    """Call the configured provider and return the normalized internal contract."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    async def check(
        self,
        request: InternalReputationRequest,
        provider: AbuseIPDBProvider,
    ) -> InternalReputationResponse:
        reputation = await provider.lookup(
            ip_address(request.ip_address), request.max_age_days
        )
        return InternalReputationResponse(
            max_age_days=request.max_age_days,
            checked_at=self.clock(),
            **reputation.model_dump(),
        )


reputation_proxy_service = ReputationProxyService()


async def get_reputation_proxy_service() -> ReputationProxyService:
    return reputation_proxy_service
