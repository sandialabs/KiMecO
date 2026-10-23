---
name: run-tests
description: "Run the KiMecO automated test suite locally the same way the git hooks and CI do. Use when asked to run tests or pytest, check that a change passes before commit or push, reproduce a GitHub Actions or GitLab CI failure, install the repository git hooks, or investigate why a pre-commit or pre-push hook is failing. Only runs tests; designing and authoring new tests belongs to the ci-test agent."
---
# Run tests

## When to use

Running the existing suite before commit/push, reproducing a CI failure, installing or debugging the git hooks. Designing or writing tests is the `ci-test` agent's job, not this skill's.

## Prerequisites

- A Python 3.11 or 3.12 environment (the package floor is `>=3.11`) with KiMecO installed editable, plus the `test` extra:
  ```bash
  pip install -e .[test]            # or .[automech,test] to also run the automech-dependent cases
  ```
  `test` = `pytest>=9.0.2`, `pytest-cov>=7.1.0`, `radon>=6.0.1`. The only extras are `test` and `automech` (see `pyproject.toml`). Coverage is off in the hooks, in CI and in the pytest configuration: it runs only when you pass `--cov` yourself (step 6).
- Never validate in Python 3.10 (e.g. the `game` env). `tests/unit/test_installation_metadata_ci.py` skips at module level without `tomllib`, so a broken dependency mirror still looks green.
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
   `hooks/run_tests.sh` uses `TEST_PATH=${KIMECO_HOOK_TESTS:-tests/unit/}` and `cd`s to the repo root. It then picks the first usable conda env among `${KIMECO_HOOK_ENV}` (if set), `kmo`, `kimeco` and `automech`. An env is found with `conda env list`, or at `~/.conda/envs/<env>/bin/python`. It is usable when it has Python >= 3.11 and can import `pytest`. If none is usable, the hook uses the active `python` when that meets the same check, and otherwise exits 1. The first output line names the chosen env (`[git hook] Using conda env '<env>'`). Force one with `KIMECO_HOOK_ENV=<env> ./hooks/run_tests.sh`.
4. Install the hooks (they are not installed automatically):
   ```bash
   git config core.hooksPath hooks
   ```
   `hooks/pre-commit` and `hooks/pre-push` both `exec hooks/run_tests.sh`.
5. Reproduce CI:
   - **GitHub Actions** (`.github/workflows/tests.yml`) has three jobs, each on a Python 3.11 / 3.12 matrix and each running `pytest tests/unit/ -v`:
     - `test`: `pip install -e .[test]`, then the opt-in editable-install test (`KIMECO_RUN_INSTALL_TEST=1`).
     - `test-automech-extra`: GitHub pre-install of `autoio`/`autochem`/`autofile`/`mechanalyzer`, `pip install -e .[automech,test]`, and `KIMECO_REQUIRE_EXTRAS=automech,test`, which turns skips into failures.
     - `test-mess-binary`: a micromamba env with `mess-static`, plus `KIMECO_REQUIRE_MESS=1`.
   - **GitLab** (`.gitlab-ci.yml`): mamba env with Python 3.11, `mamba install --file requirements.txt setuptools wheel`, `pip install --no-build-isolation --no-deps -e .`; smoke checks (import `kimeco` and deps, `kmo --help`, `kmoui --help`, GUI module imports, `kmopp --help`); then `pytest tests/unit/ -v`; then `pytest tests/examples/ -v`, where exit code 5 (no tests collected) is tolerated.
6. Measure coverage and code complexity (local only: neither runs in the hooks or CI):
   ```bash
   python -m pytest tests/unit/ --cov=kimeco   # line coverage of kimeco/: one row per module, then TOTAL
   radon cc kimeco -s                          # cyclomatic complexity (CC) of every function, with its score
   radon cc kimeco -s -n C                     # only functions ranked C or worse, i.e. CC > 10
   ```
   Radon ranks a function by its CC (the number of independent paths through it): A 1–5, B 6–10, C 11–20, D 21–30, E 31–40, F 41+. Use it to see which complex branches deserve a test. `--cov` measures only code that runs inside the pytest process (pytest-cov 7 dropped subprocess measurement, and the repo has no coverage config to re-enable it). Tests that run KiMecO in a subprocess (fresh interpreter or venv checks), the automech driver script that KiMecO writes and then runs, and tests that only read source text add no coverage, so a low figure for a module does not by itself mean it is untested.

## Key files

- `hooks/run_tests.sh`, `hooks/pre-commit`, `hooks/pre-push`
- `.github/workflows/tests.yml`, `.gitlab-ci.yml`
- `pyproject.toml` (`[project.optional-dependencies]`), `requirements.txt`
- `tests/unit/` (files named `test_<subject>_ci.py`)

## Checks & pitfalls

- The hook may run in a different env than your active one (see step 3). If results differ, compare the hook's `Using conda env ...` line with `python -m pytest` in your env. The counts also differ between envs: an env without the `automech` extra skips those cases.
- `test_agentic_pipeline_folder_absent` / `test_agentic_pipeline_not_importable` failing means a leftover `agentic_pipeline/` folder holding only `__pycache__/` exists at the repo root. Checking out `main`, which still has the package, and running Python there creates it. Delete the folder (`rm -rf agentic_pipeline/`).
- A dependency-mirror failure (`extras_require[...] in setup.py differs from pyproject`, `DIST_TO_MODULES maps ...`) means a dependency was changed in one place only: follow the `add-dependency` skill.
- Never bypass hooks with `--no-verify`, never skip, delete, or weaken tests to get green. Report failures (test name, assertion, traceback head) to the orchestrator so `ci-test` or `planning` can act.
- `tests/examples/` and `tests/parse_pes/` may need MESS/cluster resources; they are not part of the hook/CI unit run.

## Lane

Operational: running tests changes no tracked file. Pytest may create `.pytest_cache/` and `__pycache__/`. Both are ignored: `.pytest_cache/` carries its own `.gitignore` written by pytest, and `**.pyc` is in the repo `.gitignore`. A coverage run (step 6) writes `.coverage`, and `htmlcov/` or `coverage.xml` with `--cov-report=html` or `--cov-report=xml`; all three are in the repo `.gitignore` too. A quick `git status --short` afterwards still confirms that nothing else changed.
