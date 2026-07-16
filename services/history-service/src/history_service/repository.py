"""Persistence operations for IP check history."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from history_service.models import IpCheckHistory
from history_service.schemas import CheckCreate


class HistoryRepository:
    """Query and mutate History records through a supplied session."""

    def add(self, session: Session, payload: CheckCreate) -> IpCheckHistory:
        data = payload.model_dump()
        data["request_id"] = str(payload.request_id)
        for timestamp_field in ("last_reported_at", "checked_at"):
            value = data[timestamp_field]
            data[timestamp_field] = value.replace(tzinfo=None) if value else None
        record = IpCheckHistory(**data)
        session.add(record)
        session.flush()
        return record

    def get_by_id(self, session: Session, history_id: int) -> IpCheckHistory | None:
        return session.get(IpCheckHistory, history_id)

    def get_by_request_id(
        self, session: Session, request_id: str
    ) -> IpCheckHistory | None:
        statement = select(IpCheckHistory).where(
            IpCheckHistory.request_id == request_id
        )
        return session.scalar(statement)

    def list(
        self,
        session: Session,
        *,
        limit: int,
        offset: int,
        normalized_ip: str | None,
    ) -> list[IpCheckHistory]:
        statement = select(IpCheckHistory)
        if normalized_ip is not None:
            statement = statement.where(IpCheckHistory.ip_address == normalized_ip)
        statement = (
            statement.order_by(IpCheckHistory.id.desc()).limit(limit).offset(offset)
        )
        return list(session.scalars(statement))

    def count(self, session: Session, *, normalized_ip: str | None) -> int:
        statement = select(func.count()).select_from(IpCheckHistory)
        if normalized_ip is not None:
            statement = statement.where(IpCheckHistory.ip_address == normalized_ip)
        return session.scalar(statement) or 0
