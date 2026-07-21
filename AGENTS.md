1. Project Overview

Educational multi-service IP reputation app. Checks public IPv4/v6 via AbuseIPDB, stores in MariaDB.
Priorities: Strict boundaries, clear code, reliable tests, minimal infrastructure.

2. Architecture & API Boundaries

Three isolated services. The UI must not know which reputation provider is used.

Lookup Flow: UI ➔ History (Main Backend) ➔ Backend (API Proxy) ➔ AbuseIPDB ➔ (return) ➔ History ➔ MariaDB ➔ UI.
History Flow: UI ➔ History ➔ MariaDB.

    ui-service:

        Renders UI via FastAPI/Jinja2.

        Communicates only with history-service.

    history-service (Main Backend) | Public API: /api/v1/*:

        The core application backend. Orchestrates lookups, validates/normalizes IPs.

        The only service allowed to access MariaDB.

        Calls the proxy (backend-service) for external data.

    backend-service (API Proxy) | Internal API: /internal/v1/*:

        Internal adapter exclusively for AbuseIPDB.

        Normalizes upstream requests/responses and maps errors.

        Strict NO's: No UI communication, no MariaDB access, no history persistence.

3. Responsibility Boundaries

    history-service (Main Backend): Core logic, IP/request validation, idempotency, MariaDB persistence & migrations, app-level errors.

    backend-service (API Proxy): AbuseIPDB integration (credentials, HTTPX calls, timeouts), provider data normalization, error mapping. (Must not touch DB).

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

    Proxy (backend-service) strict rules: HTTPX with timeouts. Validate upstream JSON via Pydantic. Return normalized data (never raw). Do not persist, implement idempotency, or log API keys.

7. Orchestration & Persistence (history-service)

    Lookup Flow: Validate IP/Request ➔ Check Idempotency ➔ Call Proxy ➔ Persist Success ➔ Return.

        Note: Do not persist failed lookups. Fail if DB save fails.

    Database: SQLAlchemy 2.x + Alembic (No create_all()). One session per request. Searchable fields must be relational columns, not raw JSON.

    Idempotency: Based on request_id. Reused ID + same payload = return existing. Reused ID + different payload = 409 IDEMPOTENCY_CONFLICT.


8. Config & Secrets

    Environment Variables: Use env vars for config. Provide safe examples. Never commit secrets.

    Separation: Proxy gets AbuseIPDB keys; History gets DB creds; UI gets History URL.

    Security: Use SecretStr. Do NOT leak credentials in logs, Alembic configs, or error messages.

9. Errors, Tracing & Logs

    Errors: history-service returns safe JSON errors (code, message, request_id). Proxy maps upstream issues to HTTP statuses (400, 429, 502, etc.). Never leak internal traces/DB details.

    Request IDs (request_id): Required for all requests. Must be passed across all 3 services for tracing and idempotency.

    Logging: Structured logs to stdout. Include request_id, duration, status. No secrets or raw payloads.

10. Health, Tests & Workflow

    Health: /health/live & /health/ready. Readiness checks must not consume AbuseIPDB API quotas.

    Tests: Mandatory for all changes (Unit, Endpoint, DB, Contract). Default tests must mock AbuseIPDB. Always add regression tests for bug fixes.

    Verification Pipeline: Run ruff check/format ., pytest, mypy services, alembic check before completing tasks.

    Workflow: Iterate in small steps. Avoid full rewrites. Ask for approval before changing architecture, DB engine, or security models.


11. Legacy Refactoring & Agent Workflow

    Legacy Context: The repo is migrating away from an old flow (UI ➔ Backend ➔ History). Do not preserve obsolete calls. Remove them. Backend must no longer orchestrate persistence, and UI must not call Backend directly.

    Agent Task Workflow:

        Analyze: Read this file, inspect relevant code, tests, and contracts.

        Plan: Propose a short implementation plan before editing.

        Implement: Make the smallest coherent change. Do not do a single massive rewrite of all services.

        Test & Verify: Add/update tests. Run checks (pytest, ruff, etc.). Review diffs for unrelated changes.

