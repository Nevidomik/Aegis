# Backend Service

The Backend validates public IP addresses, obtains normalized reputation data
from AbuseIPDB, and persists successful checks through History's HTTP API.

## Configuration

```dotenv
HISTORY_SERVICE_URL=http://127.0.0.1:8002
HISTORY_TIMEOUT_SECONDS=5
ABUSEIPDB_BASE_URL=https://api.abuseipdb.com
ABUSEIPDB_API_KEY=replace-me
ABUSEIPDB_CONNECT_TIMEOUT_SECONDS=5
ABUSEIPDB_READ_TIMEOUT_SECONDS=10
ABUSEIPDB_WRITE_TIMEOUT_SECONDS=5
ABUSEIPDB_POOL_TIMEOUT_SECONDS=5
```

`ABUSEIPDB_API_KEY` is required and is read from the environment at application
startup. Never commit or log a real key. The base URL is fixed in configuration,
must use HTTPS, and cannot be controlled by request data.

Install and run from the repository root:

```bash
.venv/bin/pip install -e './services/backend-service[dev]'
.venv/bin/uvicorn backend_service.main:app \
  --app-dir services/backend-service/src \
  --host 127.0.0.1 \
  --port 8001
```

`POST /api/v1/checks` accepts a public IPv4 or IPv6 address. It accepts an
optional UUID `X-Request-ID`; otherwise Backend generates one. The same ID is
sent to History and returned in the response header and body.

Tests replace the History client and reputation provider or use HTTPX mock
transports. The default suite makes no live AbuseIPDB calls:

```bash
.venv/bin/pytest services/backend-service/tests
```
