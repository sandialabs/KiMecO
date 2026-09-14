#!/usr/bin/env bash
#
# Shared test runner used by the pre-commit and pre-push git hooks.
# Exits non-zero if any test fails, which aborts the commit/push.
#
# Override the tested path with the KIMECO_HOOK_TESTS env var, e.g.:
#   KIMECO_HOOK_TESTS=tests/ git commit ...
# Force a specific conda env with KIMECO_HOOK_ENV, e.g.:
#   KIMECO_HOOK_ENV=automech git commit ...
#
set -euo pipefail

# Tests required to pass. Mirrors the CI workflow (.github/workflows/tests.yml).
# Broaden to "tests/" once MESS-dependent tests can run locally.
TEST_PATH="${KIMECO_HOOK_TESTS:-tests/unit/}"

# Run from the repository root so relative paths resolve regardless of CWD.
cd "$(git rev-parse --show-toplevel)"

# An interpreter is usable only if it meets the kimeco floor (>=3.11) AND has
# pytest importable. Never silently fall back to one that cannot run the tests.
PY_CHECK='import sys, pytest; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
py_ok() { "$@" -c "${PY_CHECK}" >/dev/null 2>&1; }
py_desc() { "$@" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || echo "unavailable"; }

# Candidate conda envs, first usable one wins: KIMECO_HOOK_ENV (if set), then
# the project defaults. Envs are located via `conda` when it is on PATH, or
# directly under ~/.conda/envs (IDE git hooks often run without conda on PATH).
CANDIDATES=(${KIMECO_HOOK_ENV:+"${KIMECO_HOOK_ENV}"} kmo kimeco automech)
PYTHON=()
CHOSEN=""
TRIED=()
for env in "${CANDIDATES[@]}"; do
  cmd=()
  if command -v conda >/dev/null 2>&1 \
     && conda env list 2>/dev/null | grep -qiE "^[[:space:]]*${env}[[:space:]]"; then
    cmd=(conda run -n "${env}" python)
  elif [[ -x "${HOME}/.conda/envs/${env}/bin/python" ]]; then
    cmd=("${HOME}/.conda/envs/${env}/bin/python")
  else
    TRIED+=("${env} (not found)")
    continue
  fi
  if py_ok "${cmd[@]}"; then
    PYTHON=("${cmd[@]}")
    CHOSEN="conda env '${env}'"
    break
  fi
  TRIED+=("${env} ($(py_desc "${cmd[@]}"), unusable)")
done

if [[ ${#PYTHON[@]} -eq 0 ]]; then
  ACTIVE_PY="$(command -v python 2>/dev/null || echo "none")"
  if [[ "${ACTIVE_PY}" != "none" ]] && py_ok python; then
    PYTHON=(python)
    CHOSEN="active python (${ACTIVE_PY})"
  else
    TRIED_STR="$(printf '%s, ' "${TRIED[@]}")"; TRIED_STR="${TRIED_STR%, }"
    echo "[git hook] No interpreter with Python >= 3.11 and pytest found" \
         "(tried conda envs: ${TRIED_STR}; active python: ${ACTIVE_PY} $(py_desc python))."
    echo "[git hook] Create one (e.g. 'conda create -n game python=3.11' then 'pip install -e .[test]')" \
         "or set KIMECO_HOOK_ENV=<env>."
    echo "[git hook] (Bypass with 'git commit/push --no-verify' only if you are sure.)"
    exit 1
  fi
fi

echo "[git hook] Using ${CHOSEN}: ${PYTHON[*]}"
echo "[git hook] Running tests: ${TEST_PATH}"
if ! "${PYTHON[@]}" -m pytest "${TEST_PATH}" -q; then
  echo
  echo "[git hook] Tests failed - aborting."
  echo "[git hook] (Bypass with 'git commit/push --no-verify' only if you are sure.)"
  exit 1
fi

echo "[git hook] All tests passed."
