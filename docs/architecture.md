# Architecture

## Goal

Build a small application with three independently runnable services and a relational database.

The priority is:
1. understandable behavior;
2. clear service boundaries;
3. correct application behavior;
4. reliable testing;
5. future extensibility.

The application uses one application-facing service, one external-provider proxy, and one presentation service.

## Components

### UI Service
Responsibilities:
- render the web interface;
- accept an IP address from the user;
- request reputation checks from History Service;
- request lookup history from History Service;
- request locally persisted blacklist status and entries from History Service;
- display current results, history, blacklist data, and user-facing errors;
- proxy the minimal browser blacklist-status poll to History Service.

Restrictions:
- no direct Provider Service access;
- no direct AbuseIPDB access;
- no database access;
- no API keys or database credentials;
- no persistence logic.

*The UI communicates only with History Service.*

### History Service
History Service acts as the application provider and persistence owner.

Responsibilities:
- expose the application-facing API used by UI Service;
- validate and normalize IPv4 and IPv6 addresses;
- reject non-public addresses;
- orchestrate reputation lookups;
- call Provider Service for normalized AbuseIPDB data;
- validate Provider Service responses;
- persist successful lookup results;
- return current results and history;
- implement request idempotency;
- manage database schema changes through Alembic.

Additional responsibilities:

- periodically synchronize AbuseIPDB blacklist data;
- preserve complete historical snapshots;
- record synchronization attempts and failures;
- use provider rate-limit metadata when determining the next attempt;
- expose locally persisted blacklist data to UI;
- retain the latest successful snapshot after an update failure.

The initial implementation retains every accepted complete snapshot and has no
automatic pruning policy. Each snapshot contains no more than 1000 entries.

Restrictions:
- no direct AbuseIPDB access;
- no AbuseIPDB API key;
- no arbitrary upstream URLs from user input;
- no provider-specific HTTP implementation outside the Provider Service client.

*History Service is the only service allowed to access MariaDB.*

### Provider Service
Provider Service acts as an internal AbuseIPDB proxy and provider adapter.

Responsibilities:
- expose an internal reputation lookup API;
- receive normalized lookup requests from History Service;
- call AbuseIPDB;
- validate the upstream response;
- normalize provider-specific data into the internal service contract;
- map provider failures into stable internal API errors;
- use explicit HTTP timeouts;
- preserve request ID propagation.

Additional responsibilities:

- call the AbuseIPDB blacklist endpoint;
- validate every returned blacklist entry;
- normalize IPv4 and IPv6 addresses;
- extract rate-limit response headers;
- return normalized snapshot metadata and entries.

Provider Service does not decide when synchronization should occur.

Restrictions:
- no public application history API;
- no direct UI access;
- no MariaDB access;
- no persistence logic;
- no idempotency logic;
- no calls to History Service;
- no arbitrary upstream URLs from request input.

*Only Provider Service stores and uses the AbuseIPDB API key.*

History Service exposes no internal persistence endpoints. Provider Service has
no route or client for writing to History Service.

---

## Blacklist synchronization flow

```text
1. History Service determines that synchronization is due.
2. History Service creates a synchronization run.
3. History Service requests GET /internal/v1/blacklist from Provider Service.
4. Provider Service requests GET /api/v2/blacklist from AbuseIPDB.
5. Provider Service validates and normalizes the response.
6. Provider Service returns snapshot data and rate-limit metadata.
7. History Service checks whether the snapshot is new.
8. History Service stores the snapshot and every entry in one transaction.
9. History Service records the successful synchronization run.
10. UI later reads the latest persisted snapshot from History Service.
```

```text
History Service scheduler
       |
       v
Provider Service
       |
       v
AbuseIPDB
       |
       v
Provider Service
       |
       v
History Service
       |
       v
MariaDB
```

## UI refresh flow

The browser periodically asks UI Service whether the latest snapshot changed.

UI Service reads snapshot state from History Service.

```text
Browser polling
  -> UI Service
  -> History Service
  -> MariaDB
```

Browser polling must not trigger a Provider Service or AbuseIPDB request.

If the snapshot identifier has not changed, UI should not reload the complete
table.

If synchronization fails, UI continues displaying the latest successful
snapshot and shows a stale-data or synchronization warning where appropriate.

The in-process scheduler is controlled by `BLACKLIST_SCHEDULER_ENABLED` and is
disabled by default. Its default interval is 21600 seconds (six hours). Exactly
one History Service worker may enable it; additional Uvicorn workers must run
with the scheduler disabled. The scheduler reads persisted `next_attempt_at`
state and does not bypass a future rate-limit reset.



---

## Service boundaries

### Application-facing boundary

History Service owns the application API:

* `POST /api/v1/checks`
* `GET  /api/v1/checks`
* `GET  /api/v1/checks/{history_id}`
* `GET  /api/v1/blacklist/status`
* `GET  /api/v1/blacklist`
* `GET  /api/v1/blacklist/snapshots`
* `GET  /api/v1/blacklist/snapshots/{snapshot_id}`

UI Service communicates only with this API.

### Provider boundary

Provider Service owns the internal provider API:

* `POST /internal/v1/reputation-checks`
* `GET /internal/v1/blacklist`

Only History Service may call these endpoints.
*The provider contract must not expose unnecessary raw AbuseIPDB response data.*

---

## Failure behavior

* **Invalid request schema**: reject in History Service; do not call Provider Service; do not create history.
* **Invalid or non-public IP**: reject in History Service before calling Provider Service; do not create history.
* **Provider Service unavailable**: History Service returns a dependency-unavailable error; do not create history.
* **AbuseIPDB timeout**: Provider Service returns an internal timeout error; History Service maps it to an application error; do not create history.
* **AbuseIPDB authentication failure**: Provider Service returns a stable internal authentication error; do not create history.
* **Invalid AbuseIPDB response**: Provider Service returns an invalid-upstream-response error; do not create history.
* **Invalid Provider Service response**: History Service treats it as an invalid dependency response; do not create history.
* **Database unavailable**: History Service returns a service-unavailable error; do not report the operation as successfully stored.
* **Persistence failure after a successful provider lookup**: return a persistence-related service error; do not report a successful application result.
* **Duplicate request ID with equivalent payload**: return the existing persisted result; do not call Provider Service again where the existing result can be resolved safely; do not create a second row.
* **Duplicate request ID with different payload**: return `409 IDEMPOTENCY_CONFLICT`.

---

## Data ownership

**UI Service owns:**

* HTML templates;
* presentation models;
* form state;
* user-facing error presentation.

**History Service owns:**

* the application-facing reputation result model;
* application request validation;
* lookup orchestration;
* idempotency rules;
* persistence model;
* history queries;
* database migrations;
* complete blacklist snapshots and entries;
* blacklist synchronization runs and next-attempt metadata.

**Provider Service owns:**

* AbuseIPDB credentials;
* AbuseIPDB request construction;
* AbuseIPDB response models;
* provider-specific normalization;
* provider-specific failure mapping.

**MariaDB owns:**

* persisted lookup records;
* persisted blacklist snapshots, entries, and synchronization runs;
* Alembic version state.

The original manual-check table remains supported by the manual-check API and
is not read or written by blacklist synchronization.

*Note: AbuseIPDB responses are treated as untrusted external data. Provider Service must validate them before returning an internal response. History Service must validate Provider Service responses before persistence.*

---

## Configuration ownership

### UI Service

* **May receive:** `HISTORY_SERVICE_URL`, `HISTORY_TIMEOUT_SECONDS`
- **Must not receive:** `PROVIDER_SERVICE_URL`, `ABUSEIPDB_API_KEY`, `DATABASE_URL`, `MARIADB_PASSWORD`

### History Service

- **May receive:** `PROVIDER_SERVICE_URL`, `PROVIDER_TIMEOUT_SECONDS`,
  `MARIADB_HOST`, `MARIADB_PORT`, `MARIADB_DATABASE`, `MARIADB_USER`,
  `MARIADB_PASSWORD`, and the `BLACKLIST_*` scheduler settings documented in
  `services/history-service/.env.example`
* **Must not receive:** `ABUSEIPDB_API_KEY`

### Provider Service

* **May receive:** `ABUSEIPDB_BASE_URL`, `ABUSEIPDB_API_KEY`, HTTP timeout settings
* **Must not receive:** `HISTORY_SERVICE_URL`, `DATABASE_URL`, `MARIADB_PASSWORD`

---

## Security rules

* Secrets come from environment variables.
* API keys and passwords are never logged.
* User input cannot control the AbuseIPDB host.
* External requests use explicit timeouts.
* Service-to-service responses are validated.
* Public errors do not expose stack traces, credentials, SQL, raw upstream responses, or internal URLs.
* UI does not receive provider credentials.
* Provider Service does not receive database credentials.
* Tests do not call the live AbuseIPDB API by default.

---

## Observability

Each request should use a UUID request ID propagated through:
`X-Request-ID: <uuid>`

The propagation path is:
`UI Service -> History Service -> Provider Service`

Services write logs to stdout and include:

* timestamp;
* service name;
* event name;
* request ID;
* status;
* duration;
* dependency name where relevant.

* **History Service** should log database and Provider Service dependency events without logging credentials or complete request bodies unnecessarily.
* **Provider Service** should identify AbuseIPDB as the upstream dependency without logging API keys or authorization headers.

---

## Health checks

Each service exposes:

* `GET /health/live`
* `GET /health/ready`

**UI Service**

* **live:** confirms the process can serve requests.
* **ready:** calls History Service readiness and reports not-ready when History
  Service or MariaDB is unavailable. It does not perform a provider lookup.

**History Service**

* **live:** confirms the process can serve requests.
* **ready:** confirms MariaDB availability with a minimal database query. It
  does not call Provider Service or AbuseIPDB.

**Provider Service**

* **live:** confirms the process can serve requests.
* **ready:** confirms local initialization and required configuration. (It must not consume AbuseIPDB quota during readiness checks).

---

## Deployment topology

For a single Ubuntu test server, the intended topology is:

```text
UI Service       0.0.0.0:8000
History Service  127.0.0.1:8002
Provider Service  127.0.0.1:8001
MariaDB          127.0.0.1:3306

```

Only UI Service should be reachable externally.

The internal request direction is:

```text
UI :8000
  -> History :8002
  -> Provider :8001
  -> AbuseIPDB

```

History Service separately accesses MariaDB on port `3306`.

The initial UI is tabular. Charts and analytical dashboards are outside the
current scope.
