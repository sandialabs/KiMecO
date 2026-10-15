---
name: install-kimeco-env
description: "Install or repair a KiMecO conda environment from source, including the MESS binaries and optional automech. Use when setting up KiMecO on a new workstation or cluster, recreating a broken environment, choosing a Python version, installing MESS so `which mess` works, enabling use_automech (mess_io/autoio), or verifying an install with the kmo, kmoui, kmopp and kmo_start smoke checks or kmo_install_test.sh."
---
# Install the KiMecO environment

## When to use

New workstation or cluster account, broken or outdated env, adding MESS or automech, or verifying an install.

## Prerequisites

- `conda` (and optionally `mamba`) on `PATH`; a clone of the repository.
- Python **3.10–3.12** (`requires-python = ">=3.10"`; CI tests 3.10, 3.11, 3.12; `kmo_install_test.sh`, `.gitlab-ci.yml`, and the wiki use 3.10). Avoid newer interpreters until they are added to the CI matrix.
- Pick an env name. Names used in the repo: `game` (preferred by `hooks/run_tests.sh`), `kimeco` (wiki), `kimeco-ci` (`kmo_install_test.sh`, GitLab).

## Steps

1. Create and activate the env:
   ```bash
   conda create -n <env> -c conda-forge python=3.10 pip -y
   conda activate <env>
   ```
2. Install dependencies and KiMecO (from the repo root). Conda-forge route (`wiki/Installation-from-Source.md`, `.gitlab-ci.yml`):
   ```bash
   conda install -c conda-forge mamba -y
   mamba install -c conda-forge --file requirements.txt -y
   pip install --no-build-isolation --no-deps -e .
   ```
   Pip-only route (as GitHub CI does), which also brings test and agentic extras:
   ```bash
   pip install -e .[test,agentic]
   ```
3. Install MESS (required for real runs). Either copy the static binaries from https://github.com/Auto-Mech/MESS into `$CONDA_PREFIX/bin` (wiki), or install the `mess-static` conda package built with `build-mess-conda-package`. Then:
   ```bash
   which mess
   ```
4. Optional automech (only for `use_automech: true`): install the Auto-Mech packages providing `mess_io` (the wiki points to https://github.com/Auto-Mech/autochem and related packages). `mess_io` must import in the launch env **and** on compute nodes, otherwise `_check_automech` cancels the run:
   ```bash
   python -c "from mess_io import well_lumped_input_file"
   ```
5. Smoke-check (mirrors `kmo_install_test.sh` / GitLab):
   ```bash
   python -c "import kimeco, ase, cantera, dash, numpy, pandas, plotly, scipy, sqlalchemy"
   kmo --help
   kmoui --help
   kmopp --help
   python -c "import kimeco.gui.kimecoapp, kimeco.gui.sopsection, kimeco.gui.kinsection, kimeco.gui.simsection, kimeco.gui.corsection"
   ```
   `kmo_start` has no `--help` smoke check in the repo; launching it starts a Dash server on port 8000 (`kmo_start [config.json]`).
6. Optional full scripted check:
   ```bash
   ENV_NAME=<throwaway-env> ./kmo_install_test.sh
   ```

## Key files

- `requirements.txt`, `pyproject.toml`, `setup.py`, `meta.yaml`
- `kmo_install_test.sh`, `.gitlab-ci.yml`, `.github/workflows/tests.yml`
- `wiki/Installation-from-Source.md`

## Checks & pitfalls

- **`kmo_install_test.sh` deletes the target env first** (`conda env remove -n "${ENV_NAME}"`, default `kimeco-ci`). Always set `ENV_NAME` explicitly to a throwaway name and confirm with the user before running it against an existing env. It also runs `pytest -q` over the whole `tests/` tree.
- On clusters, compute jobs need the same env: generated Slurm scripts do not activate conda, so the master job script must (see `submit-hpc-job`).
- `pip install -e .` without `--no-deps` can pull PyPI wheels over conda-forge builds; prefer the mamba route on clusters.
- The `kimeco.egg-info/` directory at the repo root is **git-tracked**; an editable install may rewrite files in it. Check `git status --short` after installing and do not commit incidental `kimeco.egg-info` changes without asking.

## Lane

Operational when the install leaves no tracked or new non-ignored files in the repo. If `git status` shows modified `kimeco.egg-info/*` files, report them to the user (restore with their approval) rather than committing them.
