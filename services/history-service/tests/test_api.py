from typing import Any
from unittest.mock import Mock
from uuid import UUID

import pytest
from history_service.backend_client import get_backend_client
from history_service.exceptions import BackendUnavailableError
from history_service.schemas import HistoryListQuery
from history_service.service import (
    ApplicationService,
    CreateResult,
    HistoryService,
    HistoryUnavailableError,
    IdempotencyConflictError,
    ListResult,
    get_application_service,
)
from httpx2 import AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from .conftest import check_payload, history_record


class FakeHistoryService:
    def __init__(self) -> None:
        self.created = True
        self.record = history_record()
        self.records = [self.record]
        self.total = 1
        self.requested_query: HistoryListQuery | None = None

    def create(self, _: object, __: object) -> CreateResult:
        return CreateResult(record=self.record, created=self.created)

    def get(self, _: object, history_id: int) -> object:
        return self.record if history_id == self.record.id else None

    def list(self, _: object, query: HistoryListQuery) -> ListResult:
        self.requested_query = query
        return ListResult(records=self.records, total=self.total)


@pytest.mark.anyio
async def test_readiness_executes_database_check(
    client: AsyncClient, session: Mock
) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    statement = session.execute.call_args.args[0]
    assert str(statement) == "SELECT 1"


@pytest.mark.anyio
async def test_readiness_reports_database_failure(
    client: AsyncClient, session: Mock
) -> None:
    session.execute.side_effect = SQLAlchemyError("database details")

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}
    assert "database details" not in response.text


@pytest.mark.anyio
async def test_create_returns_201_for_new_record_and_200_for_duplicate(
    client: AsyncClient, override_service: Any
) -> None:
    service = FakeHistoryService()
    override_service(service)
    headers = {"X-Request-ID": str(check_payload()["request_id"])}

    created_response = await client.post(
        "/internal/v1/checks", json=check_payload(), headers=headers
    )
    service.created = False
    duplicate_response = await client.post(
        "/internal/v1/checks", json=check_payload(), headers=headers
    )

    assert created_response.status_code == 201
    assert duplicate_response.status_code == 200
    assert (
        created_response.json()["history_id"] == duplicate_response.json()["history_id"]
    )
    assert created_response.headers["X-Request-ID"] == headers["X-Request-ID"]
    assert duplicate_response.headers["X-Request-ID"] == headers["X-Request-ID"]


@pytest.mark.anyio
async def test_list_uses_bounded_pagination_and_normalized_filter(
    client: AsyncClient, override_service: Any
) -> None:
    service = FakeHistoryService()
    override_service(service)

    response = await client.get(
        "/internal/v1/checks",
        params={"limit": 10, "offset": 2, "ip_address": "8.8.8.8"},
        headers={"X-Request-ID": str(check_payload()["request_id"])},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert service.requested_query == HistoryListQuery(
        limit=10, offset=2, ip_address="8.8.8.8"
    )


@pytest.mark.anyio
async def test_get_returns_record_or_stable_not_found(
    client: AsyncClient, override_service: Any
) -> None:
    override_service(FakeHistoryService())
    request_id = str(check_payload()["request_id"])

    found = await client.get(
        "/internal/v1/checks/145", headers={"X-Request-ID": request_id}
    )
    missing = await client.get(
        "/internal/v1/checks/999", headers={"X-Request-ID": request_id}
    )

    assert found.status_code == 200
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {
            "code": "HISTORY_RECORD_NOT_FOUND",
            "message": "The requested history record does not exist.",
            "request_id": request_id,
        }
    }
    assert found.headers["X-Request-ID"] == request_id
    assert missing.headers["X-Request-ID"] == request_id


@pytest.mark.anyio
async def test_invalid_request_uses_stable_error_envelope(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/internal/v1/checks",
        params={"limit": 101},
        headers={"X-Request-ID": str(check_payload()["request_id"])},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["error"]["request_id"] == str(check_payload()["request_id"])


@pytest.mark.anyio
async def test_database_failure_is_hidden(
    client: AsyncClient, override_service: Any
) -> None:
    class UnavailableService(FakeHistoryService):
        def list(self, _: object, query: HistoryListQuery) -> ListResult:
            raise HistoryUnavailableError("sensitive database details")

    override_service(UnavailableService())
    request_id = str(check_payload()["request_id"])

    response = await client.get(
        "/internal/v1/checks", headers={"X-Request-ID": request_id}
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "HISTORY_UNAVAILABLE",
            "message": "History storage is temporarily unavailable.",
            "request_id": request_id,
        }
    }
    assert "sensitive" not in response.text


@pytest.mark.anyio
async def test_idempotency_conflict_returns_stable_409(
    client: AsyncClient, override_service: Any
) -> None:
    class ConflictingService(FakeHistoryService):
        def create(self, _: object, __: object) -> CreateResult:
            raise IdempotencyConflictError

    override_service(ConflictingService())
    request_id = str(check_payload()["request_id"])

    response = await client.post(
        "/internal/v1/checks",
        json=check_payload(),
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 409
    assert response.headers["X-Request-ID"] == request_id
    assert response.json() == {
        "error": {
            "code": "IDEMPOTENCY_CONFLICT",
            "message": (
                "The request ID has already been used with different request data."
            ),
            "request_id": request_id,
        }
    }


@pytest.mark.anyio
async def test_request_id_middleware_generates_and_rejects_ids(
    client: AsyncClient,
) -> None:
    generated = await client.get("/health/live")
    invalid = await client.get("/health/live", headers={"X-Request-ID": "not-a-uuid"})

    assert UUID(generated.headers["X-Request-ID"])
    assert generated.status_code == 200
    assert invalid.status_code == 400
    assert UUID(invalid.headers["X-Request-ID"])
    assert invalid.headers["X-Request-ID"] == invalid.json()["error"]["request_id"]


@pytest.mark.anyio
async def test_application_create_propagates_request_id_and_returns_record(
    client: AsyncClient, override_dependency: Any
) -> None:
    class RecordingApplicationService:
        def __init__(self) -> None:
            self.call: dict[str, object] | None = None
            self.created = True

        def check(
            self, session: object, payload: object, request_id: UUID, backend: object
        ) -> CreateResult:
            self.call = {
                "session": session,
                "payload": payload,
                "request_id": request_id,
                "backend": backend,
            }
            return CreateResult(record=history_record(), created=self.created)

    service = RecordingApplicationService()
    backend = object()
    override_dependency(get_application_service, service)
    override_dependency(get_backend_client, backend)

    response = await client.post(
        "/api/v1/checks",
        json={"ip_address": "8.8.8.8", "max_age_days": 90},
        headers={"X-Request-ID": str(check_payload()["request_id"])},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == str(check_payload()["request_id"])
    assert response.json()["history_id"] == 145
    assert response.json()["request_id"] == str(check_payload()["request_id"])
    assert service.call is not None
    assert service.call["request_id"] == UUID(str(check_payload()["request_id"]))
    assert service.call["backend"] is backend

    service.created = False
    duplicate = await client.post(
        "/api/v1/checks",
        json={"ip_address": "8.8.8.8", "max_age_days": 90},
        headers={"X-Request-ID": str(check_payload()["request_id"])},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["history_id"] == response.json()["history_id"]


@pytest.mark.anyio
async def test_application_create_rejects_nonpublic_ip_without_backend_call(
    client: AsyncClient, override_dependency: Any
) -> None:
    history = Mock(spec=HistoryService)
    backend = Mock()
    override_dependency(get_application_service, ApplicationService(history))
    override_dependency(get_backend_client, backend)

    response = await client.post(
        "/api/v1/checks",
        json={"ip_address": "127.0.0.1", "max_age_days": 90},
        headers={"X-Request-ID": str(check_payload()["request_id"])},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NON_PUBLIC_IP_ADDRESS"
    backend.check.assert_not_called()
    history.get_by_request_id.assert_not_called()


@pytest.mark.anyio
async def test_application_proxy_failure_uses_safe_error_envelope(
    client: AsyncClient, override_dependency: Any
) -> None:
    class FailingApplicationService:
        def check(self, *_: object) -> CreateResult:
            raise BackendUnavailableError

    override_dependency(get_application_service, FailingApplicationService())
    override_dependency(get_backend_client, object())
    request_id = str(check_payload()["request_id"])

    response = await client.post(
        "/api/v1/checks",
        json={"ip_address": "8.8.8.8", "max_age_days": 90},
        headers={"X-Request-ID": request_id},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "BACKEND_UNAVAILABLE",
            "message": "The reputation service is temporarily unavailable.",
            "request_id": request_id,
        }
    }


@pytest.mark.anyio
async def test_application_list_and_get_expose_persisted_history(
    client: AsyncClient, override_dependency: Any, override_service: Any
) -> None:
    class ListingApplicationService:
        def list(
            self, _: object, query: HistoryListQuery
        ) -> tuple[ListResult, HistoryListQuery]:
            normalized = HistoryListQuery(
                limit=query.limit, offset=query.offset, ip_address="8.8.8.8"
            )
            return ListResult(records=[history_record()], total=1), normalized

    override_dependency(get_application_service, ListingApplicationService())
    override_service(FakeHistoryService())
    request_id = str(check_payload()["request_id"])

    listed = await client.get(
        "/api/v1/checks",
        params={"ip_address": "8.8.8.8"},
        headers={"X-Request-ID": request_id},
    )
    found = await client.get("/api/v1/checks/145", headers={"X-Request-ID": request_id})
    missing = await client.get(
        "/api/v1/checks/999", headers={"X-Request-ID": request_id}
    )

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert found.status_code == 200
    assert found.json()["history_id"] == 145
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "HISTORY_RECORD_NOT_FOUND"


@pytest.mark.anyio
async def test_application_database_failure_is_mapped_without_details(
    client: AsyncClient, override_dependency: Any
) -> None:
    class UnavailableApplicationService:
        def list(self, *_: object) -> object:
            raise HistoryUnavailableError("sensitive database details")

    override_dependency(get_application_service, UnavailableApplicationService())
    request_id = str(check_payload()["request_id"])

    response = await client.get("/api/v1/checks", headers={"X-Request-ID": request_id})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "DATABASE_UNAVAILABLE",
            "message": "The database is temporarily unavailable.",
            "request_id": request_id,
        }
    }
    assert "sensitive" not in response.text
