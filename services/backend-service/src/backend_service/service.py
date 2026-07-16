"""Backend check orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address, ip_address
from uuid import UUID

from backend_service.exceptions import InvalidIPAddressError, NonPublicIPAddressError
from backend_service.history_client import HistoryClient
from backend_service.provider import AbuseIPDBProvider
from backend_service.schemas import CheckRequest, CheckResponse, HistoryCheckCreate


class CheckService:
    """Validate, look up, normalize, and persist one IP check."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    async def check(
        self,
        request: CheckRequest,
        request_id: UUID,
        provider: AbuseIPDBProvider,
        history_client: HistoryClient,
    ) -> CheckResponse:
        address = self._public_address(request.ip_address)
        reputation = await provider.lookup(address, request.max_age_days)
        history_payload = HistoryCheckCreate(
            request_id=request_id,
            max_age_days=request.max_age_days,
            checked_at=self.clock(),
            **reputation.model_dump(),
        )
        return await history_client.save(history_payload, request_id=str(request_id))

    @staticmethod
    def _public_address(value: str) -> IPv4Address | IPv6Address:
        try:
            address = ip_address(value)
        except ValueError as error:
            raise InvalidIPAddressError from error
        if (
            address.is_loopback
            or address.is_private
            or address.is_multicast
            or address.is_link_local
            or address.is_unspecified
            or not address.is_global
        ):
            raise NonPublicIPAddressError
        return address


check_service = CheckService()


async def get_check_service() -> CheckService:
    return check_service
