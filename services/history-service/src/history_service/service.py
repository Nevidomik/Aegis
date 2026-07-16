"""Business operations for persistent lookup history."""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from history_service.models import IpCheckHistory
from history_service.repository import HistoryRepository
from history_service.schemas import CheckCreate, HistoryListQuery


class HistoryUnavailableError(Exception):
    """Raised when MariaDB cannot complete a History operation."""


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


class HistoryService:
    """Coordinate transactions and idempotency."""

    def __init__(self, repository: HistoryRepository | None = None) -> None:
        self.repository = repository or HistoryRepository()

    def create(self, session: Session, payload: CheckCreate) -> CreateResult:
        request_id = str(payload.request_id)
        try:
            existing = self.repository.get_by_request_id(session, request_id)
            if existing is not None:
                return CreateResult(record=existing, created=False)

            try:
                record = self.repository.add(session, payload)
                session.commit()
                return CreateResult(record=record, created=True)
            except IntegrityError:
                session.rollback()
                existing = self.repository.get_by_request_id(session, request_id)
                if existing is None:
                    raise
                return CreateResult(record=existing, created=False)
        except SQLAlchemyError as error:
            session.rollback()
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


history_service = HistoryService()


async def get_history_service() -> HistoryService:
    """Return the stateless History service."""
    return history_service
