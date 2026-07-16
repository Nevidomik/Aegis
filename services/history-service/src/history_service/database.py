"""SQLAlchemy engine and request-scoped session management."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from history_service.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create the process-wide lazy SQLAlchemy engine."""
    return create_engine(get_settings().database_url(), pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Create the process-wide session factory."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Generator[Session]:
    """Provide exactly one SQLAlchemy session for an HTTP request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
