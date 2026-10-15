---
name: run-tests
description: "Run the KiMecO automated test suite locally the same way the git hooks and CI do. Use when asked to run tests or pytest, check that a change passes before commit or push, reproduce a GitHub Actions or GitLab CI failure, install the repository git hooks, or investigate why a pre-commit or pre-push hook is failing. Only runs tests; designing and authoring new tests belongs to the ci-test agent."
---
# Run tests

## When to use

Running the existing suite before commit/push, reproducing a CI failure, installing or debugging the git hooks. Designing or writing tests is the `ci-test` agent's job, not this skill's.

## Prerequisites

- A Python 3.10–3.12 environment with KiMecO installed editable, including test and agentic extras:
  ```bash
  pip install -e .[test,agentic]
  ```
  (`test` = `pytest>=9.0.2`; `agentic` = `anthropic`, `pydantic`, `pyyaml`, see `pyproject.toml`.)
- No MESS binary or Slurm needed: unit tests that touch the queue or partition checks patch those calls (e.g. `QueueingSystem.get_all_running`, `sinfo`) instead of running them (the CI workflow comment states MESS-dependent tests are excluded from `tests/unit/`).

## Steps

1. From the repository root, run the same suite the hooks run:
   ```bash
   python -m pytest tests/unit/ -q
   ```
2. Narrow down when something fails:
   ```bash
   python -m pytest tests/unit/test_<subject>_ci.py -q
   python -m pytest tests/unit/ -q -k "<expression>"
   python -m pytest tests/unit/ -q -x          # stop at first failure
   ```
3. Run the hook runner exactly as git does:
   ```bash
   ./hooks/run_tests.sh
   KIMECO_HOOK_TESTS=tests/unit/test_<subject>_ci.py ./hooks/run_tests.sh
   ```
   `hooks/run_tests.sh` uses `TEST_PATH=${KIMECO_HOOK_TESTS:-tests/unit/}`, `cd`s to the repo root, and runs `conda run -n game python -m pytest` if a conda env named `game` exists, else `python -m pytest`.
4. Install the hooks (they are not installed automatically):
   ```bash
   git config core.hooksPath hooks
   ```
   `hooks/pre-commit` and `hooks/pre-push` both `exec hooks/run_tests.sh`.
5. Reproduce CI:
   - **GitHub Actions** (`.github/workflows/tests.yml`): Python 3.10, 3.11, 3.12 matrix; `pip install -e .[test,agentic]`; `pytest tests/unit/ -v`.
   - **GitLab** (`.gitlab-ci.yml`): mamba env with Python 3.10, `mamba install --file requirements.txt setuptools wheel`, `pip install --no-build-isolation --no-deps -e .`; smoke checks (import `kimeco` and deps, `kmo --help`, `kmoui --help`, GUI module imports, `kmopp --help`); then `pytest tests/unit/ -v`; then `pytest tests/examples/ -v`, where exit code 5 (no tests collected) is tolerated.

## Key files

- `hooks/run_tests.sh`, `hooks/pre-commit`, `hooks/pre-push`
- `.github/workflows/tests.yml`, `.gitlab-ci.yml`
- `pyproject.toml` (`[project.optional-dependencies]`), `requirements.txt`
- `tests/unit/` (files named `test_<subject>_ci.py`)

## Checks & pitfalls

- **Collection error in `tests/unit/test_agentic_pipeline_ci.py`** (e.g. `ModuleNotFoundError: anthropic`/`yaml`/`pydantic`) means the `agentic` extra is missing: `pip install -e .[agentic]`. Note the GitLab job installs `requirements.txt` only, which does not include these packages.
- If the `game` env exists but is stale, the hook runs tests there, not in your active env — compare with `python -m pytest` directly.
- Never bypass hooks with `--no-verify`, never skip, delete, or weaken tests to get green. Report failures (test name, assertion, traceback head) to the orchestrator so `ci-test` or `planning` can act.
- `tests/examples/` and `tests/parse_pes/` may need MESS/cluster resources; they are not part of the hook/CI unit run.

## Lane

Operational: running tests changes no tracked file. Pytest may create `.pytest_cache/` and `__pycache__/`; `.pytest_cache/` is not gitignored, so check `git status --short` afterwards and do not commit it.
