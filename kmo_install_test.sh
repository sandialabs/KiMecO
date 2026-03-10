#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

fail() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/requirements.txt" ] && [ -f "${SCRIPT_DIR}/pyproject.toml" ]; then
  REPO_DIR="${SCRIPT_DIR}"
elif [ -f "${SCRIPT_DIR}/../requirements.txt" ] && [ -f "${SCRIPT_DIR}/../pyproject.toml" ]; then
  REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
  fail "Could not locate repository root from ${SCRIPT_DIR}"
fi
ENV_NAME="${ENV_NAME:-kimeco-ci}"

log "Script directory: ${SCRIPT_DIR}"
log "Repository root: ${REPO_DIR}"
log "Target conda environment: ${ENV_NAME}"

cd "${REPO_DIR}" || fail "Could not change to repo root"

if ! command -v conda >/dev/null 2>&1; then
  fail "conda is not available in PATH"
fi

log "Using conda from: $(command -v conda)"
log "Conda version: $(conda --version)"

log "Removing existing environment if present"
conda env remove -n "${ENV_NAME}" -y >/dev/null 2>&1 || true

log "Creating fresh conda environment with Python 3.10 and pip"
conda create -n "${ENV_NAME}" -c conda-forge python=3.10 pip -y

log "Loading conda shell support"
source "$(conda info --base)/etc/profile.d/conda.sh"

log "Activating environment ${ENV_NAME}"
conda activate "${ENV_NAME}"

log "Active python: $(command -v python)"
log "Python version: $(python -V)"

log "Installing mamba inside ${ENV_NAME}"
conda install -c conda-forge mamba -y
log "Mamba version: $(mamba --version)"

log "Installing runtime dependencies from requirements.txt with mamba"
mamba install -c conda-forge --file requirements.txt -y

log "Installing build/test tools via mamba to avoid pip build-isolation downloads"
mamba install -c conda-forge setuptools wheel pytest -y

log "Installing package in editable mode without build isolation"
pip install --no-build-isolation --no-deps -e .

log "Running import smoke test"
python - <<'PY'
import ase
import cantera
import dash
import kimeco
import numpy
import pandas
import plotly
import scipy
import sqlalchemy

print("Import checks passed")
PY

log "Running entry-point help checks"
log "Checking kmo --help"
kmo --help

log "Checking kmoui --help"
kmoui --help

log "Checking kmopp --help"
kmopp --help

log "Running pytest"
set +e
pytest -q
rc=$?
set -e

if [ "$rc" -eq 5 ]; then
  log "No tests collected yet. CI-equivalent smoke test passes."
  exit 0
fi

if [ "$rc" -ne 0 ]; then
  fail "pytest failed with exit code ${rc}"
fi

log "Smoke test completed successfully"