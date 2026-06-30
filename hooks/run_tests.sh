#!/usr/bin/env bash
#
# Shared test runner used by the pre-commit and pre-push git hooks.
# Exits non-zero if any test fails, which aborts the commit/push.
#
# Override the tested path with the KIMECO_HOOK_TESTS env var, e.g.:
#   KIMECO_HOOK_TESTS=tests/ git commit ...
#
set -euo pipefail

# Tests required to pass. Mirrors the CI workflow (.github/workflows/tests.yml).
# Broaden to "tests/" once MESS-dependent tests can run locally.
TEST_PATH="${KIMECO_HOOK_TESTS:-tests/unit/}"

# Run from the repository root so relative paths resolve regardless of CWD.
cd "$(git rev-parse --show-toplevel)"

# Prefer the project's "game" conda environment if it exists; otherwise fall
# back to the currently active environment's pytest.
if command -v conda >/dev/null 2>&1 && conda env list | grep -qiE '^[[:space:]]*game[[:space:]]'; then
  RUNNER=(conda run -n game python -m pytest)
else
  RUNNER=(python -m pytest)
fi

echo "[git hook] Running tests: ${TEST_PATH}"
if ! "${RUNNER[@]}" "${TEST_PATH}" -q; then
  echo
  echo "[git hook] Tests failed - aborting."
  echo "[git hook] (Bypass with 'git commit/push --no-verify' only if you are sure.)"
  exit 1
fi

echo "[git hook] All tests passed."
