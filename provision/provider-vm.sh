#!/usr/bin/env bash
set -Eeuo pipefail

readonly API_KEY_FILE="/tmp/aegis-provider-api-key"
readonly INGESTION_TOKEN_FILE="/tmp/aegis-provider-history-token"
readonly ENVIRONMENT_DIRECTORY="/etc/aegis"
readonly ENVIRONMENT_FILE="${ENVIRONMENT_DIRECTORY}/provider.env"
readonly SERVICE_FILE="/etc/systemd/system/aegis-provider.service"
readonly WORKER_SERVICE_FILE="/etc/systemd/system/aegis-provider-blacklist-worker.service"
readonly SERVICE_DIRECTORY="/opt/aegis/provider-service"
readonly VENV_DIRECTORY="${SERVICE_DIRECTORY}/.venv"
readonly PROVIDER_ADDRESS="192.168.100.12"
readonly PROVIDER_PORT="8001"
readonly HISTORY_URL="http://192.168.100.11:8002"
readonly OUTBOX_DIRECTORY="/var/lib/aegis-provider"

fail() {
  echo "Aegis Provider provisioning failed: $*" >&2
  exit 1
}

[[ -f "${API_KEY_FILE}" ]] || \
  fail "missing Provider API-key upload; check AEGIS_PROVIDER_SECRET_FILE"
[[ -f "${INGESTION_TOKEN_FILE}" ]] || \
  fail "missing ingestion token upload; check AEGIS_INGESTION_SECRET_FILE"
trap 'rm -f "${API_KEY_FILE}" "${INGESTION_TOKEN_FILE}"' EXIT
[[ -x "${VENV_DIRECTORY}/bin/uvicorn" ]] || \
  fail "Provider virtual environment is not installed"
[[ -x "${VENV_DIRECTORY}/bin/aegis-provider-blacklist-worker" ]] || \
  fail "Provider blacklist worker is not installed"
[[ -d "${SERVICE_DIRECTORY}/src/provider_service" ]] || \
  fail "Provider source is not installed"

ABUSEIPDB_API_KEY="$(<"${API_KEY_FILE}")"
INGESTION_TOKEN="$(<"${INGESTION_TOKEN_FILE}")"
[[ -n "${ABUSEIPDB_API_KEY}" ]] || fail "AbuseIPDB API key must not be empty"
[[ "${ABUSEIPDB_API_KEY}" != *$'\n'* ]] || \
  fail "API key file must contain exactly one line"
[[ "${ABUSEIPDB_API_KEY}" =~ ^[A-Za-z0-9._-]+$ ]] || \
  fail "API key contains unsupported characters"
[[ ${#INGESTION_TOKEN} -ge 32 ]] || \
  fail "Provider-History ingestion token must contain at least 32 characters"
[[ "${INGESTION_TOKEN}" =~ ^[A-Za-z0-9._~!@%^+=:-]+$ ]] || \
  fail "Provider-History ingestion token contains unsupported characters"

install -d -o root -g aegis -m 0750 "${ENVIRONMENT_DIRECTORY}"
install -d -o aegis -g aegis -m 0750 "${OUTBOX_DIRECTORY}"

temporary_environment="$(mktemp)"
temporary_service="$(mktemp)"
temporary_worker_service="$(mktemp)"
trap 'rm -f "${temporary_environment}" "${temporary_service}" "${temporary_worker_service}" "${API_KEY_FILE}" "${INGESTION_TOKEN_FILE}"' EXIT

{
  printf 'ABUSEIPDB_BASE_URL=https://api.abuseipdb.com\n'
  printf 'ABUSEIPDB_API_KEY=%s\n' "${ABUSEIPDB_API_KEY}"
  printf 'ABUSEIPDB_CONNECT_TIMEOUT_SECONDS=5\n'
  printf 'ABUSEIPDB_READ_TIMEOUT_SECONDS=10\n'
  printf 'ABUSEIPDB_WRITE_TIMEOUT_SECONDS=5\n'
  printf 'ABUSEIPDB_POOL_TIMEOUT_SECONDS=5\n'
  printf 'ABUSEIPDB_OPERATION_TIMEOUT_SECONDS=20\n'
  printf 'BLACKLIST_POLLING_ENABLED=true\n'
  printf 'BLACKLIST_POLL_INTERVAL_SECONDS=21600\n'
  printf 'BLACKLIST_CONFIDENCE_MINIMUM=90\n'
  printf 'BLACKLIST_OUTBOX_PATH=%s/blacklist-outbox.sqlite3\n' "${OUTBOX_DIRECTORY}"
  printf 'HISTORY_SERVICE_URL=%s\n' "${HISTORY_URL}"
  printf 'HISTORY_INGESTION_TOKEN=%s\n' "${INGESTION_TOKEN}"
  printf 'HISTORY_CONNECT_TIMEOUT_SECONDS=5\n'
  printf 'HISTORY_READ_TIMEOUT_SECONDS=10\n'
  printf 'HISTORY_WRITE_TIMEOUT_SECONDS=10\n'
  printf 'HISTORY_POOL_TIMEOUT_SECONDS=5\n'
  printf 'HISTORY_OPERATION_TIMEOUT_SECONDS=20\n'
  printf 'HISTORY_DELIVERY_RETRY_INITIAL_SECONDS=30\n'
  printf 'HISTORY_DELIVERY_RETRY_MAXIMUM_SECONDS=900\n'
} >"${temporary_environment}"
install -o root -g aegis -m 0640 "${temporary_environment}" "${ENVIRONMENT_FILE}"

cat >"${temporary_service}" <<EOF
[Unit]
Description=Aegis Provider Service
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60s
StartLimitBurst=5

[Service]
Type=simple
User=aegis
Group=aegis
WorkingDirectory=${SERVICE_DIRECTORY}
EnvironmentFile=${ENVIRONMENT_FILE}
ExecStart=${VENV_DIRECTORY}/bin/uvicorn provider_service.main:app --app-dir ${SERVICE_DIRECTORY}/src --host ${PROVIDER_ADDRESS} --port ${PROVIDER_PORT} --no-access-log
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
EOF
install -o root -g root -m 0644 "${temporary_service}" "${SERVICE_FILE}"

cat >"${temporary_worker_service}" <<EOF
[Unit]
Description=Aegis Provider Blacklist Polling Worker
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=60s
StartLimitBurst=5

[Service]
Type=simple
User=aegis
Group=aegis
UMask=0027
WorkingDirectory=${SERVICE_DIRECTORY}
EnvironmentFile=${ENVIRONMENT_FILE}
ExecStart=${VENV_DIRECTORY}/bin/aegis-provider-blacklist-worker
Restart=on-failure
RestartSec=5s
StateDirectory=aegis-provider
StateDirectoryMode=0750
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=${OUTBOX_DIRECTORY}

[Install]
WantedBy=multi-user.target
EOF
install -o root -g root -m 0644 \
  "${temporary_worker_service}" "${WORKER_SERVICE_FILE}"

systemctl daemon-reload
systemctl enable --now aegis-provider.service
systemctl enable --now aegis-provider-blacklist-worker.service
systemctl restart aegis-provider.service
systemctl restart aegis-provider-blacklist-worker.service

wait_for_health() {
  local path="$1"
  local attempts=30

  while (( attempts > 0 )); do
    if curl --fail --silent --show-error --connect-timeout 2 --max-time 3 \
      "http://${PROVIDER_ADDRESS}:${PROVIDER_PORT}${path}" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 2
  done

  fail "Provider health check ${path} did not become ready"
}

wait_for_health "/health/live"
wait_for_health "/health/ready"

echo "Provider Service is healthy at http://${PROVIDER_ADDRESS}:${PROVIDER_PORT}"
