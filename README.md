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

Configuration is supplied through environment variables. Copy the example file:

```bash
cp .env.example .env
```

Later application features will require secrets such as the following; they
must never be committed:

- `ABUSEIPDB_API_KEY`
- `MARIADB_PASSWORD`

## Local development

Create a virtual environment and install each service in editable mode with its
development dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -e './services/ui-service[dev]'
.venv/bin/pip install -e './services/backend-service[dev]'
.venv/bin/pip install -e './services/history-service[dev]'
```

Run a service from the repository root, for example:

```bash
.venv/bin/uvicorn ui_service.main:app \
  --app-dir services/ui-service/src \
  --host 127.0.0.1 \
  --port 8000
```

Verification commands:

```bash
ruff check .
ruff format --check .
pytest
```

Database schema changes must be applied through Alembic migrations.

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
