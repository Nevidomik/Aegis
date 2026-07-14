# AGENTS.md
## Project overview

This repository contains a small multi-service IP reputation application.

The application checks public IPv4 and IPv6 addresses through the AbuseIPDB API
and stores successful lookup history in MariaDB.

The project is an educational DevOps assignment. Priorities are:

1. Clear service boundaries.
2. Code that is easy to understand and explain.
3. Correct application behavior.
4. Reliable tests.
5. Extensibility for later containerization, CI/CD, orchestration, and cloud deployment.

Do not introduce unnecessary infrastructure or abstractions before they are needed.

## Target architecture

The application consists of three services:
- `ui-service`
  - Renders the web interface using FastAPI and Jinja2.
  - Communicates only with `backend-service`.
  - Must not call AbuseIPDB directly.
  - Must not access MariaDB directly.

- `backend-service`
  - Exposes the public application API.
  - Validates user-supplied IP addresses.
  - Calls the AbuseIPDB API.
  - Normalizes upstream responses.
  - Sends successful results to `history-service`.
  - Must not access MariaDB directly.

- `history-service`
  - Owns persistence.
  - Stores and returns lookup history.
  - Is the only service allowed to access MariaDB.
  - Uses SQLAlchemy 2.x and Alembic.

The request flow is:

User -> UI -> Backend
                  ├──> AbuseIPDB
                  └──> History Service -> MariaDB

The UI must never communicate directly with AbuseIPDB, History Service, or MariaDB.

## Technology choices

Use the following unless the task explicitly requires a change:
- Python 3.14 or the version declared by the project
- FastAPI
- Jinja2 for server-rendered UI
- HTTPX for service-to-service and AbuseIPDB requests
- Pydantic v2
- pydantic-settings
- SQLAlchemy 2.x
- Alembic
- MariaDB
- pytest
- Ruff
- mypy or Pyright if already configured

Do not add React, Vue, Node.js, Redis, Celery, Kafka, Kubernetes, or another
database unless the user explicitly approves the architectural change.

## Repository rules

Keep each service independently runnable.

Each service should have:
- its own application package;
- its own dependency declaration;
- its own tests;
- its own configuration model;
- its own README only when service-specific instructions are needed.

Do not create a shared runtime Python package merely to reuse Pydantic models
between services. Service boundaries must remain explicit.

API contracts may be documented in:
- OpenAPI specifications;
- `docs/api-contracts.md`;
- test fixtures;
- contract tests.

## Coding conventions

- Keep route handlers thin.
- Keep business logic outside route handlers.
- Keep database access outside route handlers.
- Use APIRouter.
- Use dependency injection where appropriate.
- Use explicit Pydantic request/response models.
- Never return ORM models directly.
- Prefer simple code over abstractions.
- Use descriptive names.
- Type annotate public APIs.
- Preserve exception causes.

## Reputation lookup

- Use Python's `ipaddress` module.
- Accept IPv4 and IPv6.
- Reject:
  - loopback
  - private
  - multicast
  - link-local
  - unspecified
- Do not validate IPs with regex.
- Normalize addresses before lookup.
- Validate AbuseIPDB responses with Pydantic.
- Use explicit HTTP timeouts.
- Do not enable verbose responses unless requested.

## Persistence rules

Only `history-service` may access MariaDB.

Rules:
- SQLAlchemy 2.x
- Alembic for schema changes
- One session per request
- No create_all() in production
- Review generated migrations
- Store searchable data in columns
- Raw JSON is supplementary only
- request_id must be idempotent

## Configuration and secrets

Configuration that differs between environments must come from environment variables.

Commit `.env.example`, but never commit `.env`.

Do not add real:
- AbuseIPDB API keys;
- MariaDB passwords;
- access tokens;
- credentials;
- private URLs.

When adding a new setting:

1. Add it to the relevant settings model.
2. Add a safe placeholder to `.env.example`.
3. Document it in `docs/development.md` or the relevant README.
4. Add validation where appropriate.

## Error handling

Public errors should use a stable structure similar to:

```json
{
  "error": {
    "code": "INVALID_IP_ADDRESS",
    "message": "The supplied value is not a valid public IP address.",
    "request_id": "..."
  }
}
```
Do not leak:
- stack traces;
- credentials;
- internal URLs;
- SQL statements;
- raw upstream response bodies.

Use appropriate status codes.

Examples:
- 400 invalid or non-public IP;
- 422 invalid request schema;
- 429 application rate limit;
- 502 invalid upstream response;
- 503 unavailable dependency;
- 504 upstream timeout.

## Logging

Write logs to stdout.

Prefer structured logs.

Every request should carry a request ID where practical.

Include useful context such as:
- service name;
- event name;
- request ID;
- duration;
- HTTP status;
- upstream service name.

Do not log:
- API keys;
- passwords;
- complete authorization headers;
- database connection URLs containing credentials.

## Testing requirements

Every meaningful change should include or update tests.
Test behavior, not private implementation details.

At minimum:
- unit tests for validation and normalization;
- integration tests for service endpoints;
- mocked AbuseIPDB responses;
- database integration tests for history persistence;
- tests for timeout and upstream error handling.

Tests must not make live AbuseIPDB calls by default.

Use fixtures for representative AbuseIPDB responses.

When fixing a bug, add a regression test that fails before the fix and passes after it.

## Verification

Run all applicable checks before considering a task complete.

Preferred commands:

ruff check .
ruff format --check .
pytest

If configured:

mypy services

For History Service:

alembic upgrade head
alembic check

Never claim tests passed unless they were executed.

## Workflow for implementation tasks

Before editing:
- Read this file.
- Read the relevant service code.
- Read the related documentation and tests.
- Summarize the intended change.
- Identify affected service boundaries.

For a non-trivial task:
- Propose a short implementation plan.
- Implement the smallest coherent change.
- Add or update tests.
- Run relevant checks.
- Review the diff for unrelated changes.
- Update documentation where required.

Ask before changing:
- architecture
- public APIs
- database engine
- service boundaries
- security model
- infrastructure