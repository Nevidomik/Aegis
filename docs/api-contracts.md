# API Contracts

All timestamps use UTC ISO 8601. JSON is UTF-8.

## Public Backend API

### Create IP check

```http
POST /api/v1/checks
Content-Type: application/json
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
- `max_age_days` must be between 1 and 365;
- default `max_age_days` is 30.

Success:

```http
201 Created
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

### List history

```http
GET /api/v1/checks?limit=20&offset=0
GET /api/v1/checks?ip_address=8.8.8.8
```

Success:

```json
{
  "items": [],
  "limit": 20,
  "offset": 0,
  "total": 0
}
```

### Get one history record

```http
GET /api/v1/checks/{history_id}
```

## Internal History API

The UI must not call these endpoints.

### Save check

```http
POST /internal/v1/checks
```

The body contains the normalized Backend result and a unique `request_id`.

Success:

```http
201 Created
```

Duplicate `request_id` must not create a second row.

### List checks

```http
GET /internal/v1/checks?limit=20&offset=0
GET /internal/v1/checks?ip_address=8.8.8.8
```

### Get one check

```http
GET /internal/v1/checks/{history_id}
```

## Health endpoints

Each service exposes:

```http
GET /health/live
GET /health/ready
```

`live` confirms that the process is running.

`ready` confirms that required dependencies are available.

## Error format

```json
{
  "error": {
    "code": "INVALID_IP_ADDRESS",
    "message": "The supplied value is not a valid public IP address.",
    "request_id": "6f5aa064-43e8-4dbb-a544-d60b68af5cbd"
  }
}
```

Recommended errors:

| Status | Code |
|---|---|
| 400 | `INVALID_IP_ADDRESS` |
| 400 | `NON_PUBLIC_IP_ADDRESS` |
| 404 | `HISTORY_RECORD_NOT_FOUND` |
| 422 | `INVALID_REQUEST` |
| 429 | `RATE_LIMIT_EXCEEDED` |
| 502 | `UPSTREAM_INVALID_RESPONSE` |
| 503 | `ABUSEIPDB_UNAVAILABLE` |
| 503 | `HISTORY_UNAVAILABLE` |
| 504 | `UPSTREAM_TIMEOUT` |

## Compatibility

- Public and internal routes are versioned.
- Breaking changes require a new API version.
- Unknown fields from AbuseIPDB may be ignored.
- Unknown fields in internal service contracts should be rejected.
