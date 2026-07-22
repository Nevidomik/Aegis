# UI File Map

This document maps the browser-facing implementation owned by `ui-service`.
The UI is server-rendered with FastAPI and Jinja2, communicates only with
History Service, and has no database or Provider Service access.

## UI-only directory tree

Generated directories such as `.venv`, `.mypy_cache`, and `__pycache__` are
intentionally omitted.

```text
services/ui-service/
├── .env.example
├── README.md
├── pyproject.toml
├── src/
│   └── ui_service/
│       ├── __init__.py
│       ├── application_client.py
│       ├── config.py
│       ├── main.py
│       ├── routes.py
│       ├── schemas.py
│       ├── security_logging.py
│       ├── static/
│       │   └── blacklist.js
│       └── templates/
│           ├── blacklist.html
│           └── index.html
└── tests/
    ├── conftest.py
    ├── test_application_client.py
    ├── test_blacklist_javascript.py
    ├── test_config.py
    ├── test_lifecycle.py
    ├── test_routes.py
    ├── test_security_logging.py
    └── test_startup.py
```

The service-local `.env` is runtime configuration and must not be committed.
The repository `uv.lock` is generated dependency metadata and must be updated
with `uv lock`, not edited manually.

## Route-to-template map

| Browser route | Controller | Template or response | Data dependencies |
| --- | --- | --- | --- |
| `GET /` | `routes.index` | `templates/index.html` | `GET /api/v1/checks?limit=20&offset=0` |
| `POST /` | `routes.submit_check` | `templates/index.html` | `POST /api/v1/checks`, followed by recent history |
| `GET /blacklist?page=N` | `routes.blacklist` | `templates/blacklist.html` | `GET /api/v1/blacklist/status`; when non-empty, `GET /api/v1/blacklist?limit=100&offset=...` |
| `GET /blacklist/status` | `routes.blacklist_status` | Minimal JSON, no template | `GET /api/v1/blacklist/status` |
| `GET /static/blacklist.js` | `routes.blacklist_script` | JavaScript response loaded from `static/blacklist.js` | None |
| `GET /health/live` | `routes.liveness` | JSON, no template | None |
| `GET /health/ready` | `routes.readiness` | JSON, no template | History Service `GET /health/ready` |

`routes.render_page` is the shared Python rendering helper for the main page.
It supplies form state, the current result, recent history, and safe error text
to `index.html`.

## Template inheritance map

There is currently no Jinja inheritance, layout template, macro, or included
fragment.

```text
index.html
└── standalone HTML document
    ├── document head and title
    ├── inline global and page CSS
    ├── cross-page navigation link
    ├── lookup form
    ├── result definition list
    └── recent-history table

blacklist.html
└── standalone HTML document
    ├── document head and title
    ├── inline global and page CSS
    ├── cross-page navigation link
    ├── synchronization status and warnings
    ├── snapshot definition list
    ├── blacklist table
    ├── pagination navigation
    └── polling script bootstrap
```

The two templates duplicate the document shell, base colors, typography,
container and section styles, error styling, definition-list styling, tables,
and responsive rules. A future redesign may introduce a base template,
fragments, and a shared stylesheet, but those files do not exist today.

## Static asset map

| Asset | Served from | Used by | Responsibility |
| --- | --- | --- | --- |
| `src/ui_service/static/blacklist.js` | `/static/blacklist.js` | `blacklist.html` | Same-origin snapshot-status polling and conditional reload |

There are no standalone CSS files, images, icons, fonts, favicons, manifests,
or other repository-owned browser assets. Both templates use inline CSS and
the operating system `system-ui` font stack.

Static files are not mounted as a directory. `routes.py` reads
`blacklist.js` at import time and serves the cached text from a dedicated
route. Adding a new asset therefore requires an explicit serving decision; it
is not enough to place a file under `static/`.

## JavaScript behavior map

`static/blacklist.js` exports `snapshotChanged`, `indicatorMessage`,
`createPoller`, and `start` through a browser/Node-compatible wrapper.

```text
blacklist.html renders latest_snapshot_id
  -> BlacklistPolling.start(...)
  -> schedule poll after 30 seconds
  -> browser GET /blacklist/status with cache disabled
  -> UI Service asks History Service for persisted status
  -> response contains only state, latest_snapshot_id, and data_stale
     ├── snapshot ID changed: reload the full page
     └── snapshot ID unchanged: update indicator text and warning class
```

Behavioral safeguards:

- only one poll may be in flight;
- polling pauses while the document is hidden;
- polling resumes when visibility returns;
- a failed poll preserves the currently rendered snapshot and status;
- polling does not trigger synchronization or call Provider Service;
- the browser never receives the internal History Service URL.

The state messages for `empty`, `ready`, `syncing`, `stale`, and `degraded`
are duplicated between `blacklist.html` and `blacklist.js`. Changes must keep
the initial server render and subsequent JavaScript updates consistent.

## History Service client boundary

`application_client.py` is the sole UI-to-History HTTP boundary. It exposes:

| Client method | History endpoint | UI consumer |
| --- | --- | --- |
| `check` | `POST /api/v1/checks` | Main-page form submission |
| `recent_history` | `GET /api/v1/checks` | Main-page recent history |
| `history_record` | `GET /api/v1/checks/{history_id}` | Available client operation; not currently linked from a page |
| `blacklist_status` | `GET /api/v1/blacklist/status` | Blacklist render and browser polling proxy |
| `blacklist` | `GET /api/v1/blacklist` | Blacklist table and pagination |
| `ready` | `GET /health/ready` | UI readiness endpoint |

The client:

- propagates `X-Request-ID`;
- validates successful bodies with UI-owned Pydantic models from `schemas.py`;
- validates History error envelopes before presenting their safe messages;
- rejects mismatched response request IDs and unexpected response shapes;
- applies an overall operation deadline in addition to the HTTPX connect,
  read, write, and pool timeouts configured by `main.py` and `config.py`;
- maps transport and timeout failures to a safe `ApplicationClientError`.

The corresponding authoritative public contract is documented in
`docs/api-contracts.md` and implemented by History Service's `routes.py`,
`schemas.py`, `service.py`, and `blacklist_read.py`. Provider models must not
be imported into UI Service.

## Recommended edit locations

| Change category | Recommended files | Notes |
| --- | --- | --- |
| Colors | `templates/index.html`, `templates/blacklist.html` | Colors are currently duplicated in inline CSS. For a broad redesign, first introduce an explicitly served shared stylesheet and CSS custom properties. |
| Spacing and sizing | Both templates | `main`, `section`, form, table, definition-list, and responsive spacing are inline. Preserve accessible reflow at the existing mobile breakpoint or replace it deliberately. |
| Typography | Both templates | The current `:root` declarations use `system-ui`. A shared stylesheet would prevent drift. Adding a font also requires a static-serving and licensing decision. |
| Navigation | Both templates | Cross-page links and blacklist pagination are inline. A shared layout or navigation fragment would be the natural reusable owner. Route URLs remain application behavior. |
| Tables | Both templates | Main history and blacklist entry tables share most styles. Column content and conditions depend on validated schema fields. |
| Forms | `templates/index.html`; `routes.py` only when behavior must change | Visual form work belongs in the template. Input names, action, method, ranges, parsing, and error rules are application behavior. |
| Status badges or alerts | `templates/blacklist.html`, `static/blacklist.js`; `index.html` for common alerts | Keep state-to-label/class mapping identical between the server-rendered and polled states. A reusable alert/status fragment and shared CSS are appropriate future owners. |
| Charts | No current presentation file | Charts and analytical dashboards are explicitly outside the current documented scope. Adding them requires product/architecture approval, a defined History data contract, route/client/schema work, a template container, JavaScript, and tests. Do not derive analytics in the browser from undocumented fields. |

For a visual-only redesign, begin with the two templates. Edit `routes.py`,
`schemas.py`, or `application_client.py` only when the approved change actually
requires new data or behavior.

## Tests by UI change category

Run the complete UI suite after any cross-cutting UI change:

```bash
.venv/bin/pytest services/ui-service/tests
```

Focused test guidance:

| Change category | Minimum focused tests | Additional checks |
| --- | --- | --- |
| Colors, spacing, typography | `test_routes.py` | Inspect semantic HTML and responsive rules; there is no visual-regression suite |
| Template structure or shared layout | `test_routes.py`, `test_startup.py` | Run the complete UI suite when introducing new template/static infrastructure |
| Navigation | `test_routes.py` | Verify target routes and pagination query strings |
| Tables or displayed fields | `test_routes.py`, `test_application_client.py` | Run History contract tests if fields or response shapes change |
| Forms | `test_routes.py`, `test_application_client.py` | Cover retained input values, local validation, dependency errors, request IDs, and successful submission |
| Status badges, warnings, or state messages | `test_routes.py`, `test_blacklist_javascript.py` | Cover every state in both initial HTML and polling updates |
| JavaScript or polling | `test_blacklist_javascript.py`, `test_routes.py` | Node is required by the JavaScript test; do not add real-time sleeps |
| History client or schemas | `test_application_client.py`, `test_routes.py`, `test_lifecycle.py` | Also run `services/history-service/tests/test_api.py` and `test_blacklist_api.py` for contract changes |
| Configuration or timeouts | `test_config.py`, `test_lifecycle.py`, `test_application_client.py` | Keep all timeout phases explicit and bounded |
| Logging or public errors | `test_security_logging.py`, `test_routes.py`, `test_application_client.py` | Preserve request-ID correlation and sentinel-secret redaction |
| Dependencies or packaging | Complete UI suite | Run `uv lock --check`, Ruff, and mypy through the repository verification commands |
| Charts or new application data | Complete UI and relevant History suites | Add contract, route, schema, behavior, accessibility, and browser-facing tests before considering the feature complete |

`test_routes.py` currently serves as the template integration suite. There is
no browser automation, screenshot, or visual-regression test suite.

## Files that mix presentation and application behavior

Treat the following files cautiously during design work:

### `templates/index.html`

The file owns appearance but also contains the POST action, form field names,
numeric bounds, conditional result/error behavior, and assumptions about
History response fields. Changing those elements can alter application input
or contract behavior.

### `templates/blacklist.html`

The file owns appearance but also implements status-state branching,
pagination URLs, snapshot-ID serialization, and JavaScript initialization.
Removing or renaming IDs, fields, links, or script options can break polling
or data navigation.

### `static/blacklist.js`

Indicator text and CSS classes are presentational, but reload decisions,
polling interval, visibility handling, overlap prevention, and failure
handling are application behavior. It must continue to use the same-origin UI
status route and must not call History or Provider directly.

### `routes.py`

This is not a template helper module. It owns form validation, dependency
orchestration, request-ID propagation, safe errors, blacklist pagination,
polling JSON, and the static script response. Presentation-only changes should
avoid it unless new template context is genuinely required.

### `schemas.py` and `application_client.py`

These files form an independently validated service boundary. Field names,
types, bounds, error handling, and response validation are API behavior, not
view styling. Do not weaken their validation to accommodate a template.

### `main.py`, `config.py`, and `security_logging.py`

These files control HTTP client lifetime and deadlines, dependency location,
debug mode, exception handling, and sensitive-value redaction. They are
runtime and security infrastructure, not presentation configuration.

Any change that requires new History data must be reconciled with
`docs/api-contracts.md` and History Service's public boundary. UI Service must
remain unaware of the external reputation provider and must never access
MariaDB directly.
