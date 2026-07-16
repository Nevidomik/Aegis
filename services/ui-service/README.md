# UI Service

The UI service renders a single HTML page with Jinja2. Browsers submit checks to
UI, and UI communicates only with Backend's public API.

## Configuration

Create the service-local file from the repository root:

```bash
cp services/ui-service/.env.example services/ui-service/.env
```

The UI loads that file explicitly regardless of the current working directory:

```dotenv
BACKEND_SERVICE_URL=http://127.0.0.1:8001
BACKEND_TIMEOUT_SECONDS=5
```

Install the locked workspace and run from the repository root:

```bash
uv sync --locked --all-packages --all-extras
.venv/bin/uvicorn ui_service.main:app \
  --app-dir services/ui-service/src \
  --host 127.0.0.1 \
  --port 8000
```

UI reuses one lifecycle-owned HTTPX client for all Backend requests and closes
it during application shutdown.

The page is available at `http://127.0.0.1:8000/`. The UI contains no AbuseIPDB,
History Service, or database configuration.

Route tests replace the Backend client and make no live service calls:

```bash
.venv/bin/pytest services/ui-service/tests
```
