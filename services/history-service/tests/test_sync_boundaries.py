from inspect import iscoroutinefunction, isgeneratorfunction

from history_service.database import get_session
from history_service.routes import (
    create_application_check,
    get_application_check,
    list_application_checks,
)


def test_database_handlers_and_session_dependency_are_synchronous() -> None:
    assert isgeneratorfunction(get_session)
    assert not iscoroutinefunction(create_application_check)
    assert not iscoroutinefunction(list_application_checks)
    assert not iscoroutinefunction(get_application_check)
