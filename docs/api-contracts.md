# API Contracts

All timestamps use UTC ISO 8601.

JSON is encoded as UTF-8.

Unknown fields in internal service contracts should be rejected unless a
specific compatibility rule says otherwise.

---

## Service boundaries

The application consists of three independently runnable services:

- `ui-service` exposes the browser-facing interface;
- `history-service` exposes the public application API, owns MariaDB, performs
  application orchestration, and runs scheduled blacklist synchronization;
- `provider-service` exposes internal provider endpoints and acts as the
  stateless AbuseIPDB adapter.

The allowed request paths are:

```text
Browser
  -> UI Service
  -> History Service
  -> Provider Service
  -> AbuseIPDB
```

and:

```text
History Service scheduler
  -> Provider Service
  -> AbuseIPDB Blacklist API
  -> History Service
  -> MariaDB
```

UI Service must not call Provider Service directly.

Provider Service must not access MariaDB, persist results, run the scheduler, or
call History Service.

Browser polling and blacklist-read endpoints must use locally persisted data
only. They must not trigger an AbuseIPDB request.

---

# Application API

The Application API is exposed by `history-service` and consumed by
`ui-service`.

`provider-service` must not expose these application endpoints.

## Manual reputation checks

### Create IP check

```http
POST /api/v1/checks
Content-Type: application/json
X-Request-ID: <optional UUID>
```

Request:

```json
{
  "ip_address": "8.8.8.8",
  "max_age_days": 90
}
```

Rules:

- `ip_address` must be a valid public IPv4 or IPv6 address;
- loopback, private, multicast, link-local, unspecified, and otherwise
  non-globally-routable addresses are rejected;
- `max_age_days` must be between 1 and 365;
- default `max_age_days` is 30;
- the address is normalized before the provider request;
- History Service owns validation and idempotency;
- Provider Service is called only after application validation succeeds.

Created response:

```http
HTTP/1.1 201 Created
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd
```

```json
{
  "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
  "history_id": 145,
  "ip_address": "8.8.8.8",
  "ip_version": 4,
  "is_public": true,
  "is_whitelisted": null,
  "abuse_confidence_score": 0,
  "country_code": "US",
  "usage_type": "Data Center/Web Hosting/Transit",
  "isp": "Google LLC",
  "domain": "google.com",
  "total_reports": 0,
  "num_distinct_users": 0,
  "last_reported_at": null,
  "max_age_days": 90,
  "source": "AbuseIPDB",
  "checked_at": "2026-07-15T18:30:00Z"
}
```

Idempotent response:

When the same request ID is reused with an equivalent application payload,
History Service returns the original persisted result:

```http
HTTP/1.1 200 OK
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd
```

No new provider lookup or database row should be created when the existing
result can be safely resolved from the idempotency record.

When the same request ID is reused with different relevant request data:

```http
HTTP/1.1 409 Conflict
```

```json
{
  "error": {
    "code": "IDEMPOTENCY_CONFLICT",
    "message": "The request ID has already been used with different request data.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}
```

### List manual-check history

```http
GET /api/v1/checks?limit=20&offset=0
GET /api/v1/checks?ip_address=8.8.8.8
```

Query rules:

- `limit` defaults to 20;
- `limit` must be between 1 and 100;
- `offset` defaults to 0;
- `offset` must be greater than or equal to 0;
- `ip_address`, when supplied, must be normalized before filtering;
- results are ordered by descending `history_id`.

Success:

```http
HTTP/1.1 200 OK
```

```json
{
  "items": [
    {
      "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
      "history_id": 145,
      "ip_address": "8.8.8.8",
      "ip_version": 4,
      "is_public": true,
      "is_whitelisted": null,
      "abuse_confidence_score": 0,
      "country_code": "US",
      "usage_type": "Data Center/Web Hosting/Transit",
      "isp": "Google LLC",
      "domain": "google.com",
      "total_reports": 0,
      "num_distinct_users": 0,
      "last_reported_at": null,
      "max_age_days": 90,
      "source": "AbuseIPDB",
      "checked_at": "2026-07-15T18:30:00Z"
    }
  ],
  "limit": 20,
  "offset": 0,
  "total": 1
}
```

### Get one manual-check record

```http
GET /api/v1/checks/{history_id}
```

Success:

```http
HTTP/1.1 200 OK
```

The response uses the same persisted record model returned by
`POST /api/v1/checks`.

Not found:

```http
HTTP/1.1 404 Not Found
```

```json
{
  "error": {
    "code": "HISTORY_RECORD_NOT_FOUND",
    "message": "The requested history record does not exist.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}
```

The existing manual-check persistence remains supported by these endpoints.
Blacklist synchronization does not write to the manual-check table.

---

## Blacklist resources

Blacklist resources are owned by History Service and are read from MariaDB.

These endpoints must not call Provider Service or AbuseIPDB.

### Get blacklist synchronization status

```http
GET /api/v1/blacklist/status
```

Success:

```http
HTTP/1.1 200 OK
```

```json
{
  "state": "ready",
  "sync_in_progress": false,
  "latest_snapshot_id": 42,
  "latest_provider_generated_at": "2026-07-22T12:00:00Z",
  "latest_fetched_at": "2026-07-22T12:00:02Z",
  "last_attempt_at": "2026-07-22T12:00:00Z",
  "last_success_at": "2026-07-22T12:00:04Z",
  "next_attempt_at": "2026-07-22T18:00:04Z",
  "rate_limit_limit": 5,
  "rate_limit_remaining": 4,
  "rate_limit_reset_at": "2026-07-23T00:00:00Z",
  "data_stale": false,
  "last_error": null
}
```

Possible `state` values:

- `empty` — no successful snapshot exists;
- `ready` — a successful snapshot is available;
- `syncing` — synchronization is currently running;
- `stale` — the latest successful snapshot is older than the configured
  freshness threshold;
- `degraded` — a snapshot is available, but the latest synchronization failed.

When the latest synchronization failed but a previous successful snapshot
exists, the response may include a safe application-level error summary:

```json
{
  "last_error": {
    "code": "UPSTREAM_TIMEOUT",
    "message": "The latest synchronization attempt failed."
  }
}
```

The status response must not expose stack traces, credentials, internal URLs,
SQL details, or raw provider bodies.

### Get latest blacklist snapshot

```http
GET /api/v1/blacklist?limit=100&offset=0
GET /api/v1/blacklist?ip_version=4&minimum_score=95
GET /api/v1/blacklist?country_code=US
```

Query rules:

- `limit` defaults to 100;
- `limit` must be between 1 and 100;
- `offset` defaults to 0;
- `offset` must be greater than or equal to 0;
- `ip_version`, when supplied, must be `4` or `6`;
- `minimum_score`, when supplied, must be between 0 and 100;
- `country_code`, when supplied, must be a two-letter uppercase country code;
- results are ordered by descending `abuse_confidence_score`, then descending
  `last_reported_at`, then ascending `ip_address`;
- the endpoint returns entries from the latest successful snapshot only.

Success:

```http
HTTP/1.1 200 OK
```

```json
{
  "snapshot": {
    "snapshot_id": 42,
    "provider": "AbuseIPDB",
    "provider_generated_at": "2026-07-22T12:00:00Z",
    "fetched_at": "2026-07-22T12:00:02Z",
    "confidence_minimum": 90,
    "requested_limit": 1000,
    "returned_count": 1000
  },
  "items": [
    {
      "ip_address": "203.0.113.25",
      "ip_version": 4,
      "abuse_confidence_score": 100,
      "country_code": "US",
      "last_reported_at": "2026-07-22T11:47:00Z"
    }
  ],
  "limit": 100,
  "offset": 0,
  "total": 1000
}
```

No successful snapshot:

```http
HTTP/1.1 404 Not Found
```

```json
{
  "error": {
    "code": "BLACKLIST_SNAPSHOT_NOT_FOUND",
    "message": "No successful blacklist snapshot is available.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}
```

### List stored blacklist snapshots

```http
GET /api/v1/blacklist/snapshots?limit=20&offset=0
```

Query rules:

- `limit` defaults to 20;
- `limit` must be between 1 and 100;
- `offset` defaults to 0;
- results are ordered by descending `snapshot_id`.

Success:

```http
HTTP/1.1 200 OK
```

```json
{
  "items": [
    {
      "snapshot_id": 42,
      "provider": "AbuseIPDB",
      "provider_generated_at": "2026-07-22T12:00:00Z",
      "fetched_at": "2026-07-22T12:00:02Z",
      "confidence_minimum": 90,
      "requested_limit": 1000,
      "returned_count": 1000
    }
  ],
  "limit": 20,
  "offset": 0,
  "total": 1
}
```

### Get one stored blacklist snapshot

```http
GET /api/v1/blacklist/snapshots/{snapshot_id}?limit=100&offset=0
```

Query rules:

- `limit` defaults to 100;
- `limit` must be between 1 and 100;
- `offset` defaults to 0;
- entries are ordered by descending `abuse_confidence_score`, then descending
  `last_reported_at`, then ascending `ip_address`.

Success:

```http
HTTP/1.1 200 OK
```

```json
{
  "snapshot": {
    "snapshot_id": 42,
    "provider": "AbuseIPDB",
    "provider_generated_at": "2026-07-22T12:00:00Z",
    "fetched_at": "2026-07-22T12:00:02Z",
    "confidence_minimum": 90,
    "requested_limit": 1000,
    "returned_count": 1000
  },
  "items": [
    {
      "ip_address": "203.0.113.25",
      "ip_version": 4,
      "abuse_confidence_score": 100,
      "country_code": "US",
      "last_reported_at": "2026-07-22T11:47:00Z"
    }
  ],
  "limit": 100,
  "offset": 0,
  "total": 1000
}
```

Not found:

```http
HTTP/1.1 404 Not Found
```

```json
{
  "error": {
    "code": "BLACKLIST_SNAPSHOT_NOT_FOUND",
    "message": "The requested blacklist snapshot does not exist.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}
```

---

# Internal Provider API

The Internal Provider API is exposed by `provider-service` and consumed only by
`history-service`.

UI Service must not call these endpoints.

Provider Service does not persist results, expose history resources, or run
scheduled synchronization.

## Create normalized provider reputation check

```http
POST /internal/v1/reputation-checks
Content-Type: application/json
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd
```

Request:

```json
{
  "ip_address": "8.8.8.8",
  "max_age_days": 90
}
```

Rules:

- the request is expected to contain a normalized IP address;
- `ip_address` must still conform to the internal schema;
- `max_age_days` must be between 1 and 365;
- Provider Service must not accept a user-supplied upstream URL;
- Provider Service must use its configured AbuseIPDB endpoint;
- Provider Service must validate the AbuseIPDB response;
- Provider Service must not access MariaDB;
- Provider Service must not implement persistence idempotency.

Success:

```http
HTTP/1.1 200 OK
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd
```

```json
{
  "ip_address": "8.8.8.8",
  "ip_version": 4,
  "is_public": true,
  "is_whitelisted": null,
  "abuse_confidence_score": 0,
  "country_code": "US",
  "usage_type": "Data Center/Web Hosting/Transit",
  "isp": "Google LLC",
  "domain": "google.com",
  "total_reports": 0,
  "num_distinct_users": 0,
  "last_reported_at": null,
  "max_age_days": 90,
  "source": "AbuseIPDB",
  "checked_at": "2026-07-15T18:30:00Z"
}
```

The internal response does not include:

- `history_id`;
- persistence status;
- database metadata;
- MariaDB identifiers;
- application idempotency information.

Those fields are owned by History Service.

## Retrieve normalized provider blacklist

```http
GET /internal/v1/blacklist?confidence_minimum=90&limit=1000
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd
```

Rules:

- `confidence_minimum` must be between 0 and 100;
- default `confidence_minimum` is 90;
- `limit` must be between 1 and 1000;
- default `limit` is 1000;
- Provider Service must use its configured AbuseIPDB endpoint;
- request input must not select or override the upstream host;
- every returned IP address must be validated and normalized;
- duplicate normalized IP addresses in one response must be rejected or handled
  according to a documented deterministic policy;
- Provider Service must validate provider metadata and every returned item;
- Provider Service must return no database identifiers;
- Provider Service must not store the response;
- Provider Service must extract supported rate-limit response headers;
- unknown AbuseIPDB fields may be ignored.

Success:

```http
HTTP/1.1 200 OK
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd
```

```json
{
  "provider": "AbuseIPDB",
  "generated_at": "2026-07-22T12:00:00Z",
  "fetched_at": "2026-07-22T12:00:02Z",
  "request": {
    "confidence_minimum": 90,
    "limit": 1000
  },
  "rate_limit": {
    "limit": 5,
    "remaining": 4,
    "reset_at": "2026-07-23T00:00:00Z",
    "retry_after_seconds": null
  },
  "items": [
    {
      "ip_address": "203.0.113.25",
      "ip_version": 4,
      "abuse_confidence_score": 100,
      "country_code": "US",
      "last_reported_at": "2026-07-22T11:47:00Z"
    }
  ]
}
```

Field rules:

- `generated_at` is the provider snapshot generation time;
- `fetched_at` is the local Provider Service completion time;
- `rate_limit` fields may be `null` when the corresponding header is absent;
- `items` contains no more than 1000 entries;
- `ip_address` uses canonical compressed representation;
- `ip_version` is derived from the normalized address;
- `abuse_confidence_score` must be between 0 and 100;
- `country_code` may be `null`;
- `last_reported_at` may be `null`.

---

## Internal Provider errors

Provider Service returns stable internal errors.

Example:

```json
{
  "error": {
    "code": "UPSTREAM_TIMEOUT",
    "message": "The reputation provider did not respond before the timeout.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}
```

Expected internal errors:

| Status | Code | Meaning |
|---:|---|---|
| 422 | `INVALID_REQUEST` | Internal request schema is invalid |
| 429 | `RATE_LIMIT_EXCEEDED` | AbuseIPDB quota or rate limit was reached |
| 502 | `UPSTREAM_INVALID_RESPONSE` | AbuseIPDB returned invalid JSON or data |
| 502 | `UPSTREAM_REQUEST_REJECTED` | AbuseIPDB rejected the request |
| 503 | `UPSTREAM_AUTHENTICATION_FAILED` | AbuseIPDB credentials were rejected |
| 503 | `UPSTREAM_UNAVAILABLE` | AbuseIPDB could not be reached |
| 504 | `UPSTREAM_TIMEOUT` | AbuseIPDB request timed out |

When available, a rate-limit error should include normalized retry metadata:

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "The provider rate limit has been reached.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd",
    "retry": {
      "retry_after_seconds": 3600,
      "reset_at": "2026-07-23T00:00:00Z"
    }
  }
}
```

History Service maps internal Provider Service errors into the public
Application API error contract.

---

# Blacklist synchronization behavior

Blacklist synchronization is an internal History Service process and is not
triggered by blacklist-read endpoints.

The initial implementation runs inside History Service and can be disabled by
configuration.

Default policy:

- base synchronization interval: 21600 seconds;
- maximum provider result size: 1000 addresses;
- default confidence minimum: 90;
- only one synchronization may mutate blacklist state at a time.

A synchronization attempt must:

1. register a synchronization run;
2. call `GET /internal/v1/blacklist`;
3. validate the complete Provider Service response;
4. detect duplicate provider snapshots;
5. persist the snapshot and every entry transactionally;
6. persist normalized rate-limit metadata;
7. mark the synchronization run as successful, duplicate, rate-limited, or
   failed;
8. calculate and persist the next allowed attempt time.

A failed synchronization must not remove or replace the latest successful
snapshot.

A duplicate snapshot must not create a second snapshot or duplicate entry rows.

## Next-attempt rules

After a successful request with remaining quota:

```text
next_attempt_at = synchronization_finished_at + configured_interval
```

When `rate_limit.remaining` is zero:

```text
next_attempt_at = max(
    synchronization_finished_at + configured_interval,
    rate_limit.reset_at + jitter
)
```

After HTTP 429, retry timing priority is:

1. `Retry-After`;
2. rate-limit reset time;
3. conservative fallback interval.

A known rate-limit reset time must not be bypassed by exponential backoff.

For temporary connection failures, timeouts, and upstream 5xx failures, History
Service may use bounded exponential backoff.

Recommended progression:

```text
5 minutes -> 15 minutes -> 30 minutes -> 60 minutes
```

Retries must be bounded and must not run continuously.

For invalid provider JSON or an invalid normalized Provider Service response,
History Service should retain the last successful snapshot and wait until the
normal configured interval unless an operator explicitly triggers another
attempt.

---

# Health endpoints

Each service exposes:

```http
GET /health/live
GET /health/ready
```

## Liveness

`live` confirms that the process is running and can serve a simple request.

It must not depend on an external provider lookup.

## Readiness

`ready` confirms that the service is initialized sufficiently to receive
traffic.

Expected behavior:

- UI Service verifies local initialization and configuration and does not
  perform a reputation check;
- History Service verifies local initialization and performs a minimal MariaDB
  connectivity check;
- Provider Service verifies local initialization and required configuration;
- no readiness endpoint may consume AbuseIPDB quota;
- History readiness must not require a successful live blacklist request.

The presence of stale blacklist data does not necessarily make History Service
unready. Staleness is reported through `/api/v1/blacklist/status`.

---

# Application error format

Application-facing errors are returned by `history-service`.

```json
{
  "error": {
    "code": "INVALID_IP_ADDRESS",
    "message": "The supplied value is not a valid public IP address.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}
```

Recommended Application API errors:

| Status | Code |
|---:|---|
| 400 | `INVALID_IP_ADDRESS` |
| 400 | `NON_PUBLIC_IP_ADDRESS` |
| 404 | `HISTORY_RECORD_NOT_FOUND` |
| 404 | `BLACKLIST_SNAPSHOT_NOT_FOUND` |
| 409 | `IDEMPOTENCY_CONFLICT` |
| 409 | `BLACKLIST_SYNC_ALREADY_RUNNING` |
| 422 | `INVALID_REQUEST` |
| 429 | `RATE_LIMIT_EXCEEDED` |
| 502 | `PROVIDER_SERVICE_INVALID_RESPONSE` |
| 502 | `UPSTREAM_INVALID_RESPONSE` |
| 502 | `UPSTREAM_REQUEST_REJECTED` |
| 503 | `PROVIDER_SERVICE_UNAVAILABLE` |
| 503 | `UPSTREAM_AUTHENTICATION_FAILED` |
| 503 | `UPSTREAM_UNAVAILABLE` |
| 503 | `DATABASE_UNAVAILABLE` |
| 504 | `UPSTREAM_TIMEOUT` |

The UI should render readable messages and must not display raw internal error
objects.

---

# Error mapping

History Service should map Provider Service errors into application-oriented
errors.

Suggested mapping:

| Provider Service condition | Application API error |
|---|---|
| `RATE_LIMIT_EXCEEDED` | `RATE_LIMIT_EXCEEDED` |
| `UPSTREAM_INVALID_RESPONSE` | `UPSTREAM_INVALID_RESPONSE` |
| `UPSTREAM_REQUEST_REJECTED` | `UPSTREAM_REQUEST_REJECTED` |
| `UPSTREAM_AUTHENTICATION_FAILED` | `UPSTREAM_AUTHENTICATION_FAILED` |
| `UPSTREAM_UNAVAILABLE` | `UPSTREAM_UNAVAILABLE` |
| `UPSTREAM_TIMEOUT` | `UPSTREAM_TIMEOUT` |
| invalid Provider Service JSON or schema | `PROVIDER_SERVICE_INVALID_RESPONSE` |
| connection failure to Provider Service | `PROVIDER_SERVICE_UNAVAILABLE` |

Provider-specific implementation details must not be unnecessarily exposed
through public application errors.

---

# Request ID behavior

A request ID is carried using:

```http
X-Request-ID: <uuid>
```

Each service should:

- accept a valid incoming UUID;
- generate one when absent according to project policy;
- include it in response headers;
- include it in structured errors;
- propagate it to downstream service requests.

The expected request path is:

```text
UI Service
  -> History Service
  -> Provider Service
```

History Service must also assign a request ID to scheduled synchronization runs.

The request ID used for tracing a synchronization attempt is not a public
manual-check idempotency key.

Provider requests may include the request ID only when doing so is supported and
safe.

---

# UI refresh behavior

UI may poll blacklist status periodically.

Recommended initial interval:

```text
30 seconds
```

Polling flow:

```text
Browser
  -> UI Service
  -> History Service
  -> MariaDB
```

UI should:

1. remember the current `latest_snapshot_id`;
2. request `/api/v1/blacklist/status`;
3. reload the blacklist table only when `latest_snapshot_id` changes;
4. retain currently displayed data after a temporary error;
5. show stale or degraded state without clearing the latest valid snapshot.

UI polling must not:

- call Provider Service directly;
- trigger blacklist synchronization;
- consume AbuseIPDB quota;
- reload the complete table when no snapshot change occurred.

Charts and analytical dashboard endpoints are outside the current scope.

---

# Compatibility

- Application and internal routes are versioned.
- Breaking changes require a new API version.
- Unknown fields from AbuseIPDB may be ignored during Provider Service parsing.
- Unknown fields in internal Provider Service responses should be rejected by
  History Service unless forward-compatible handling is explicitly adopted.
- UI must depend on the Application API rather than provider-specific fields or
  internal routes.
- Provider Service must not expose application history or blacklist persistence
  endpoints.
- History Service's manual-check and blacklist resources exist only under
  `/api/v1/*`.
- The existing manual-check table remains supported by the manual-check API but
  is not used by blacklist synchronization.
- The initial implementation supports complete blacklist snapshots of no more
  than 1000 entries.
