# UI Service

The UI service renders a single HTML page with Jinja2. Browsers submit checks to
UI, and UI communicates only with Backend's public API.

## Configuration

```dotenv
BACKEND_SERVICE_URL=http://127.0.0.1:8001
BACKEND_TIMEOUT_SECONDS=5
```

Install and run from the repository root:

```bash
.venv/bin/pip install -e './services/ui-service[dev]'
.venv/bin/uvicorn ui_service.main:app \
  --app-dir services/ui-service/src \
  --host 127.0.0.1 \
  --port 8000
```

The page is available at `http://127.0.0.1:8000/`. The UI contains no AbuseIPDB,
History Service, or database configuration.

Route tests replace the Backend client and make no live service calls:

```bash
.venv/bin/pytest services/ui-service/tests
```
