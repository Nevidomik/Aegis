from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID

import pytest
from history_service.exceptions import (
    InvalidIPAddressError,
    NonPublicIPAddressError,
    ProviderServiceUnavailableError,
)
from history_service.provider_client import ProviderClient
from history_service.repository import HistoryRepository
from history_service.schemas import (
    ApplicationCheckRequest,
    CheckCreate,
    ProviderReputationResponse,
)
from history_service.service import (
    ApplicationService,
    CreateResult,
    HistoryService,
    HistoryUnavailableError,
    IdempotencyConflictError,
)
from sqlalchemy.exc import IntegrityError, OperationalError

from .conftest import check_payload, history_record

REQUEST_ID = UUID("6f5aa064-43e8-4dbb-a544-d60b68af5cbd")


def provider_response(
    *, ip_address: str = "8.8.8.8", ip_version: int = 4
) -> ProviderReputationResponse:
    payload = check_payload()
    payload.pop("request_id")
    payload["ip_address"] = ip_address
    payload["ip_version"] = ip_version
    return ProviderReputationResponse.model_validate(payload)


def test_create_returns_existing_record_without_writing() -> None:
    existing = history_record()
    repository = Mock(spec=HistoryRepository)
    repository.get_by_request_id.return_value = existing
    session = Mock()

    result = HistoryService(repository).create(
        session, CheckCreate.model_validate(check_payload())
    )

    assert result.record is existing
    assert result.created is False
    repository.add.assert_not_called()
    session.commit.assert_not_called()


def test_create_recovers_from_concurrent_duplicate() -> None:
    existing = history_record()
    repository = Mock(spec=HistoryRepository)
    repository.get_by_request_id.side_effect = [None, existing]
    repository.add.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    session = Mock()

    result = HistoryService(repository).create(
        session, CheckCreate.model_validate(check_payload())
    )

    assert result.record is existing
    assert result.created is False
    session.rollback.assert_called_once()


def test_create_rejects_existing_request_id_with_different_payload() -> None:
    existing = history_record()
    repository = Mock(spec=HistoryRepository)
    repository.get_by_request_id.return_value = existing
    session = Mock()

    conflicting_payload = CheckCreate.model_validate(check_payload(max_age_days=30))

    try:
        HistoryService(repository).create(session, conflicting_payload)
    except IdempotencyConflictError:
        pass
    else:
        raise AssertionError("Expected IdempotencyConflictError")

    repository.add.assert_not_called()
    session.commit.assert_not_called()


def test_create_rejects_concurrent_duplicate_with_different_payload() -> None:
    existing = history_record()
    repository = Mock(spec=HistoryRepository)
    repository.get_by_request_id.side_effect = [None, existing]
    repository.add.side_effect = IntegrityError("insert", {}, Exception("duplicate"))
    session = Mock()

    conflicting_payload = CheckCreate.model_validate(check_payload(max_age_days=30))

    try:
        HistoryService(repository).create(session, conflicting_payload)
    except IdempotencyConflictError:
        pass
    else:
        raise AssertionError("Expected IdempotencyConflictError")

    session.rollback.assert_called_once()


def test_database_errors_are_wrapped_without_details() -> None:
    repository = Mock(spec=HistoryRepository)
    repository.get_by_id.side_effect = OperationalError(
        "select", {}, Exception("password leaked")
    )

    try:
        HistoryService(repository).get(Mock(), 1)
    except HistoryUnavailableError as error:
        assert str(error) == ""
    else:
        raise AssertionError("Expected HistoryUnavailableError")


def test_application_check_normalizes_calls_provider_and_persists() -> None:
    history = Mock(spec=HistoryService)
    history.get_by_request_id.return_value = None
    history.create.return_value = CreateResult(record=history_record(), created=True)
    provider = Mock(spec=ProviderClient)
    provider.check.return_value = provider_response(
        ip_address="2606:4700:4700::1111", ip_version=6
    )

    result = ApplicationService(history).check(
        Mock(),
        ApplicationCheckRequest(
            ip_address="2606:4700:4700:0:0:0:0:1111", max_age_days=90
        ),
        REQUEST_ID,
        provider,
    )

    assert result.created is True
    proxy_payload = provider.check.call_args.args[0]
    assert proxy_payload.ip_address == "2606:4700:4700::1111"
    assert provider.check.call_args.kwargs["request_id"] == str(REQUEST_ID)
    persisted = history.create.call_args.args[1]
    assert persisted.request_id == REQUEST_ID
    assert persisted.checked_at == datetime(2026, 7, 15, 18, 30, tzinfo=UTC)


def test_application_check_returns_idempotent_record_before_provider_call() -> None:
    existing = history_record()
    history = Mock(spec=HistoryService)
    history.get_by_request_id.return_value = existing
    provider = Mock(spec=ProviderClient)

    result = ApplicationService(history).check(
        Mock(),
        ApplicationCheckRequest(ip_address="8.8.8.8", max_age_days=90),
        REQUEST_ID,
        provider,
    )

    assert result == CreateResult(record=existing, created=False)
    provider.check.assert_not_called()
    history.create.assert_not_called()


def test_application_check_conflict_stops_before_provider_call() -> None:
    history = Mock(spec=HistoryService)
    history.get_by_request_id.return_value = history_record()
    provider = Mock(spec=ProviderClient)

    with pytest.raises(IdempotencyConflictError):
        ApplicationService(history).check(
            Mock(),
            ApplicationCheckRequest(ip_address="1.1.1.1", max_age_days=90),
            REQUEST_ID,
            provider,
        )

    provider.check.assert_not_called()
    history.create.assert_not_called()


def test_application_check_does_not_persist_invalid_or_failed_lookups() -> None:
    history = Mock(spec=HistoryService)
    history.get_by_request_id.return_value = None
    provider = Mock(spec=ProviderClient)
    provider.check.side_effect = ProviderServiceUnavailableError()

    with pytest.raises(NonPublicIPAddressError):
        ApplicationService(history).check(
            Mock(),
            ApplicationCheckRequest(ip_address="127.0.0.1", max_age_days=90),
            REQUEST_ID,
            provider,
        )
    with pytest.raises(ProviderServiceUnavailableError):
        ApplicationService(history).check(
            Mock(),
            ApplicationCheckRequest(ip_address="8.8.8.8", max_age_days=90),
            REQUEST_ID,
            provider,
        )

    history.create.assert_not_called()


def test_application_check_rejects_malformed_ip_before_dependencies() -> None:
    history = Mock(spec=HistoryService)
    provider = Mock(spec=ProviderClient)

    with pytest.raises(InvalidIPAddressError):
        ApplicationService(history).check(
            Mock(),
            ApplicationCheckRequest(ip_address="not-an-ip", max_age_days=90),
            REQUEST_ID,
            provider,
        )

    history.get_by_request_id.assert_not_called()
    provider.check.assert_not_called()
