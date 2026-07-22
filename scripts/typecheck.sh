#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly MYPY="${REPOSITORY_ROOT}/.venv/bin/python"

cd "${REPOSITORY_ROOT}"

# Production packages are checked together by the documented repository command.
"${MYPY}" -m mypy services

# Recheck each independently runnable application with its service-local config.
for service in \
  services/history-service \
  services/provider-service \
  services/ui-service; do
  "${MYPY}" -m mypy --config-file mypy-service.ini "${service}/src"
done
