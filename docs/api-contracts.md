# API Contracts

All timestamps use UTC ISO 8601.

JSON is encoded as UTF-8.

Unknown fields in internal service contracts should be rejected unless a specific compatibility rule says otherwise.

---

## Application API

The Application API is exposed by `history-service` and consumed by `ui-service`.

`backend-service` must not expose these application endpoints.

### Create IP check

```http
POST /api/v1/checks
Content-Type: application/json
X-Request-ID: <optional UUID>

```

**Request:**

```json
{
  "ip_address": "8.8.8.8",
  "max_age_days": 90
}

```

**Rules:**

* `ip_address` must be a valid public IPv4 or IPv6 address;
* loopback, private, multicast, link-local, unspecified, and otherwise non-globally-routable addresses are rejected;
* `max_age_days` must be between 1 and 365;
* default `max_age_days` is 30;
* the address is normalized before the provider request;
* History Service owns validation and idempotency;
* Backend Service is called only after application validation succeeds.

**Created response:**

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

**Idempotent response:**
When the same request ID is reused with an equivalent application payload, History Service returns the original persisted result:

```http
HTTP/1.1 200 OK
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd

```

*No new provider lookup or database row should be created when the existing result can be safely resolved from the idempotency record.*

When the same request ID is reused with a different relevant payload:

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

### List history

```http
GET /api/v1/checks?limit=20&offset=0
GET /api/v1/checks?ip_address=8.8.8.8

```

**Query rules:**

* `limit` defaults to 20;
* `limit` must be between 1 and 100;
* `offset` defaults to 0;
* `offset` must be greater than or equal to 0;
* `ip_address`, when supplied, must be normalized before filtering;
* results are ordered by descending `history_id`.

**Success:**

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

### Get one history record

```http
GET /api/v1/checks/{history_id}

```

**Success:**

```http
HTTP/1.1 200 OK

```

*The response uses the same persisted record model returned by `POST /api/v1/checks`.*

**Not found:**

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

---

## Internal Backend Proxy API

The Internal Backend Proxy API is exposed by `backend-service` and consumed **only** by `history-service`.

* UI Service must not call these endpoints.
* Backend Service does not persist results and does not expose history endpoints.
* History Service does not expose an internal persistence API to Backend Service.

### Create provider reputation check

```http
POST /internal/v1/reputation-checks
Content-Type: application/json
X-Request-ID: 6f5aa064-43e8-4dbb-a544-d60b68af5cbd

```

**Request:**

```json
{
  "ip_address": "8.8.8.8",
  "max_age_days": 90
}

```

**Rules:**

* the request is expected to contain a normalized IP address;
* `ip_address` must still conform to the internal schema;
* `max_age_days` must be between 1 and 365;
* Backend Service must not accept a user-supplied upstream URL;
* Backend Service must use its configured AbuseIPDB endpoint;
* Backend Service must validate the AbuseIPDB response;
* Backend Service must not access MariaDB;
* Backend Service must not implement persistence idempotency.

**Success:**

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

*Note: The internal response does not include `history_id`, persistence status, database metadata, MariaDB identifiers, or application idempotency information. Those fields are owned by History Service.*

### Internal proxy errors

Backend Service returns stable internal errors.

**Example:**

```json
{
  "error": {
    "code": "UPSTREAM_TIMEOUT",
    "message": "The reputation provider did not respond before the timeout.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}

```

**Expected internal errors include:**

| Status Code | Code | Meaning |
| --- | --- | --- |
| **422** | `INVALID_REQUEST` | Internal request schema is invalid |
| **429** | `RATE_LIMIT_EXCEEDED` | AbuseIPDB quota or rate limit was reached |
| **502** | `UPSTREAM_INVALID_RESPONSE` | AbuseIPDB returned an invalid response |
| **502** | `UPSTREAM_REQUEST_REJECTED` | AbuseIPDB rejected the request |
| **503** | `ABUSEIPDB_AUTHENTICATION_FAILED` | AbuseIPDB credentials were rejected |
| **503** | `ABUSEIPDB_UNAVAILABLE` | AbuseIPDB could not be reached |
| **504** | `UPSTREAM_TIMEOUT` | AbuseIPDB request timed out |

*History Service maps these internal errors into the Application API error contract.*

---

## Health endpoints

Each service exposes:

* `GET /health/live`
* `GET /health/ready`

### Liveness

`live` confirms that the process is running and can serve a simple request. It must not depend on an external provider lookup.

### Readiness

`ready` confirms that the service is initialized sufficiently to receive traffic.

**Expected behavior:**

* **UI Service:** verifies local initialization and configuration; does not perform a reputation check.
* **History Service:** verifies local initialization; performs a minimal MariaDB connectivity check; does not perform a real AbuseIPDB lookup.
* **Backend Service:** verifies local initialization and required configuration; does not consume AbuseIPDB quota.

---

## Application error format

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

**Recommended Application API errors:**

| Status Code | Code |
| --- | --- |
| **400** | `INVALID_IP_ADDRESS` |
| **400** | `NON_PUBLIC_IP_ADDRESS` |
| **404** | `HISTORY_RECORD_NOT_FOUND` |
| **409** | `IDEMPOTENCY_CONFLICT` |
| **422** | `INVALID_REQUEST` |
| **429** | `RATE_LIMIT_EXCEEDED` |
| **502** | `PROVIDER_INVALID_RESPONSE` |
| **502** | `PROVIDER_REQUEST_REJECTED` |
| **502** | `BACKEND_INVALID_RESPONSE` |
| **503** | `PROVIDER_AUTHENTICATION_FAILED` |
| **503** | `PROVIDER_UNAVAILABLE` |
| **503** | `BACKEND_UNAVAILABLE` |
| **503** | `DATABASE_UNAVAILABLE` |
| **504** | `PROVIDER_TIMEOUT` |

*The UI should render readable messages and must not display raw internal error objects.*

---

## Error mapping

History Service should map Backend Service errors into application-oriented errors.

**Suggested mapping:**

| Backend Service error | Application API error |
| --- | --- |
| `RATE_LIMIT_EXCEEDED` | `RATE_LIMIT_EXCEEDED` |
| `UPSTREAM_INVALID_RESPONSE` | `PROVIDER_INVALID_RESPONSE` |
| `UPSTREAM_REQUEST_REJECTED` | `PROVIDER_REQUEST_REJECTED` |
| `ABUSEIPDB_AUTHENTICATION_FAILED` | `PROVIDER_AUTHENTICATION_FAILED` |
| `ABUSEIPDB_UNAVAILABLE` | `PROVIDER_UNAVAILABLE` |
| `UPSTREAM_TIMEOUT` | `PROVIDER_TIMEOUT` |
| *invalid proxy JSON or schema* | `BACKEND_INVALID_RESPONSE` |
| *connection failure to Backend* | `BACKEND_UNAVAILABLE` |

*Provider-specific names should not be unnecessarily exposed through the application-facing contract.*

---

## Request ID behavior

A request ID is carried using:
`X-Request-ID: <uuid>`

**Each service should:**

* accept a valid incoming UUID;
* generate one when absent according to project policy;
* include it in response headers;
* include it in structured errors;
* propagate it to downstream requests.

**The expected propagation path is:**

```text
UI Service -> History Service -> Backend Service

```

*The provider request may include the request ID only if doing so is supported and safe.*

---

## Compatibility

* Application and internal routes are versioned.
* Breaking changes require a new API version.
* Unknown fields from AbuseIPDB may be ignored during provider parsing.
* Unknown fields in the Backend internal response should be rejected by History Service unless forward-compatible handling is explicitly adopted.
* UI must depend on the Application API rather than provider-specific fields or internal proxy routes.
* Backend Service must not expose application history endpoints.
* History Service's check and history resources exist only under `/api/v1/*`.
