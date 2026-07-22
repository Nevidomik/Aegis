# UI Service

The UI service renders the manual-check and blacklist pages with Jinja2.
Browsers communicate with UI, and UI communicates only with History Service's
application API.

## Configuration

Create the service-local file from the repository root:

```bash
cp services/ui-service/.env.example services/ui-service/.env
```

The UI loads that file explicitly regardless of the current working directory:

```dotenv
HISTORY_SERVICE_URL=http://127.0.0.1:8002
HISTORY_TIMEOUT_SECONDS=5
```

Install the locked workspace and run from the repository root:

```bash
uv sync --locked --all-packages --all-extras
.venv/bin/uvicorn ui_service.main:app \
  --app-dir services/ui-service/src \
  --host 127.0.0.1 \
  --port 8000
```

UI reuses one lifecycle-owned HTTPX client for all History requests and closes
it during application shutdown.

The manual-check page is available at `http://127.0.0.1:8000/`, and the tabular
blacklist page is available at `http://127.0.0.1:8000/blacklist`. Charts and
analytical dashboards are outside the current scope. The UI contains no
AbuseIPDB, Provider Service, or database configuration.

The blacklist page polls UI Service's same-origin `/blacklist/status` endpoint
every 30 seconds. UI Service reads status from History Service, which reads
MariaDB. The browser reloads the page only when `latest_snapshot_id` changes;
unchanged snapshots and temporary polling errors leave the displayed table in
place. Polling pauses while the document is hidden. It never calls Provider
Service, triggers synchronization, or consumes AbuseIPDB quota.

Route tests replace the application client and make no live service calls:

```bash
.venv/bin/pytest services/ui-service/tests
```
