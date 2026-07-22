#!/usr/bin/env bash
set -Eeuo pipefail

readonly ENVIRONMENT_DIRECTORY="/etc/aegis"
readonly ENVIRONMENT_FILE="${ENVIRONMENT_DIRECTORY}/ui.env"
readonly SERVICE_FILE="/etc/systemd/system/aegis-ui.service"
readonly SERVICE_DIRECTORY="/opt/aegis/ui-service"
readonly VENV_DIRECTORY="${SERVICE_DIRECTORY}/.venv"
readonly UI_ADDRESS="192.168.100.10"
readonly UI_PORT="8000"
readonly HISTORY_URL="http://192.168.100.11:8002"

fail() {
  echo "Aegis UI provisioning failed: $*" >&2
  exit 1
}

[[ -x "${VENV_DIRECTORY}/bin/uvicorn" ]] || \
  fail "UI virtual environment is not installed"
[[ -d "${SERVICE_DIRECTORY}/src/ui_service" ]] || \
  fail "UI source is not installed"

install -d -o root -g aegis -m 0750 "${ENVIRONMENT_DIRECTORY}"
temporary_environment="$(mktemp)"
temporary_service="$(mktemp)"
trap 'rm -f "${temporary_environment}" "${temporary_service}"' EXIT

{
  printf 'HISTORY_SERVICE_URL=%s\n' "${HISTORY_URL}"
  printf 'HISTORY_CONNECT_TIMEOUT_SECONDS=3\n'
  printf 'HISTORY_READ_TIMEOUT_SECONDS=5\n'
  printf 'HISTORY_WRITE_TIMEOUT_SECONDS=5\n'
  printf 'HISTORY_POOL_TIMEOUT_SECONDS=3\n'
  printf 'HISTORY_OPERATION_TIMEOUT_SECONDS=10\n'
} >"${temporary_environment}"
install -o root -g aegis -m 0640 "${temporary_environment}" "${ENVIRONMENT_FILE}"

cat >"${temporary_service}" <<EOF
[Unit]
Description=Aegis UI Service
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
ExecStart=${VENV_DIRECTORY}/bin/uvicorn ui_service.main:app --app-dir ${SERVICE_DIRECTORY}/src --host 0.0.0.0 --port ${UI_PORT} --no-access-log
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

systemctl daemon-reload
systemctl enable --now aegis-ui.service
systemctl restart aegis-ui.service

wait_for_health() {
  local path="$1"
  local attempts=30

  while (( attempts > 0 )); do
    if curl --fail --silent --show-error --connect-timeout 2 --max-time 3 \
      "http://${UI_ADDRESS}:${UI_PORT}${path}" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 2
  done

  fail "UI health check ${path} did not become ready"
}

wait_for_health "/health/live"
wait_for_health "/health/ready"

echo "UI Service is healthy at http://${UI_ADDRESS}:${UI_PORT}"
