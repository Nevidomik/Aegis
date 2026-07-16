from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def test_offline_migration_does_not_depend_on_working_directory(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service_root = Path(__file__).parents[1]
    config = Config(service_root / "alembic.ini")
    monkeypatch.chdir(tmp_path)

    command.upgrade(config, "head", sql=True)

    captured = capsys.readouterr()
    output = f"{captured.out}\n{captured.err}"
    assert config.get_main_option("sqlalchemy.url") is None
    assert "MARIADB_PASSWORD" not in output
    assert "replace-me" not in output
