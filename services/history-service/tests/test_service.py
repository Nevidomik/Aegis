from unittest.mock import Mock

from history_service.repository import HistoryRepository
from history_service.schemas import CheckCreate
from history_service.service import (
    HistoryService,
    HistoryUnavailableError,
    IdempotencyConflictError,
)
from sqlalchemy.exc import IntegrityError, OperationalError

from .conftest import check_payload, history_record


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

    conflicting_payload = CheckCreate.model_validate(
        check_payload(abuse_confidence_score=99)
    )

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

    conflicting_payload = CheckCreate.model_validate(
        check_payload(abuse_confidence_score=99)
    )

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
