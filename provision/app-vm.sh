#!/usr/bin/env bash
set -Eeuo pipefail

readonly SERVICE_NAME="${1:-}"
readonly PACKAGE_NAME="${2:-}"
readonly PYTHON_BIN="python3.14"
readonly APP_ROOT="/opt/aegis"
readonly SERVICE_DIR="${APP_ROOT}/${SERVICE_NAME}"
readonly SOURCE_DIR="/vagrant/services/${SERVICE_NAME}"
readonly VENV_DIR="${SERVICE_DIR}/.venv"

fail() {
  echo "Aegis application provisioning failed: $*" >&2
  exit 1
}

case "${SERVICE_NAME}:${PACKAGE_NAME}" in
  ui-service:ui_service|history-service:history_service|provider-service:provider_service)
    ;;
  *)
    fail "unsupported service/package pair '${SERVICE_NAME}:${PACKAGE_NAME}'"
    ;;
esac

[[ -f "${SOURCE_DIR}/pyproject.toml" ]] || fail "missing ${SOURCE_DIR}/pyproject.toml"
[[ -d "${SOURCE_DIR}/src/${PACKAGE_NAME}" ]] || fail "missing service package source"

export DEBIAN_FRONTEND=noninteractive

apt-get update

# Ubuntu 24.04 does not always provide the repository-required Python 3.14 in
# its base package sources. Add the Python package archive only when needed.
if ! apt-cache show python3.14 >/dev/null 2>&1; then
  apt-get install --yes --no-install-recommends \
    ca-certificates \
    software-properties-common
  add-apt-repository --yes ppa:deadsnakes/ppa
  apt-get update
fi

apt-get install --yes --no-install-recommends \
  ca-certificates \
  curl \
  python3-pip \
  python3.14 \
  python3.14-venv

if ! id aegis >/dev/null 2>&1; then
  useradd \
    --system \
    --home-dir "${APP_ROOT}" \
    --shell /usr/sbin/nologin \
    --user-group \
    aegis
fi

install -d -o aegis -g aegis -m 0750 "${APP_ROOT}" "${SERVICE_DIR}"

# Replace only the deployed service inputs so repeated provisioning cannot
# leave removed source files behind.
rm -rf "${SERVICE_DIR}/src"
install -o aegis -g aegis -m 0644 \
  "${SOURCE_DIR}/pyproject.toml" \
  "${SERVICE_DIR}/pyproject.toml"
cp -a "${SOURCE_DIR}/src" "${SERVICE_DIR}/src"
chown -R aegis:aegis "${SERVICE_DIR}/src"

if [[ "${SERVICE_NAME}" == "history-service" ]]; then
  rm -rf "${SERVICE_DIR}/alembic"
  install -o aegis -g aegis -m 0644 \
    "${SOURCE_DIR}/alembic.ini" \
    "${SERVICE_DIR}/alembic.ini"
  cp -a "${SOURCE_DIR}/alembic" "${SERVICE_DIR}/alembic"
  chown -R aegis:aegis "${SERVICE_DIR}/alembic"
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  runuser -u aegis -- "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

run_as_aegis() {
  runuser -u aegis -- env \
    HOME="${APP_ROOT}" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    "$@"
}

run_as_aegis "${VENV_DIR}/bin/python" -m pip install --upgrade pip || \
  fail "pip bootstrap failed for ${SERVICE_NAME}"
run_as_aegis "${VENV_DIR}/bin/python" -m pip install --editable "${SERVICE_DIR}" || \
  fail "dependency installation failed for ${SERVICE_NAME}"

run_as_aegis "${VENV_DIR}/bin/python" -c "import ${PACKAGE_NAME}" || \
  fail "package import verification failed for ${PACKAGE_NAME}"

echo "Verified ${PACKAGE_NAME} with ${VENV_DIR}/bin/python"
