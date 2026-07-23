1. Project Overview

Educational multi-service IP reputation app. Checks public IPv4/v6 via AbuseIPDB, stores in MariaDB.
Priorities: Strict boundaries, clear code, reliable tests, minimal infrastructure.

## 2. Architecture & API Boundaries

The application consists of three independently runnable services.

The UI must not know which external reputation provider is used.

Manual lookup flow:

UI
  -> History Service
  -> Provider Service
  -> AbuseIPDB
  -> Provider Service
  -> History Service
  -> MariaDB
  -> UI

Blacklist synchronization flow:

Provider Service worker
  -> AbuseIPDB Blacklist API
  -> Provider local durable outbox
  -> History Service
  -> MariaDB

Blacklist display flow:

Browser
  -> UI Service
  -> History Service
  -> MariaDB

### ui-service

- Renders the web interface using FastAPI and Jinja2.
- Communicates only with history-service.
- Displays the latest persisted blacklist snapshot.
- May poll History Service for a newer snapshot.
- Must not call Provider Service or AbuseIPDB directly.
- Must not access MariaDB.

### history-service

History Service is the application backend and persistence owner.

Public API: `/api/v1/*`

Responsibilities:

- application-facing API;
- manual lookup orchestration;
- public-IP validation and normalization;
- request idempotency;
- MariaDB persistence and Alembic migrations;
- authenticated blacklist snapshot ingestion;
- complete blacklist snapshot persistence;
- blacklist query APIs used by UI.

History Service is the only service allowed to access MariaDB.

### provider-service

Provider Service is an internal AbuseIPDB adapter.

Internal API: `/internal/v1/*`

Responsibilities:

- AbuseIPDB authentication;
- individual reputation lookup requests;
- blacklist requests;
- upstream response validation;
- provider-specific normalization;
- rate-limit metadata extraction;
- provider error mapping.

Strict restrictions:

- no UI communication;
- no MariaDB access;
- no MariaDB persistence;
- no calls to History Service except authenticated snapshot delivery;
- no application idempotency.

3. Responsibility Boundaries

    history-service (Main Backend): Core logic, IP/request validation, idempotency, MariaDB persistence & migrations, app-level errors.

    provider-service (API Proxy): AbuseIPDB integration (credentials, HTTPX calls, timeouts), provider data normalization, error mapping. (Must not touch DB).

    ui-service: HTML/Jinja2 rendering, form handling, UI error presentation.

4. Tech Stack & Repository Rules

    Stack: FastAPI, HTTPX, Pydantic v2, SQLAlchemy 2.x, Alembic, MariaDB, pytest, Ruff, mypy/Pyright. (Jinja2 for UI).

    Restrictions: Use standard pip/venv. Do not add external tools (Poetry, uv, Redis, Kafka, React) without explicit approval.

    Strict Independence: Each service must be independently runnable with its own dependencies, config, and tests.

    No Shared Packages: Do not create a shared Python package for models. Duplicate boundary/Pydantic models between services to ensure independent validation.

5. Coding Conventions

    Thin Handlers: Move business & DB logic out of route handlers. Use APIRouter & Dependency Injection.

    Models: Explicit Pydantic models for I/O. Never return ORM models directly.

    Async/Sync Rules: Run synchronous SQLAlchemy operations in def (sync) handlers or worker threads, NOT in async def handlers.

6. IP Validation & Proxy Rules

    IP Validation: Use Python's ipaddress module (no regex!). Accept global IPv4/IPv6, reject local/private/multicast. Normalize to compressed format. Both services validate inputs.

    Proxy (provider-service) strict rules: HTTPX with timeouts. Validate upstream JSON via Pydantic. Return normalized data (never raw). Do not persist, implement idempotency, or log API keys.

7. Orchestration & Persistence (history-service)

    Lookup Flow: Validate IP/Request ➔ Check Idempotency ➔ Call Proxy ➔ Persist Success ➔ Return.

        Note: Do not persist failed lookups. Fail if DB save fails.

    Database: SQLAlchemy 2.x + Alembic (No create_all()). One session per request. Searchable fields must be relational columns, not raw JSON.

    Idempotency: Based on request_id. Reused ID + same payload = return existing. Reused ID + different payload = 409 IDEMPOTENCY_CONFLICT.


8. Config & Secrets

    Environment Variables: Use env vars for config. Provide safe examples. Never commit secrets.

    Separation: Proxy gets AbuseIPDB keys; History gets DB creds; UI gets History URL.

    Security: Use SecretStr. Do NOT leak credentials in logs, Alembic configs, or error messages.

## 9. Blacklist synchronization

The AbuseIPDB blacklist is treated as a point-in-time provider snapshot.

Provider Service periodically fetches normalized blacklist snapshots, stores
pending delivery durably in a local SQLite outbox, and sends them to History.
History validates and persists accepted snapshots in MariaDB.

### Default synchronization configuration

- maximum entries: 1000;
- minimum confidence score: 90;
- base synchronization interval: 21600 seconds (six hours);
- UI status polling interval: 30 seconds.

The confidence threshold, Provider worker enablement, base interval, stale threshold,
temporary-attempt bound, and jitter bound are configurable. The initial
complete-snapshot limit is fixed at no more than 1000 entries.

### Polling ownership

The standalone Provider worker is the only periodic polling owner. It is
independent of API worker count, protected by a singleton lock, and disabled by
default with `BLACKLIST_POLLING_ENABLED=false`.

### Synchronization behavior

A synchronization attempt must:

1. have the Provider worker request and normalize an AbuseIPDB snapshot;
2. commit the normalized payload and stable delivery ID to the local outbox;
3. deliver it to History's authenticated ingestion endpoint;
4. have History validate and idempotently accept the delivery;
5. persist the snapshot, entries, and summary metrics transactionally;
6. acknowledge the delivery so Provider can remove it from the outbox.

A failed synchronization must not replace or delete the latest successful
snapshot.

The latest successful snapshot remains available to UI when synchronization
temporarily fails.

### Rate-limit behavior

Provider Service must extract and return, where available:

- `X-RateLimit-Limit`;
- `X-RateLimit-Remaining`;
- `X-RateLimit-Reset`;
- `Retry-After`.

Provider Service owns polling and delivery retry decisions.

Rules:

- use the configured interval after a successful request;
- when remaining quota is zero, wait until the reported reset time;
- after HTTP 429, honor `Retry-After` or the rate-limit reset time;
- use the bounded 5, 15, 30, and 60 minute progression for temporary
  connection, timeout, and 5xx failures;
- do not retry continuously;
- do not delete valid local data after a failed update;
- add a small random delay where practical to avoid repeated synchronized
  retries.

A retry must not bypass a known rate-limit reset time.

### Snapshot persistence

Every accepted snapshot stores:

- provider generation time;
- local fetch time;
- request parameters;
- all normalized blacklist entries;
- entry count;
- rate-limit metadata where available.

A snapshot is uniquely identified by provider and provider generation time
where the provider supplies reliable generation metadata.

Snapshot entries must be unique by snapshot and normalized IP address.

The existing manual lookup table remains in the database as a legacy table.
The blacklist synchronization flow must not write to it.

Accepted complete snapshots are retained historically. The initial
implementation has no automatic snapshot-retention or pruning job.

Blacklist analytics are computed by History from persisted MariaDB snapshots.
UI may render those results but must not aggregate complete histories in the
browser or contact Provider to produce charts.

10. Errors, Tracing & Logs

    Errors: history-service returns safe JSON errors (code, message, request_id). Proxy maps upstream issues to HTTP statuses (400, 429, 502, etc.). Never leak internal traces/DB details.

    Request IDs (request_id): Required for all requests. Must be passed across all 3 services for tracing and idempotency.

    Logging: Structured logs to stdout. Include request_id, duration, status. No secrets or raw payloads.

11. Health, Tests & Workflow

    Health: /health/live & /health/ready. Readiness checks must not consume AbuseIPDB API quotas.

    Tests: Mandatory for all changes (Unit, Endpoint, DB, Contract). Default tests must mock AbuseIPDB. Always add regression tests for bug fixes.

    Verification Pipeline: Run ruff check/format ., pytest, mypy services, alembic check before completing tasks.

    Workflow: Iterate in small steps. Avoid full rewrites. Ask for approval before changing architecture, DB engine, or security models.

    Blacklist synchronization tests must cover:

- successful initial synchronization;
- complete snapshot persistence;
- duplicate snapshot handling;
- IPv4 and IPv6 entries;
- malformed provider data;
- Provider Service timeout;
- HTTP 429 with Retry-After;
- zero remaining quota;
- bounded retry behavior;
- database rollback;
- worker shutdown while polling or delivery is waiting;
- Provider polling disabled in ordinary tests;
- durable outbox recovery after worker restart;
- UI retaining the last successful snapshot after a synchronization failure.


12. Agent Workflow

    Boundary Enforcement: Manual lookup is UI ➔ History ➔ Provider ➔ AbuseIPDB. Periodic synchronization is Provider ➔ AbuseIPDB ➔ Provider outbox ➔ History ➔ MariaDB. Analytics is UI ➔ History ➔ MariaDB. Provider may call only AbuseIPDB and History, and must never access UI or MariaDB.

    Agent Task Workflow:

        Analyze: Read this file, inspect relevant code, tests, and contracts.

        Plan: Propose a short implementation plan before editing.

        Implement: Make the smallest coherent change. Do not do a single massive rewrite of all services.

        Test & Verify: Add/update tests. Run checks (pytest, ruff, etc.). Review diffs for unrelated changes.
