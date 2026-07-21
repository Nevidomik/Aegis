import os
from uuid import UUID, uuid4

import pytest
from history_service.models import IpCheckHistory
from history_service.schemas import (
    ApplicationCheckRequest,
    BackendReputationRequest,
    BackendReputationResponse,
    CheckCreate,
    HistoryListQuery,
)
from history_service.service import ApplicationService, HistoryService
from sqlalchemy import URL, create_engine, delete
from sqlalchemy.orm import Session

from .conftest import check_payload

pytestmark = pytest.mark.mariadb


def test_create_idempotency_listing_and_filtering_against_mariadb() -> None:
    if os.getenv("RUN_MARIADB_TESTS") != "1":
        pytest.skip("Set RUN_MARIADB_TESTS=1 for MariaDB integration tests.")

    required = {
        name: os.getenv(name)
        for name in (
            "TEST_MARIADB_DATABASE",
            "TEST_MARIADB_USER",
            "TEST_MARIADB_PASSWORD",
        )
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.fail(f"Missing MariaDB test settings: {', '.join(missing)}")

    url = URL.create(
        "mariadb+pymysql",
        username=required["TEST_MARIADB_USER"],
        password=required["TEST_MARIADB_PASSWORD"],
        host=os.getenv("TEST_MARIADB_HOST", "127.0.0.1"),
        port=int(os.getenv("TEST_MARIADB_PORT", "3306")),
        database=required["TEST_MARIADB_DATABASE"],
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(url, pool_pre_ping=True)
    request_id = str(uuid4())
    payload = CheckCreate.model_validate(check_payload(request_id=request_id))
    service = HistoryService()

    try:
        with Session(engine, expire_on_commit=False) as session:
            first = service.create(session, payload)
            duplicate = service.create(session, payload)
            page = service.list(
                session, HistoryListQuery(ip_address=payload.ip_address)
            )

            assert first.created is True
            assert duplicate.created is False
            assert duplicate.record.id == first.record.id
            assert any(record.id == first.record.id for record in page.records)
    finally:
        with Session(engine) as cleanup_session:
            cleanup_session.execute(
                delete(IpCheckHistory).where(IpCheckHistory.request_id == request_id)
            )
            cleanup_session.commit()
        engine.dispose()


def test_application_lookup_persists_and_resolves_idempotency_against_mariadb() -> None:
    if os.getenv("RUN_MARIADB_TESTS") != "1":
        pytest.skip("Set RUN_MARIADB_TESTS=1 for MariaDB integration tests.")

    required = {
        name: os.getenv(name)
        for name in (
            "TEST_MARIADB_DATABASE",
            "TEST_MARIADB_USER",
            "TEST_MARIADB_PASSWORD",
        )
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.fail(f"Missing MariaDB test settings: {', '.join(missing)}")

    class FakeBackend:
        def __init__(self) -> None:
            self.calls = 0

        def check(
            self, payload: BackendReputationRequest, *, request_id: str
        ) -> BackendReputationResponse:
            self.calls += 1
            data = check_payload(request_id=request_id)
            data.pop("request_id")
            data["ip_address"] = payload.ip_address
            data["max_age_days"] = payload.max_age_days
            return BackendReputationResponse.model_validate(data)

    url = URL.create(
        "mariadb+pymysql",
        username=required["TEST_MARIADB_USER"],
        password=required["TEST_MARIADB_PASSWORD"],
        host=os.getenv("TEST_MARIADB_HOST", "127.0.0.1"),
        port=int(os.getenv("TEST_MARIADB_PORT", "3306")),
        database=required["TEST_MARIADB_DATABASE"],
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(url, pool_pre_ping=True)
    request_id = UUID(str(uuid4()))
    backend = FakeBackend()
    service = ApplicationService(HistoryService())
    payload = ApplicationCheckRequest(ip_address="8.8.8.8", max_age_days=90)

    try:
        with Session(engine, expire_on_commit=False) as session:
            first = service.check(session, payload, request_id, backend)
            duplicate = service.check(session, payload, request_id, backend)

            assert first.created is True
            assert duplicate.created is False
            assert duplicate.record.id == first.record.id
            assert backend.calls == 1
    finally:
        with Session(engine) as cleanup_session:
            cleanup_session.execute(
                delete(IpCheckHistory).where(
                    IpCheckHistory.request_id == str(request_id)
                )
            )
            cleanup_session.commit()
        engine.dispose()
