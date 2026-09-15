#!/usr/bin/env bash
set -euo pipefail

EXP_DIR="/workspaces/ai-sequence-identification/experiments/retrieval_H1"
VENV_PATH="${EXP_DIR}/.venv"
STAMP_FILE="${VENV_PATH}/.evee-install-stamp"
PYPROJECT_PATH="${EXP_DIR}/pyproject.toml"
BASE_PYTHON="$(command -v python3)"
if [ -z "${BASE_PYTHON}" ]; then
    echo "==> python3 not found on PATH; cannot create virtual environment." >&2
    exit 1
fi
PYTHON_BIN="${VENV_PATH}/bin/python"
PYPROJECT_STAMP=""
VENV_STAMP=""
REBUILD_ENV=false

compute_current_stamp() {
    PYPROJECT_STAMP=""

    if [ -f "${PYPROJECT_PATH}" ]; then
        PYPROJECT_STAMP="$(sha256sum "${PYPROJECT_PATH}" | awk '{print $1}')"
    fi
}

read_installed_stamp() {
    VENV_STAMP=""

    if [ -f "${STAMP_FILE}" ]; then
        VENV_STAMP="$(cat "${STAMP_FILE}")"
    fi
}

should_reinstall() {
    REBUILD_ENV=false

    if [ ! -d "${VENV_PATH}" ] || [ ! -f "${STAMP_FILE}" ] || [ "${PYPROJECT_STAMP}" != "${VENV_STAMP}" ]; then
        REBUILD_ENV=true
    fi

    if [ -f "${PYPROJECT_PATH}" ] && [ -z "${PYPROJECT_STAMP}" ]; then
        echo "==> Could not compute dependency stamp from ${PYPROJECT_PATH}; forcing reinstall."
        REBUILD_ENV=true
    fi
}

recreate_venv() {
    if [ -d "${VENV_PATH}" ]; then
        echo "==> Recreating virtual environment to match declared dependencies."
        rm -rf "${VENV_PATH}"
    fi

    "${BASE_PYTHON}" -m venv "${VENV_PATH}"
    "${PYTHON_BIN}" -m pip install --upgrade pip setuptools wheel
}

ensure_toml_compat() {
    # tomllib is only available in Python 3.11+.
    "${PYTHON_BIN}" - <<'PY'
import subprocess
import sys

if sys.version_info < (3, 11):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", "tomli"])
PY
}

install_dependencies() {
    if [ -f "${PYPROJECT_PATH}" ]; then
        mapfile -t DEPS < <("${PYTHON_BIN}" - "${PYPROJECT_PATH}" <<'PY'
import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

with open(sys.argv[1], "rb") as f:
    data = tomllib.load(f)

for dep in data.get("project", {}).get("dependencies", []):
    print(dep)
PY
)

        if [ "${#DEPS[@]}" -gt 0 ]; then
            "${PYTHON_BIN}" -m pip install --no-cache-dir "${DEPS[@]}"
        else
            echo "==> No dependencies found in ${PYPROJECT_PATH}; skipping pip install."
        fi
    else
        echo "==> ${PYPROJECT_PATH} not found; skipping pip install."
    fi
}

write_stamp() {
    if [ -n "${PYPROJECT_STAMP}" ]; then
        echo "${PYPROJECT_STAMP}" > "${STAMP_FILE}"
    fi
}

if [ ! -d "${EXP_DIR}" ]; then
    echo "==> Skipping Evee setup; ${EXP_DIR} not found."
    exit 0
fi

compute_current_stamp
read_installed_stamp
should_reinstall

if [ "${REBUILD_ENV}" = true ]; then
    echo "==> Setting up Evee virtual environment in ${VENV_PATH}..."
    recreate_venv
    ensure_toml_compat
    install_dependencies
    write_stamp
else
    echo "==> Evee environment is up to date."
fi

echo "==> Evee command version:"
"${VENV_PATH}/bin/evee" --version || true
