# Aegis

A small multi-service IP reputation application.

Aegis checks public IPv4 and IPv6 addresses through AbuseIPDB and periodically
synchronizes a limited AbuseIPDB blacklist into MariaDB.

The web interface displays the latest locally persisted blacklist snapshot and
updates automatically when a newer snapshot becomes available.

## Architecture

```text
Browser
  │
  ▼
UI Service ──HTTP──> History Service ──HTTP──> Provider Service
                         │                    │
                         ▼                    └──HTTPS──> AbuseIPDB
                      MariaDB
```

Scheduled blacklist flow:

History Service scheduler
  -> Provider Service
  -> AbuseIPDB Blacklist API
  -> History Service
  -> MariaDB

Service responsibilities:

- **UI Service** — renders the interface and communicates only with History Service.

- **History Service** — acts as the application backend, exclusively owns MariaDB, runs blacklist synchronization, and stores complete blacklist snapshots.

- **Provider Service** — acts as an internal AbuseIPDB adapter. It validates and normalizes provider responses but does not persist data or run scheduled jobs.

More details: [`docs/architecture.md`](docs/architecture.md)

## Planned stack

- Python 3
- FastAPI
- Jinja2
- HTTPX
- Pydantic
- SQLAlchemy 2.x
- Alembic
- MariaDB
- pytest
- Ruff

## Repository layout

```text
services/
├── ui-service/
├── provider-service/
└── history-service/

docs/
├── architecture.md
├── api-contracts.md
└── adr/
```

## Configuration

Each service loads its own `.env` file using a path anchored to that service, so
commands behave the same from any working directory. Create the local files from
the repository root:

```bash
cp services/ui-service/.env.example services/ui-service/.env
cp services/provider-service/.env.example services/provider-service/.env
cp services/history-service/.env.example services/history-service/.env
```

Replace the placeholders for required secrets. They must never be committed:

- `ABUSEIPDB_API_KEY`
- `MARIADB_PASSWORD`

## Local development

Install `uv` 0.11 (the supported tool range is enforced by the root project),
then create the repository environment from the committed lockfile:

```bash
uv sync --locked --all-packages --all-extras
```

This installs all three independently declared service projects into `.venv`.
Use `uv lock` after an intentional dependency change, review `uv.lock`, and
commit the updated manifest and lockfile together. Normal setup and CI should
use `--locked` so stale dependency metadata fails instead of being resolved
implicitly.

Run a service from the repository root, for example:

```bash
.venv/bin/uvicorn ui_service.main:app \
  --app-dir services/ui-service/src \
  --host 127.0.0.1 \
  --port 8000
```

Verification commands:

```bash
make check
```

Database schema changes must be applied through Alembic migrations. All
migration commands in the History Service README run from the repository root.

## Current scope

The application supports:

- validation of public IPv4 and IPv6 addresses;
- normalized individual AbuseIPDB lookups;
- persistence of successful manual checks;
- scheduled retrieval of up to 1000 blacklist entries;
- complete blacklist snapshots in MariaDB;
- tabular display of the latest successful snapshot;
- automatic UI refresh when a new local snapshot is available;
- rate-limit-aware retry behavior;
- explicit separation between UI, application, and provider responsibilities.

Not included yet:

- authentication;
- charts and analytical dashboards;
- cron or a dedicated scheduler process;
- message queues;
- caching;
- multiple reputation providers;
- Docker or Kubernetes;
- cloud deployment.

## Documentation

- [Architecture](docs/architecture.md)
- [API contracts](docs/api-contracts.md)
- [Architecture decisions](docs/adr/)
