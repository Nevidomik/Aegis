# Backend Service

The Backend is an internal AbuseIPDB proxy. It accepts normalized lookup
requests from History Service, validates and normalizes AbuseIPDB responses,
and returns a provider-independent internal result. It has no persistence or
history responsibilities.

## Configuration

Create the service-local file from the repository root:

```bash
cp services/backend-service/.env.example services/backend-service/.env
```

Backend loads that file explicitly regardless of the current working directory:

```dotenv
ABUSEIPDB_BASE_URL=https://api.abuseipdb.com
ABUSEIPDB_API_KEY=replace-me
ABUSEIPDB_CONNECT_TIMEOUT_SECONDS=5
ABUSEIPDB_READ_TIMEOUT_SECONDS=10
ABUSEIPDB_WRITE_TIMEOUT_SECONDS=5
ABUSEIPDB_POOL_TIMEOUT_SECONDS=5
```

`ABUSEIPDB_API_KEY` is required and is read from the service-local environment
file or an exported environment variable at application startup. Never commit or
log a real key. The base URL is fixed in configuration, must use HTTPS, and
cannot be controlled by request data.

Install the locked workspace and run from the repository root:

```bash
uv sync --locked --all-packages --all-extras
.venv/bin/uvicorn backend_service.main:app \
  --app-dir services/backend-service/src \
  --host 127.0.0.1 \
  --port 8001
```

Backend maintains one lifecycle-owned HTTPX client for AbuseIPDB. It is reused
across requests and closed during shutdown.

`POST /internal/v1/reputation-checks` is the internal provider-proxy boundary
for History Service. It accepts only a canonical public `ip_address` and a
`max_age_days` value from 1 through 365, calls the configured AbuseIPDB
endpoint, and returns a validated normalized result. It forwards no request to
History Service and performs no persistence or idempotency work. A valid
`X-Request-ID` is returned in the response header and in safe error envelopes.

Tests replace the reputation provider or use HTTPX mock transports. The default
suite makes no live AbuseIPDB calls:

```bash
.venv/bin/pytest services/backend-service/tests
```
