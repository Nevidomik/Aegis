"""Business operations for persistent lookup history."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from history_service.exceptions import InvalidIPAddressError, NonPublicIPAddressError
from history_service.models import IpCheckHistory
from history_service.repository import HistoryRepository
from history_service.schemas import (
    ApplicationCheckRequest,
    CheckCreate,
    HistoryListQuery,
    ProviderReputationRequest,
    ProviderReputationResponse,
)


class HistoryUnavailableError(Exception):
    """Raised when MariaDB cannot complete a History operation."""


class IdempotencyConflictError(Exception):
    """Raised when one request ID is reused for different normalized data."""


@dataclass(frozen=True)
class CreateResult:
    """Result of an idempotent create operation."""

    record: IpCheckHistory
    created: bool


@dataclass(frozen=True)
class ListResult:
    """Records and total for one query page."""

    records: list[IpCheckHistory]
    total: int


class ProviderGateway(Protocol):
    """Minimal internal proxy behavior required by application orchestration."""

    def check(
        self, payload: ProviderReputationRequest, *, request_id: str
    ) -> ProviderReputationResponse: ...


class HistoryService:
    """Coordinate transactions and idempotency."""

    def __init__(self, repository: HistoryRepository | None = None) -> None:
        self.repository = repository or HistoryRepository()

    def create(self, session: Session, payload: CheckCreate) -> CreateResult:
        request_id = str(payload.request_id)
        try:
            existing = self.repository.get_by_request_id(session, request_id)
            if existing is not None:
                return self._existing_result(existing, payload)

            try:
                record = self.repository.add(session, payload)
                session.commit()
                return CreateResult(record=record, created=True)
            except IntegrityError:
                session.rollback()
                existing = self.repository.get_by_request_id(session, request_id)
                if existing is None:
                    raise
                return self._existing_result(existing, payload)
        except SQLAlchemyError as error:
            session.rollback()
            raise HistoryUnavailableError from error

    @classmethod
    def _existing_result(
        cls, existing: IpCheckHistory, payload: CheckCreate
    ) -> CreateResult:
        if not cls._equivalent(existing, payload):
            raise IdempotencyConflictError
        return CreateResult(record=existing, created=False)

    @staticmethod
    def _equivalent(existing: IpCheckHistory, payload: CheckCreate) -> bool:
        return (
            existing.ip_address == payload.ip_address
            and existing.max_age_days == payload.max_age_days
        )

    def get_by_request_id(
        self, session: Session, request_id: str
    ) -> IpCheckHistory | None:
        try:
            return self.repository.get_by_request_id(session, request_id)
        except SQLAlchemyError as error:
            raise HistoryUnavailableError from error

    def get(self, session: Session, history_id: int) -> IpCheckHistory | None:
        try:
            return self.repository.get_by_id(session, history_id)
        except SQLAlchemyError as error:
            raise HistoryUnavailableError from error

    def list(self, session: Session, query: HistoryListQuery) -> ListResult:
        try:
            records = self.repository.list(
                session,
                limit=query.limit,
                offset=query.offset,
                normalized_ip=query.ip_address,
            )
            total = self.repository.count(session, normalized_ip=query.ip_address)
            return ListResult(records=records, total=total)
        except SQLAlchemyError as error:
            raise HistoryUnavailableError from error


def parse_public_address(value: str) -> IPv4Address | IPv6Address:
    """Parse, normalize, and enforce application public-address rules."""
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


class ApplicationService:
    """Orchestrate application requests across persistence and Provider."""

    def __init__(self, history: HistoryService | None = None) -> None:
        self.history = history or HistoryService()

    def check(
        self,
        session: Session,
        payload: ApplicationCheckRequest,
        request_id: UUID,
        provider: ProviderGateway,
    ) -> CreateResult:
        address = parse_public_address(payload.ip_address)
        normalized_ip = str(address)
        existing = self.history.get_by_request_id(session, str(request_id))
        if existing is not None:
            if (
                existing.ip_address != normalized_ip
                or existing.max_age_days != payload.max_age_days
            ):
                raise IdempotencyConflictError
            return CreateResult(record=existing, created=False)

        provider_result = provider.check(
            ProviderReputationRequest(
                ip_address=normalized_ip,
                max_age_days=payload.max_age_days,
            ),
            request_id=str(request_id),
        )
        persistence_payload = CheckCreate(
            request_id=request_id,
            **provider_result.model_dump(),
        )
        return self.history.create(session, persistence_payload)

    def list(
        self, session: Session, query: HistoryListQuery
    ) -> tuple[ListResult, HistoryListQuery]:
        normalized_ip = None
        if query.ip_address is not None:
            normalized_ip = str(parse_public_address(query.ip_address))
        normalized_query = HistoryListQuery(
            limit=query.limit,
            offset=query.offset,
            ip_address=normalized_ip,
        )
        return self.history.list(session, normalized_query), normalized_query


history_service = HistoryService()
application_service = ApplicationService(history_service)


def get_history_service() -> HistoryService:
    """Return the stateless History service."""
    return history_service


def get_application_service() -> ApplicationService:
    """Return the stateless application orchestration service."""
    return application_service
