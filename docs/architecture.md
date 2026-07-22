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
- display current results, history, and user-facing errors.

Restrictions:
- no direct Backend Service access;
- no direct AbuseIPDB access;
- no database access;
- no API keys or database credentials;
- no persistence logic.

*The UI communicates only with History Service.*

### History Service
History Service acts as the application backend and persistence owner.

Responsibilities:
- expose the application-facing API used by UI Service;
- validate and normalize IPv4 and IPv6 addresses;
- reject non-public addresses;
- orchestrate reputation lookups;
- call Backend Service for normalized AbuseIPDB data;
- validate Backend Service responses;
- persist successful lookup results;
- return current results and history;
- implement request idempotency;
- manage database schema changes through Alembic.

Restrictions:
- no direct AbuseIPDB access;
- no AbuseIPDB API key;
- no arbitrary upstream URLs from user input;
- no provider-specific HTTP implementation outside the Backend Service client.

*History Service is the only service allowed to access MariaDB.*

### Backend Service
Backend Service acts as an internal AbuseIPDB proxy and provider adapter.

Responsibilities:
- expose an internal reputation lookup API;
- receive normalized lookup requests from History Service;
- call AbuseIPDB;
- validate the upstream response;
- normalize provider-specific data into the internal service contract;
- map provider failures into stable internal API errors;
- use explicit HTTP timeouts;
- preserve request ID propagation.

Restrictions:
- no public application history API;
- no direct UI access;
- no MariaDB access;
- no persistence logic;
- no idempotency logic;
- no calls to History Service;
- no arbitrary upstream URLs from request input.

*Only Backend Service stores and uses the AbuseIPDB API key.*

History Service exposes no internal persistence endpoints. Backend Service has
no route or client for writing to History Service.

---

## Request flow

### Create a reputation check

```text
1. User submits an IP address.
2. UI sends POST /api/v1/checks to History Service.
3. History Service validates and normalizes the address.
4. History Service resolves the request ID and checks idempotency.
5. History Service sends POST /internal/v1/reputation-checks to Backend Service.
6. Backend Service calls AbuseIPDB.
7. Backend Service validates and normalizes the upstream response.
8. Backend Service returns the normalized provider result to History Service.
9. History Service persists the successful result in MariaDB.
10. History Service returns the persisted application result to UI.

```

**Diagram:**

```text
User
  |
  v
UI Service
  |
  v
History Service
  | \
  |  \-> MariaDB
  |
  v
Backend Service
  |
  v
AbuseIPDB

```

**The response path is:**

```text
AbuseIPDB
  -> Backend Service
  -> History Service
  -> UI Service
  -> User

```

### Read history

```text
User
  -> UI Service
  -> History Service
  -> MariaDB

```

---

## Service boundaries

### Application-facing boundary

History Service owns the application API:

* `POST /api/v1/checks`
* `GET  /api/v1/checks`
* `GET  /api/v1/checks/{history_id}`

UI Service communicates only with this API.

### Provider boundary

Backend Service owns the internal provider API:

* `POST /internal/v1/reputation-checks`

Only History Service may call this endpoint.
*The provider contract must not expose unnecessary raw AbuseIPDB response data.*

---

## Failure behavior

* **Invalid request schema**: reject in History Service; do not call Backend Service; do not create history.
* **Invalid or non-public IP**: reject in History Service before calling Backend Service; do not create history.
* **Backend Service unavailable**: History Service returns a dependency-unavailable error; do not create history.
* **AbuseIPDB timeout**: Backend Service returns an internal timeout error; History Service maps it to an application error; do not create history.
* **AbuseIPDB authentication failure**: Backend Service returns a stable internal authentication error; do not create history.
* **Invalid AbuseIPDB response**: Backend Service returns an invalid-upstream-response error; do not create history.
* **Invalid Backend Service response**: History Service treats it as an invalid dependency response; do not create history.
* **Database unavailable**: History Service returns a service-unavailable error; do not report the operation as successfully stored.
* **Persistence failure after a successful provider lookup**: return a persistence-related service error; do not report a successful application result.
* **Duplicate request ID with equivalent payload**: return the existing persisted result; do not call Backend Service again where the existing result can be resolved safely; do not create a second row.
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
* database migrations.

**Backend Service owns:**

* AbuseIPDB credentials;
* AbuseIPDB request construction;
* AbuseIPDB response models;
* provider-specific normalization;
* provider-specific failure mapping.

**MariaDB owns:**

* persisted lookup records;
* Alembic version state.

*Note: AbuseIPDB responses are treated as untrusted external data. Backend Service must validate them before returning an internal response. History Service must validate Backend Service responses before persistence.*

---

## Configuration ownership

### UI Service

* **May receive:** `HISTORY_SERVICE_URL`
* **Must not receive:** `BACKEND_SERVICE_URL`, `ABUSEIPDB_API_KEY`, `DATABASE_URL`, `MARIADB_PASSWORD`

### History Service

* **May receive:** `BACKEND_SERVICE_URL`, `DATABASE_URL`, `MARIADB_HOST`, `MARIADB_PORT`, `MARIADB_DATABASE`, `MARIADB_USER`, `MARIADB_PASSWORD`
* **Must not receive:** `ABUSEIPDB_API_KEY`

### Backend Service

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
* Backend Service does not receive database credentials.
* Tests do not call the live AbuseIPDB API by default.

---

## Observability

Each request should use a UUID request ID propagated through:
`X-Request-ID: <uuid>`

The propagation path is:
`UI Service -> History Service -> Backend Service`

Services write logs to stdout and include:

* timestamp;
* service name;
* event name;
* request ID;
* status;
* duration;
* dependency name where relevant.

* **History Service** should log database and Backend Service dependency events without logging credentials or complete request bodies unnecessarily.
* **Backend Service** should identify AbuseIPDB as the upstream dependency without logging API keys or authorization headers.

---

## Health checks

Each service exposes:

* `GET /health/live`
* `GET /health/ready`

**UI Service**

* **live:** confirms the process can serve requests.
* **ready:** confirms local initialization and configuration. (It should not make an expensive downstream lookup).

**History Service**

* **live:** confirms the process can serve requests.
* **ready:** confirms local initialization and MariaDB availability. (Readiness may also verify that Backend Service configuration is valid, but must not perform a real AbuseIPDB lookup).

**Backend Service**

* **live:** confirms the process can serve requests.
* **ready:** confirms local initialization and required configuration. (It must not consume AbuseIPDB quota during readiness checks).

---

## Deployment topology

For a single Ubuntu test server, the intended topology is:

```text
UI Service       0.0.0.0:8000
History Service  127.0.0.1:8002
Backend Service  127.0.0.1:8001
MariaDB          127.0.0.1:3306

```

Only UI Service should be reachable externally.

The internal request direction is:

```text
UI :8000
  -> History :8002
  -> Backend :8001
  -> AbuseIPDB

```

History Service separately accesses MariaDB on port `3306`.
