#!/usr/bin/env bash
set -uo pipefail

readonly SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY_ROOT="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"

passed=0
failed=0
live_ip=""

usage() {
  cat <<'EOF'
Usage:
  scripts/verify-vagrant.sh
  scripts/verify-vagrant.sh --live-abuseipdb <public-ip>

The default mode uses only local health and deployment endpoints. The live mode
performs one AbuseIPDB-backed reputation request and consumes provider quota.
EOF
}

case "${1:-}" in
  "")
    ;;
  --live-abuseipdb)
    [[ $# -eq 2 ]] || {
      usage >&2
      exit 2
    }
    live_ip="$2"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

cd "${REPOSITORY_ROOT}" || exit 2

pass() {
  printf 'PASS  %s\n' "$1"
  passed=$((passed + 1))
}

fail() {
  printf 'FAIL  %s\n' "$1"
  failed=$((failed + 1))
}

check() {
  local description="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    pass "${description}"
  else
    fail "${description}"
  fi
}

vm_is_running() {
  local vm="$1"
  local state
  state="$(vagrant status "${vm}" --machine-readable 2>/dev/null | \
    awk -F, '$3 == "state" { print $4; exit }')"
  [[ "${state}" == "running" ]]
}

private_ip_responds() {
  local address="$1"
  timeout 3 bash -c "</dev/tcp/${address}/22"
}

guest_http_ok() {
  local vm="$1"
  local url="$2"
  vagrant ssh "${vm}" -c "curl --fail --silent --show-error '${url}'"
}

unit_is_active() {
  local vm="$1"
  local unit="$2"
  vagrant ssh "${vm}" -c "sudo systemctl is-active --quiet '${unit}'"
}

unit_runs_as_aegis() {
  local vm="$1"
  local unit="$2"
  local owner
  owner="$(vagrant ssh "${vm}" -c \
    "pid=\$(sudo systemctl show --property MainPID --value '${unit}'); test \"\${pid}\" -gt 0; ps -o user= -p \"\${pid}\"" \
    2>/dev/null | tr -d '[:space:]')"
  [[ "${owner}" == "aegis" ]]
}

no_root_application_process() {
  local vm="$1"
  local entry_point="$2"
  vagrant ssh "${vm}" -c \
    "ps -eo user=,args= | awk '\$1 == \"root\" && index(\$0, \"${entry_point}\") { found=1 } END { exit found }'"
}

for vm in db-vm provider-vm history-vm ui-vm; do
  check "${vm} is running" vm_is_running "${vm}"
done

for target in \
  "ui-vm:192.168.56.10" \
  "history-vm:192.168.56.11" \
  "provider-vm:192.168.56.12" \
  "db-vm:192.168.56.13"; do
  vm="${target%%:*}"
  address="${target#*:}"
  check "${vm} private address ${address} responds" private_ip_responds "${address}"
done

check "Provider liveness" guest_http_ok provider-vm \
  http://192.168.56.12:8001/health/live
check "Provider readiness (quota-free)" guest_http_ok provider-vm \
  http://192.168.56.12:8001/health/ready
check "History liveness" guest_http_ok history-vm \
  http://192.168.56.11:8002/health/live
check "History readiness" guest_http_ok history-vm \
  http://192.168.56.11:8002/health/ready
check "UI liveness" curl --fail --silent --show-error \
  http://192.168.56.10:8000/health/live
check "UI readiness" curl --fail --silent --show-error \
  http://192.168.56.10:8000/health/ready
check "UI main page from host" curl --fail --silent --show-error \
  http://192.168.56.10:8000/
check "UI blacklist page from host" curl --fail --silent --show-error \
  http://192.168.56.10:8000/blacklist
check "History blacklist status" guest_http_ok ui-vm \
  http://192.168.56.11:8002/api/v1/blacklist/status

check "MariaDB systemd unit is active" unit_is_active db-vm mariadb.service
check "Provider systemd unit is active" unit_is_active provider-vm \
  aegis-provider.service
check "History systemd unit is active" unit_is_active history-vm \
  aegis-history.service
check "UI systemd unit is active" unit_is_active ui-vm aegis-ui.service

# History readiness executes SELECT 1 against its configured MariaDB session.
check "History can read MariaDB" guest_http_ok history-vm \
  http://192.168.56.11:8002/health/ready
# UI readiness calls History readiness, proving the UI-to-History path.
check "UI can communicate with History" guest_http_ok ui-vm \
  http://192.168.56.10:8000/health/ready

check "Provider process runs as aegis" unit_runs_as_aegis provider-vm \
  aegis-provider.service
check "History process runs as aegis" unit_runs_as_aegis history-vm \
  aegis-history.service
check "UI process runs as aegis" unit_runs_as_aegis ui-vm aegis-ui.service
check "No Provider application process runs as root" \
  no_root_application_process provider-vm provider_service.main:app
check "No History application process runs as root" \
  no_root_application_process history-vm history_service.main:app
check "No UI application process runs as root" \
  no_root_application_process ui-vm ui_service.main:app

if [[ -n "${live_ip}" ]]; then
  if canonical_ip="$(python3 - "${live_ip}" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1])
if not address.is_global:
    raise SystemExit(1)
print(address.compressed)
PY
  )"; then
    request_id="$(< /proc/sys/kernel/random/uuid)"
    check "Live AbuseIPDB reputation request for ${canonical_ip}" \
      vagrant ssh ui-vm -c \
      "curl --fail --silent --show-error -X POST \
        -H 'Content-Type: application/json' \
        -H 'X-Request-ID: ${request_id}' \
        --data '{\"ip_address\":\"${canonical_ip}\",\"max_age_days\":30}' \
        http://192.168.56.11:8002/api/v1/checks"
  else
    fail "Live verification IP is not a global IPv4 or IPv6 address"
  fi
fi

printf '\nSummary: %d passed, %d failed\n' "${passed}" "${failed}"
(( failed == 0 ))
