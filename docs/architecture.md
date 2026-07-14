# Architecture

## Goal

Build a small application with three independently runnable services and a relational database. The priority is understandable behavior, clear service boundaries, and future extensibility.

## Components

### UI Service

Responsibilities:

- render the web interface;
- accept an IP address;
- request current data from Backend;
- display current results and history.

Restrictions:

- no AbuseIPDB access;
- no History Service access;
- no database access;
- no API keys or database credentials.

### Backend Service

Responsibilities:

- expose the public application API;
- validate and normalize IPv4 and IPv6 addresses;
- reject non-public addresses;
- call AbuseIPDB;
- validate and normalize the upstream response;
- save successful results through History Service;
- return current data and history to UI.

Restrictions:

- no direct MariaDB access;
- no arbitrary upstream URLs from user input.

### History Service

Responsibilities:

- own the persistence model;
- save successful checks;
- return paginated and filtered history;
- manage schema changes through Alembic.

Restriction:

- it is the only service allowed to access MariaDB.

## Request flow

```text
1. User submits an IP address.
2. UI sends POST /api/v1/checks to Backend.
3. Backend validates the address.
4. Backend calls AbuseIPDB.
5. Backend normalizes the response.
6. Backend sends POST /internal/v1/checks to History.
7. History stores the record in MariaDB.
8. Backend returns the result to UI.
```

History is read through Backend:

```text
UI -> Backend -> History Service -> MariaDB
```

## Failure behavior

- Invalid or non-public IP: reject before calling AbuseIPDB.
- AbuseIPDB timeout or failure: do not create history.
- Invalid AbuseIPDB response: return an upstream error.
- History unavailable after a successful lookup: return a service error; do not report the operation as fully successful.
- Duplicate `request_id`: History returns the existing record or an idempotent success.

## Data ownership

- Backend owns the normalized reputation model used by the application.
- History owns the database model and migrations.
- AbuseIPDB responses are treated as untrusted external data.
- UI owns presentation only.

## Security rules

- Secrets come from environment variables.
- API keys and passwords are never logged.
- User input cannot control the upstream host.
- External requests use explicit timeouts.
- Public errors do not expose stack traces, credentials, SQL, or internal URLs.
- Tests do not call the live AbuseIPDB API by default.

## Observability

Each request should use a UUID request ID propagated through:

```http
X-Request-ID: <uuid>
```

Services write logs to stdout and include:

- timestamp;
- service;
- event;
- request ID;
- status;
- duration;
- dependency name where relevant.

## Future evolution

The architecture should allow later addition of:

- containers;
- CI/CD;
- orchestration;
- metrics and tracing;
- caching;
- asynchronous persistence;
- cloud deployment.

These are intentionally excluded from the first version.
