# Aegis

A small multi-service IP reputation application.

Aegis checks public IPv4 and IPv6 addresses through AbuseIPDB and periodically
synchronizes a limited AbuseIPDB blacklist into MariaDB.

The web interface displays the latest locally persisted blacklist snapshot and
updates automatically when a newer snapshot becomes available.

## Architecture

```text
Browser
  │
  ▼
UI Service ──HTTP──> History Service ──HTTP──> Provider Service
                         │                    │
                         ▼                    └──HTTPS──> AbuseIPDB
                      MariaDB
```

Scheduled blacklist flow:

History Service scheduler
  -> Provider Service
  -> AbuseIPDB Blacklist API
  -> History Service
  -> MariaDB

Service responsibilities:

- **UI Service** — renders the interface and communicates only with History Service.

- **History Service** — acts as the application backend, exclusively owns MariaDB, runs blacklist synchronization, and stores complete blacklist snapshots.

- **Provider Service** — acts as an internal AbuseIPDB adapter. It validates and normalizes provider responses but does not persist data or run scheduled jobs.

More details: [`docs/architecture.md`](docs/architecture.md)

## Stack

- Python 3
- FastAPI
- Jinja2
- HTTPX
- Pydantic
- SQLAlchemy 2.x
- Alembic
- MariaDB
- pytest
- Ruff

## Repository layout

```text
services/
├── ui-service/
├── provider-service/
└── history-service/

docs/
├── architecture.md
├── api-contracts.md
└── adr/
```

## Configuration

Each service loads its own `.env` file using a path anchored to that service, so
commands behave the same from any working directory. Create the local files from
the repository root:

```bash
cp services/ui-service/.env.example services/ui-service/.env
cp services/provider-service/.env.example services/provider-service/.env
cp services/history-service/.env.example services/history-service/.env
```

Replace the placeholders for required secrets. They must never be committed:

- `ABUSEIPDB_API_KEY`
- `MARIADB_PASSWORD`

## Local development

Install `uv` 0.11 (the supported tool range is enforced by the root project),
then create the repository environment from the committed lockfile:

```bash
uv sync --locked --all-packages --all-extras
```

This installs all three independently declared service projects into `.venv`.
Use `uv lock` after an intentional dependency change, review `uv.lock`, and
commit the updated manifest and lockfile together. Normal setup and CI should
use `--locked` so stale dependency metadata fails instead of being resolved
implicitly.

Run a service from the repository root, for example:

```bash
.venv/bin/uvicorn ui_service.main:app \
  --app-dir services/ui-service/src \
  --host 127.0.0.1 \
  --port 8000
```

When the in-process History blacklist scheduler is enabled, run exactly one
scheduler-enabled History worker. Do not use multiple Uvicorn workers with
`BLACKLIST_SCHEDULER_ENABLED=true`; additional request-serving processes must
disable the scheduler.

The scheduler's default interval is 21600 seconds (six hours). Rate-limit
metadata may move the next attempt later, while temporary failures use bounded
5, 15, 30, and 60 minute retries. A known provider reset time is never bypassed.

Verification commands:

```bash
make check
```

Database schema changes must be applied through Alembic migrations. All
migration commands in the History Service README run from the repository root.

## Vagrant topology

The base Vagrant environment creates four Ubuntu virtual machines on a private
network. The application VMs receive isolated Python environments, Provider
Service is deployed on `provider-vm`, and the database VM receives MariaDB
only. History and UI are not started yet.

| Virtual machine | Address | Intended role |
| --- | --- | --- |
| `ui-vm` | `192.168.56.10` | User-facing UI Service |
| `history-vm` | `192.168.56.11` | Internal History Service |
| `provider-vm` | `192.168.56.12` | Internal Provider Service |
| `db-vm` | `192.168.56.13` | Internal MariaDB host |

Manage the environment from the repository root:

```bash
vagrant up
vagrant status
vagrant ssh ui-vm
vagrant ssh history-vm
vagrant ssh provider-vm
vagrant ssh db-vm
vagrant halt
vagrant destroy -f
```

The `vagrant ssh <vm>` form accepts any virtual-machine name shown in the
table. No public forwarded ports are configured; the host-only private network
makes the future UI endpoint reachable at `192.168.56.10`.

Before the first `vagrant up`, create the host-local password file used to
provision MariaDB and configure History Service. Keep it outside the shared
repository:

```bash
umask 077
mkdir -p ~/.config/aegis
printf '%s\n' 'choose-a-strong-local-password' > ~/.config/aegis/mariadb-password
```

The file must contain exactly one non-empty line using letters, numbers, dots,
underscores, or the documented safe punctuation characters
`~!@%^+=:-`. It remains on the host and is uploaded only to `db-vm` and
`history-vm`; do not use the example text as the real password. To use another
location, export `AEGIS_DATABASE_SECRET_FILE` with an absolute path before
running Vagrant.

MariaDB is bound to `192.168.56.13:3306` without a public forwarded port. The
`aegis_history` account accepts connections only from History VM address
`192.168.56.11`.

Re-run database provisioning and check MariaDB health with:

```bash
vagrant provision db-vm
vagrant ssh db-vm -c "sudo mysqladmin --protocol=socket ping"
```

Schema migrations remain the responsibility of History Service and are not run
on `db-vm`.

Create the host-local Provider API-key file outside the shared repository
before provisioning `provider-vm`:

```bash
umask 077
mkdir -p ~/.config/aegis
printf '%s\n' 'your-real-abuseipdb-api-key' > ~/.config/aegis/abuseipdb-api-key
```

The key file must contain one non-empty line using letters, numbers, dots,
underscores, or hyphens. Vagrant uploads it only to `provider-vm`; provisioning
installs it as `/etc/aegis/provider.env` with restrictive permissions and
removes the temporary upload. The key is not placed in the shared `/vagrant`
directory, Vagrantfile, or a shell argument.

To keep the key elsewhere, export its path before running Vagrant:

```bash
export AEGIS_PROVIDER_SECRET_FILE=/absolute/path/to/abuseipdb-api-key
vagrant up provider-vm
```

Provider Service runs as `aegis` through `aegis-provider.service` and listens
on the private address `192.168.56.12:8001`. Inspect its state and logs with:

```bash
vagrant ssh provider-vm -c "sudo systemctl status aegis-provider.service"
vagrant ssh provider-vm -c "sudo journalctl -u aegis-provider.service -n 100 --no-pager"
vagrant ssh provider-vm -c "sudo journalctl -u aegis-provider.service -f"
```

Reprovisioning `provider-vm` reinstalls only Provider dependencies, refreshes
its environment and unit files, restarts the unit, and verifies both Provider
health endpoints.

History Service runs as `aegis` through `aegis-history.service` and listens on
the private address `192.168.56.11:8002`. Provisioning writes the protected
`/etc/aegis/history.env`, waits for MariaDB and Provider readiness, applies
History-owned Alembic migrations from `/opt/aegis/history-service`, and then
starts one Uvicorn process. `BLACKLIST_SCHEDULER_ENABLED=true`, so no additional
History workers should be added.

Provider readiness verification calls only `/health/ready`; it does not make an
AbuseIPDB request or consume API quota. History readiness executes a minimal
MariaDB query. Inspect the deployed service with:

```bash
vagrant ssh history-vm -c "sudo systemctl status aegis-history.service"
vagrant ssh history-vm -c "sudo journalctl -u aegis-history.service -n 100 --no-pager"
vagrant ssh history-vm -c "sudo journalctl -u aegis-history.service -f"
vagrant ssh history-vm -c "curl --fail http://192.168.56.11:8002/health/live"
vagrant ssh history-vm -c "curl --fail http://192.168.56.11:8002/health/ready"
```

History is available only on the private Vagrant network; no host public port
is forwarded.

UI Service runs as `aegis` through `aegis-ui.service`, listens on
`0.0.0.0:8000`, and calls History at `http://192.168.56.11:8002`. Its protected
`/etc/aegis/ui.env` contains only `HISTORY_SERVICE_URL` and
phase-specific `HISTORY_*_TIMEOUT_SECONDS`; it contains no Provider URL,
AbuseIPDB key, or
MariaDB settings. The server-rendered UI continues to keep internal service
URLs out of browser-side JavaScript.

Provisioning verifies UI liveness and its History-backed readiness from the
guest. A Vagrant host trigger also verifies that the host can reach
`http://192.168.56.10:8000`. Inspect the UI with:

```bash
curl --fail http://192.168.56.10:8000/health/live
curl --fail http://192.168.56.10:8000/health/ready
vagrant ssh ui-vm -c "sudo systemctl status aegis-ui.service"
vagrant ssh ui-vm -c "sudo journalctl -u aegis-ui.service -n 100 --no-pager"
vagrant ssh ui-vm -c "sudo journalctl -u aegis-ui.service -f"
```

No reverse proxy is required by the current project and none is installed.

### Guest firewall policy

All four guests use Ubuntu's UFW firewall with inbound traffic denied and
outbound traffic allowed by default. TCP 22 remains open for Vagrant SSH. The
private-network application rules are:

| Destination | Allowed source | TCP port |
| --- | --- | ---: |
| `ui-vm` | Vagrant private network `192.168.56.0/24` | 8000 |
| `history-vm` | `ui-vm` (`192.168.56.10`) | 8002 |
| `provider-vm` | `history-vm` (`192.168.56.11`) | 8001 |
| `db-vm` | `history-vm` (`192.168.56.11`) | 3306 |

History and Provider also allow their own private addresses to reach their
respective service ports for local provisioning health checks.

Normal outbound access remains available for package installation. Provider
can make outbound HTTPS requests to AbuseIPDB. Explicit outbound deny rules
block UI from Provider TCP 8001 and MariaDB TCP 3306, and block Provider from
MariaDB TCP 3306.

Inspect the effective rules on each guest:

```bash
vagrant ssh ui-vm -c "sudo ufw status verbose"
vagrant ssh history-vm -c "sudo ufw status verbose"
vagrant ssh provider-vm -c "sudo ufw status verbose"
vagrant ssh db-vm -c "sudo ufw status verbose"
```

Verify allowed paths from their actual source guests:

```bash
curl --fail http://192.168.56.10:8000/health/live
vagrant ssh ui-vm -c "curl --fail http://192.168.56.11:8002/health/live"
vagrant ssh history-vm -c "curl --fail http://192.168.56.12:8001/health/live"
vagrant ssh history-vm -c "timeout 3 bash -c '</dev/tcp/192.168.56.13/3306'"
```

Verify prohibited paths fail:

```bash
vagrant ssh ui-vm -c "! curl --connect-timeout 3 http://192.168.56.12:8001/health/live"
vagrant ssh ui-vm -c "! timeout 3 bash -c '</dev/tcp/192.168.56.13/3306'"
vagrant ssh provider-vm -c "! timeout 3 bash -c '</dev/tcp/192.168.56.13/3306'"
```

### End-to-end deployment verification

Run the default quota-free deployment verification from the repository root:

```bash
scripts/verify-vagrant.sh
```

It checks VM state and private addresses, health endpoints, UI pages, blacklist
status, MariaDB and application units, History database readiness,
UI-to-History communication, and application process ownership. It prints a
PASS/FAIL summary and exits non-zero if any check fails. The default mode never
calls a Provider lookup or blacklist endpoint and does not consume AbuseIPDB
quota.

To deliberately perform one live AbuseIPDB-backed reputation request, provide
a global IP address using the explicitly opt-in mode:

```bash
scripts/verify-vagrant.sh --live-abuseipdb 8.8.8.8
```

This mode consumes AbuseIPDB quota and persists a successful manual lookup in
History Service.

For troubleshooting, inspect topology and enter a guest with:

```bash
vagrant status
vagrant ssh <vm>
```

Inspect services, logs, and listening sockets inside the relevant guest:

```bash
sudo systemctl status aegis-ui.service
sudo systemctl status aegis-history.service
sudo systemctl status aegis-provider.service
sudo systemctl status mariadb.service
sudo journalctl -u aegis-history.service -n 100 --no-pager
sudo journalctl -u aegis-history.service -f
sudo ss -lntp
```

Check service health and MariaDB connectivity from the expected source VM:

```bash
curl --fail http://192.168.56.10:8000/health/live
curl --fail http://192.168.56.11:8002/health/ready
curl --fail http://192.168.56.12:8001/health/ready
sudo mysqladmin --protocol=socket ping
timeout 3 bash -c '</dev/tcp/192.168.56.13/3306'
```

The three application VMs are provisioned independently. Each receives only
its own service source and dependency metadata under `/opt/aegis`, with a
dedicated virtual environment owned by the restricted `aegis` system user.
All three application services are started. Re-run provisioning after source
or dependency changes with:

```bash
vagrant provision ui-vm
vagrant provision history-vm
vagrant provision provider-vm
```

Verify the installed package in any application VM with the corresponding
command:

```bash
vagrant ssh ui-vm -c "/opt/aegis/ui-service/.venv/bin/python -c 'import ui_service'"
vagrant ssh history-vm -c "/opt/aegis/history-service/.venv/bin/python -c 'import history_service'"
vagrant ssh provider-vm -c "/opt/aegis/provider-service/.venv/bin/python -c 'import provider_service'"
```

## Current scope

The application supports:

- validation of public IPv4 and IPv6 addresses;
- normalized individual AbuseIPDB lookups;
- persistence of successful manual checks;
- scheduled retrieval of up to 1000 blacklist entries;
- complete blacklist snapshots in MariaDB;
- full historical retention of accepted snapshots for the initial implementation;
- tabular display of the latest successful snapshot;
- automatic UI refresh when a new local snapshot is available;
- rate-limit-aware retry behavior;
- explicit separation between UI, application, and provider responsibilities.

Not included yet:

- authentication;
- charts and analytical dashboards;
- cron or a dedicated scheduler process;
- message queues;
- caching;
- multiple reputation providers;
- Docker or Kubernetes;
- cloud deployment.

The existing manual-check table and API remain supported. Blacklist
synchronization writes only to the blacklist snapshot and synchronization
tables. Browser polling reads local state through UI Service and History
Service; it never triggers Provider Service or an AbuseIPDB request.

## Documentation

- [Architecture](docs/architecture.md)
- [API contracts](docs/api-contracts.md)
- [Architecture decisions](docs/adr/)
