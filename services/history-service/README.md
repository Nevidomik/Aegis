# History Service

The History service is Aegis's application backend and persistence owner. It is
the only service that connects to MariaDB, and it calls Provider Service's
internal proxy for normalized reputation data. It uses synchronous HTTPX,
SQLAlchemy sessions, and Alembic migrations.

## Configuration

Create the service-local file from the repository root:

```bash
cp services/history-service/.env.example services/history-service/.env
```

History and Alembic load that same file explicitly regardless of the current
working directory:

```dotenv
MARIADB_HOST=127.0.0.1
MARIADB_PORT=3306
MARIADB_DATABASE=aegis_history
MARIADB_USER=aegis_history
MARIADB_PASSWORD=replace-me
PROVIDER_SERVICE_URL=http://127.0.0.1:8001
PROVIDER_CONNECT_TIMEOUT_SECONDS=5
PROVIDER_READ_TIMEOUT_SECONDS=10
PROVIDER_WRITE_TIMEOUT_SECONDS=5
PROVIDER_POOL_TIMEOUT_SECONDS=5
PROVIDER_INGESTION_TOKEN=replace-with-at-least-32-characters
BLACKLIST_STALE_AFTER_SECONDS=43200
```

`MARIADB_DATABASE`, `MARIADB_USER`, and `MARIADB_PASSWORD` are required. The
host defaults to `127.0.0.1` and the port defaults to `3306`. Do not commit real
credentials.

## Blacklist ingestion

History does not run a periodic blacklist scheduler. The standalone Provider
worker owns polling and sends normalized snapshots to the authenticated
`POST /internal/v1/blacklist/snapshots` endpoint. History remains the sole
MariaDB owner and saves accepted deliveries transactionally.

Every accepted snapshot and all of its entries are retained in the initial
implementation. There is no automatic pruning or retention window.

## Application API

History exposes `POST /api/v1/checks`, `GET /api/v1/checks`, and
`GET /api/v1/checks/{history_id}` for UI Service. A valid `X-Request-ID` is
propagated to Provider Service and used for create idempotency. Successful proxy
responses are validated before persistence; failed lookups are not persisted.

History exposes no internal persistence API. Provider Service never calls History
Service; it only returns normalized provider data to History's application
orchestration layer.

The blacklist read API consists of `GET /api/v1/blacklist/status`,
`GET /api/v1/blacklist`, `GET /api/v1/blacklist/snapshots`, and
`GET /api/v1/blacklist/snapshots/{snapshot_id}`. These endpoints read MariaDB
only and never call Provider Service or trigger synchronization.

The existing manual-check table remains supported by the manual-check API.
Blacklist synchronization does not read, truncate, delete, or write that table.

Install the service from the repository root:

```bash
uv sync --locked --all-packages --all-extras
```

## Migrations

Create a migration after changing ORM metadata:

```bash
.venv/bin/alembic -c services/history-service/alembic.ini \
  revision --autogenerate -m "describe schema change"
```

Review every generated migration before applying it. Apply and verify migrations:

```bash
.venv/bin/alembic -c services/history-service/alembic.ini upgrade head
.venv/bin/alembic -c services/history-service/alembic.ini current --check-heads
.venv/bin/alembic -c services/history-service/alembic.ini check
```

To validate downgrade behavior against a disposable database only:

```bash
.venv/bin/alembic -c services/history-service/alembic.ini downgrade base
.venv/bin/alembic -c services/history-service/alembic.ini upgrade head
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
MARIADB_HOST="$TEST_MARIADB_HOST" \
MARIADB_PORT="$TEST_MARIADB_PORT" \
MARIADB_DATABASE="$TEST_MARIADB_DATABASE" \
MARIADB_USER="$TEST_MARIADB_USER" \
MARIADB_PASSWORD="$TEST_MARIADB_PASSWORD" \
  .venv/bin/alembic -c services/history-service/alembic.ini upgrade head
.venv/bin/pytest -m mariadb services/history-service/tests
```
