---
name: add-dependency
description: "Add, remove, or re-pin a KiMecO Python dependency (base dependencies, the test extra, or the automech extra) in lockstep across every file that declares it, so pyproject.toml, setup.py, requirements.txt, meta.yaml, the tracked kimeco.egg-info, the CI git pre-installs, the install docs and the dependency-checking tests all agree. Use when adding a package to pyproject.toml or setup.py, bumping or relaxing a version bound, changing the git tag of an Auto-Mech package (autoio, autochem, autofile, mechanalyzer), adding an extra, or when a test fails with \"extras_require[...] in setup.py differs from pyproject\", \"DIST_TO_MODULES maps\", \"requirements.txt lists packages outside dependencies+test\", \"pinned to several refs\", or a ModuleNotFoundError after pip install -e .[automech]."
---

# Add a dependency

## When to use

- Add, remove, bump, or relax a requirement in a group: base (`[project] dependencies`), `test`, or `automech`.
- Change the git tag of an Auto-Mech package that is not on PyPI.
- Add a new extra: also step 4, last bullet. It is a larger change because several tests hard-code `{"test", "automech"}`.
- Not for: KiMecO's own version (`cut-release`), the `mess-static` package (`build-mess-conda-package`), or installing an environment (`install-kimeco-env`).

## Prerequisites

- An environment with Python 3.11 or later, KiMecO installed editable, and `pytest` (for example the `kimeco` conda env that `hooks/run_tests.sh` selects). Python 3.10 skips all of `tests/unit/test_installation_metadata_ci.py` (it needs `tomllib`), so a run there looks green when it is not.
- Choose the group:
  - **base**: KiMecO always needs the package.
  - **`automech`**: needed only with `use_automech=true`, and imported lazily.
  - **`test`**: needed only by pytest.
  - **CI pre-install only**: a package that only CI fixtures or tests need and that is not on PyPI. Do not put it in an extra.

## Source of truth

`pyproject.toml` decides what pip installs. When `[project]` declares the lists, setuptools ignores those in `setup.py` (`SetuptoolsWarning: extras_require overwritten in pyproject.toml`). `setup.py` is a mirror. Editing only `setup.py` changes nothing for users and fails `test_setup_py_extras_mirror_pyproject` (commit `abf684f`).

## Steps

1. **`pyproject.toml`**: edit `dependencies` or `optional-dependencies.<extra>` first.
   - Write a valid PEP 508 string.
   - Every `automech` entry needs a `>=` lower bound.
   - No canonical name may appear twice in a group.
2. **`setup.py`**: copy the change exactly.
   - `dependencies` goes to `install_requires`, and `optional-dependencies.<extra>` goes to `extras_require["<extra>"]`.
   - Use the same string and the same position. The tests compare whole lists with `==`, so `autochem<2.0.0,>=0.2025.0` fails even though it means the same thing.
3. **Base group only**:
   - Add the package to `requirements.txt`. Docs, `.gitlab-ci.yml` and `kmo_install_test.sh` all use it through `mamba install --file`. It must stay a subset of base plus `test`. Check that the conda-forge package name is the same (unverified per package).
   - Add it to `meta.yaml` `requirements: run` as `- name >=x.y`. No test checks `meta.yaml`, and it already lacks `pyarrow >=14`.
   - Optionally add its import to the smoke-test imports in `.gitlab-ci.yml` and `kmo_install_test.sh`.
4. **Tests that pin the lists** (the `ci-test` agent owns these files):
   - `tests/unit/test_installation_metadata_ci.py`: `EXPECTED_AUTOMECH` must list exactly what `pyproject.toml` lists, in the same order.
   - `tests/unit/test_installation_extras_ci.py`: in `DIST_TO_MODULES[<group>]`, map the distribution name to the module(s) it imports (`pyyaml` to `yaml`, `py3dmol` to `py3Dmol`). This is needed for every group, or `test_dist_to_module_map_covers_pyproject_exactly` fails.
   - If KiMecO code imports an `automech` package, add its top-level modules to `AUTOMECH_MODULES` in `tests/unit/test_installation_imports_ci.py`.
   - New `mess_io.writer` symbols imported by `KMOInput._check_automech` go into `GATE_WRITER_SYMBOLS`.
   - New extra: also update `EXPECTED_EXTRAS`, `KNOWN_EXTRAS`, the `['automech', 'test']` line in `test_editable_install_in_fresh_venv`, and the jobs in `tests.yml`.
5. **Packages not on PyPI** (Auto-Mech): pip cannot fetch them through the extra.
   - Pre-install from git in **both** `.github/workflows/tests.yml` jobs (`test-automech-extra`, `test-mess-binary`), with the same `@<tag>`. Add the module to their "Verify the documented automech imports" line if CI should check it.
   - Changing the `autoio` or `autochem` tag: update every `git+` line in `README.md`, `MANUAL.md` and `wiki/Installation-from-Source.md` (the §6 block and the fresh-environment recipe). `test_docs_and_ci_pin_same_autoio_autochem_refs` allows one tag only, across the docs and CI.
   - `GIT_PREINSTALL_RE` matches exactly the two-package `autoio` + `autochem` line. Adding a third package to the documented line also requires updating that regex and `_git_pins`.
   - Keep the extra's lower bound at or below the git tag, ideally equal.
6. **Code**: never import an `automech` package at the top of a `kimeco` module. Use the patterns already in the code: the imports inside the emitted driver string (`automech_kin_tpl` in `kimeco/writers/automech_kin.py`) and the lazy imports in `KMOInput._check_automech` (`kimeco/user_input.py`).
7. **Docs**: if the user-visible install changes (new pre-install, new extra, new group), update `MANUAL.md` and `wiki/Installation-from-Source.md` together, and `README.md`. MANUAL and the wiki must keep identical §5 text and identical recipe blocks.
8. **`kimeco.egg-info/`** is tracked by git. Regenerate it from the repo root, then reinstall so the installed metadata matches:
   ```bash
   conda run -n kimeco python setup.py -q egg_info
   git diff kimeco.egg-info/requires.txt kimeco.egg-info/PKG-INFO
   conda run -n kimeco pip install -e .[test]   # or .[automech,test]
   ```
   Keep only the dependency changes and review any other diff before committing.
9. **`CHANGELOG.md`**: add a bullet under `## Unreleased` (`### Added`, `### Changed` or `### Removed`) naming the package, its group and its bound or tag.
10. **Verify**:
    ```bash
    rg -n '<pkg>' pyproject.toml setup.py requirements.txt meta.yaml kimeco.egg-info/requires.txt \
       tests/unit/test_installation_*_ci.py .github/workflows/tests.yml README.md MANUAL.md wiki/Installation-from-Source.md
    conda run -n kimeco python -m pytest -q tests/unit/test_installation_metadata_ci.py \
       tests/unit/test_installation_extras_ci.py tests/unit/test_installation_imports_ci.py
    ./hooks/run_tests.sh                     # full tests/unit/, Python >= 3.11 env
    # automech group, in an env that has the extra (CI turns skips into failures the same way):
    KIMECO_REQUIRE_EXTRAS=automech,test conda run -n automech python -m pytest -q tests/unit/test_installation_extras_ci.py
    ```

## Lockstep checklist

| What | When | Checked by |
| --- | --- | --- |
| `pyproject.toml` | always | metadata and extras tests |
| `setup.py` (same strings, same order) | always | `test_setup_py_extras_mirror_pyproject` (extras and `install_requires`) |
| `requirements.txt` | base, `test` | `test_requirements_txt_is_subset_of_dependencies_and_test_extra` |
| `meta.yaml` `run:` | base | nothing (review by hand) |
| `EXPECTED_AUTOMECH` | `automech` | `test_pyproject_automech_extra_exact_list` |
| `DIST_TO_MODULES` | every group | `test_dist_to_module_map_covers_pyproject_exactly` |
| `AUTOMECH_MODULES` | `automech` package imported by KiMecO | `test_all_public_modules_import_without_automech_extra` |
| `tests.yml` git pre-installs | packages not on PyPI | `test_docs_and_ci_pin_same_autoio_autochem_refs` (autoio and autochem only) |
| README, MANUAL, wiki `git+` lines | `autoio`/`autochem` tag | recipe and pin tests |
| `kimeco.egg-info/` | always | not checked locally; CI checks extras |
| `CHANGELOG.md` | always | none |

## Checks & pitfalls

- Never edit one file alone. Every row of the checklist that applies changes in the same commit.
- Never weaken, skip or delete a test to make it pass. Update the expected lists instead.
- Upstream releases can add imports: `autoio` already pulls in `IPython` and `py3Dmol` (`test_mess_io_transitive_dependencies_are_declared`). After a tag bump, run `python -c "import mess_io, phydat, kimeco"` in a fresh environment.
- A package only CI fixtures need (for example `mechanalyzer` for future NB tests) is a CI pre-install, not an extra. If it later moves into an extra, follow every step above.

## Key files

`pyproject.toml`, `setup.py`, `requirements.txt`, `meta.yaml`, `conda_build_config.yaml`, `kimeco.egg-info/`, `.github/workflows/tests.yml`, `.gitlab-ci.yml`, `kmo_install_test.sh`, `hooks/run_tests.sh`, `README.md`, `MANUAL.md`, `wiki/Installation-from-Source.md`, `kimeco/user_input.py` (`_check_automech`), `kimeco/writers/automech_kin.py`, `tests/unit/test_installation_metadata_ci.py`, `tests/unit/test_installation_extras_ci.py`, `tests/unit/test_installation_imports_ci.py`.

## Lane

Pipeline: the skill edits tracked files. Run Stages 1-7. The `ci-test` agent owns the test edits and `version-control` owns `CHANGELOG.md` and the docs.
