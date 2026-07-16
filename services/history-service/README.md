# History Service

The History service owns Aegis persistence and is the only service that connects
to MariaDB. It uses synchronous SQLAlchemy sessions and Alembic migrations.

## Configuration

Export these variables before starting the service or running Alembic:

```dotenv
MARIADB_HOST=127.0.0.1
MARIADB_PORT=3306
MARIADB_DATABASE=aegis_history
MARIADB_USER=aegis_history
MARIADB_PASSWORD=replace-me
```

`MARIADB_DATABASE`, `MARIADB_USER`, and `MARIADB_PASSWORD` are required. The
host defaults to `127.0.0.1` and the port defaults to `3306`. Do not commit real
credentials.

Install the service from the repository root:

```bash
.venv/bin/pip install -e './services/history-service[dev]'
```

## Migrations

Create a migration after changing ORM metadata:

```bash
cd services/history-service
../../.venv/bin/alembic revision --autogenerate -m "describe schema change"
```

Review every generated migration before applying it. Apply and verify migrations:

```bash
../../.venv/bin/alembic upgrade head
../../.venv/bin/alembic current --check-heads
../../.venv/bin/alembic check
```

To validate downgrade behavior against a disposable database only:

```bash
../../.venv/bin/alembic downgrade base
../../.venv/bin/alembic upgrade head
```

The application never calls `create_all()`.

## Tests

Normal tests do not require MariaDB. Opt-in integration tests require a dedicated,
migrated test database and these variables:

```dotenv
RUN_MARIADB_TESTS=1
TEST_MARIADB_HOST=127.0.0.1
TEST_MARIADB_PORT=3306
TEST_MARIADB_DATABASE=aegis_history_test
TEST_MARIADB_USER=aegis_history_test
TEST_MARIADB_PASSWORD=replace-me
```

Run them with:

```bash
cd services/history-service
MARIADB_HOST="$TEST_MARIADB_HOST" \
MARIADB_PORT="$TEST_MARIADB_PORT" \
MARIADB_DATABASE="$TEST_MARIADB_DATABASE" \
MARIADB_USER="$TEST_MARIADB_USER" \
MARIADB_PASSWORD="$TEST_MARIADB_PASSWORD" \
  ../../.venv/bin/alembic upgrade head
../../.venv/bin/pytest -m mariadb tests
```
