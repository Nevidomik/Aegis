# Aegis

Small multi-service application for checking the reputation of public IPv4 and IPv6 addresses through the AbuseIPDB API and storing successful checks in MariaDB.

## Architecture

```text
Browser
  │
  ▼
UI Service ──HTTP──> Backend Service ──HTTPS──> AbuseIPDB
                         │
                         └──HTTP──> History Service ──SQL──> MariaDB
```

Service responsibilities:

- **UI Service** — renders the form, current result, and history. Communicates only with Backend.
- **Backend Service** — validates IP addresses, calls AbuseIPDB, normalizes responses, and sends successful results to History.
- **History Service** — owns persistence and is the only service allowed to access MariaDB.

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
├── backend-service/
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
cp services/backend-service/.env.example services/backend-service/.env
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

The first version must support:

- checking a public IPv4 or IPv6 address;
- displaying the normalized AbuseIPDB result;
- storing every successful check;
- viewing previous checks;
- clear separation between the three services.

Not included yet:

- authentication;
- Docker or Kubernetes;
- CI/CD;
- message queues;
- caching;
- cloud deployment.

## Documentation

- [Architecture](docs/architecture.md)
- [API contracts](docs/api-contracts.md)
- [Architecture decisions](docs/adr/)
