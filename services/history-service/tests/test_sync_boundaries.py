from inspect import iscoroutinefunction, isgeneratorfunction

from history_service.database import get_session
from history_service.routes import create_check, get_check, list_checks


def test_database_handlers_and_session_dependency_are_synchronous() -> None:
    assert isgeneratorfunction(get_session)
    assert not iscoroutinefunction(create_check)
    assert not iscoroutinefunction(list_checks)
    assert not iscoroutinefunction(get_check)
