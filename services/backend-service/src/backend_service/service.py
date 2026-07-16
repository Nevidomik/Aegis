"""Backend check orchestration."""

from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv6Address, ip_address
from uuid import UUID

from backend_service.exceptions import InvalidIPAddressError, NonPublicIPAddressError
from backend_service.history_client import HistoryClient
from backend_service.provider import AbuseIPDBProvider
from backend_service.schemas import (
    CheckRequest,
    CheckResponse,
    HistoryCheckCreate,
    HistoryListQuery,
    HistoryListResponse,
)


def parse_public_address(value: str) -> IPv4Address | IPv6Address:
    """Parse and enforce the application's public-address rules."""
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
        address = parse_public_address(request.ip_address)
        reputation = await provider.lookup(address, request.max_age_days)
        history_payload = HistoryCheckCreate(
            request_id=request_id,
            max_age_days=request.max_age_days,
            checked_at=self.clock(),
            **reputation.model_dump(),
        )
        return await history_client.save(history_payload, request_id=str(request_id))


class HistoryReadService:
    """Validate public history reads and delegate them to History."""

    async def list(
        self,
        query: HistoryListQuery,
        request_id: UUID,
        history_client: HistoryClient,
    ) -> HistoryListResponse:
        normalized_ip = None
        if query.ip_address is not None:
            normalized_ip = str(parse_public_address(query.ip_address))
        return await history_client.list(
            limit=query.limit,
            offset=query.offset,
            ip_address=normalized_ip,
            request_id=str(request_id),
        )

    async def get(
        self,
        history_id: int,
        request_id: UUID,
        history_client: HistoryClient,
    ) -> CheckResponse:
        return await history_client.get(history_id, request_id=str(request_id))


check_service = CheckService()
history_read_service = HistoryReadService()


async def get_check_service() -> CheckService:
    return check_service


async def get_history_read_service() -> HistoryReadService:
    return history_read_service
