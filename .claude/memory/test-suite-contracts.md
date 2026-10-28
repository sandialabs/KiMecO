---
name: test-suite-contracts
description: "Which CI, packaging and skill contracts the unit tests enforce, which pins nothing enforces, and what breaks when a test file, a dependency of the test extra or a CI command changes. Read before editing tests/unit/, tests.yml, the test extra or the add-dependency/run-tests skills."
type: project
verified: 2026-10-27 against working tree
---
**Contracts encoded in tests (edit them in the same change as the thing they pin)**
- `tests/unit/test_installation_metadata_ci.py` parses `.github/workflows/tests.yml`: exact job set
  `{"test","test-automech-extra","test-mess-binary"}`, the literal `pytest tests/unit/ -v` (a
  `re.search`, so a suffix such as `--cov=kimeco` passes, a prefix does not), the `test-mess-binary`
  step order, a line ending in `pip install -e .[test]`. Also: `EXPECTED_EXTRAS = {"test","automech"}`,
  `requirements.txt` ⊆ dependencies + `test` extra, setup.py lists identical to pyproject (same
  strings, same order), `FORBIDDEN_TOKENS = ("anthropic","pydantic","agentic")` in packaging files.
- `tests/unit/test_installation_extras_ci.py`: `ALWAYS_REQUIRED_GROUPS = {"base","test"}`, so every
  `test`-extra package is a *failing* (not skipping) case of `test_declared_dependency_imports`, one
  case per module in `DIST_TO_MODULES`. A new test-extra package must therefore also reach
  `requirements.txt` (GitLab `installation`/`unit_tests` and `kmo_install_test.sh` install from it,
  then `pip install --no-deps -e .`) and every local env the git hook picks, or they go red.
- Skills quote assertion messages verbatim: "differs from pyproject", "pinned to several refs",
  "outside dependencies+test" (metadata test) and "DIST_TO_MODULES maps" (extras test), quoted in
  `.claude/skills/add-dependency/SKILL.md` (description) and `.claude/skills/run-tests/SKILL.md`.

- `test_installation_imports_ci.py::AUTOMECH_MODULES` includes `mechanalyzer`: no KiMecO module may
  import it at module level (it is imported lazily in `KMOInput._check_prompt`, prompt mode only;
  it is in no extra, not on PyPI). CI (`tests.yml`) pre-installs `mechanalyzer@0.2026.1` and
  `autofile@0.2025.0` from GitHub; `test_installation_extras_ci.py` has a real-guard test: its AST part (the
  probed `mechanalyzer.builder` symbol) runs everywhere, its import part skips when mechanalyzer is
  absent and fails under `KIMECO_REQUIRE_EXTRAS=automech`.

**Pins nothing enforces (check by hand)**
- `.github/workflows/tests.yml` runs `KIMECO_RUN_INSTALL_TEST=1 pytest
  tests/unit/test_installation_imports_ci.py -q -k editable_install`. Renaming that file or
  `test_editable_install_in_fresh_venv` collects nothing: exit 5, red CI. The fresh-interpreter
  checks in that file share the module-scoped, non-autouse fixture `fresh_runs` (commands run
  concurrently), so `-k editable_install` starts none of them.
- `test_no_source_references_agentic_pipeline_or_anthropic` (imports test) scans all
  `tests/**/*.py` and skips only its own file via `__file__`: the forbidden literals must stay there.
- `.claude/**` is outside every check: pytest's default `norecursedirs` skips dot-directories, CI
  and the hooks run only `tests/unit` (plus `tests/examples` on GitLab), the forbidden-pattern scan
  covers only `kimeco/` and `tests/`, and setuptools discovery skips directories with a `.` in their
  name (`setuptools/discovery.py`). A script shipped in a skill (e.g.
  `relabel-mess-by-structure/relabel_mess.py`) is never tested, linted or packaged.
- `tests/__init__.py`, `tests/unit/__init__.py`, `tests/examples/__init__.py` are required: two
  `test_mess_io_multi_input.py` share a basename, and
  `from tests.unit.test_installation_extras_ci import import_or_skip` is used by other test files.

**Golden writer outputs** (`tests/unit/data/mess_writer_golden/`): raw bytes written by the code
before multi-PES parsing (ethyl example, DME pair). `test_mess_multi_pes_write_ci.py::
test_single_file_and_dme_outputs_match_goldens` applies an explicit delta (`_golden_with_dme_delta`,
payload pops): a later writer change updates that delta, never regenerates the files.
`test_golden_folder_hygiene` forbids `.py` files there (pytest collection and the forbidden-literal
scan of `tests/**/*.py`). `tests/unit/data/s_golden/` is an unrelated empty untracked folder.

**Packaging side effects**
- `python setup.py -q egg_info` writes only `kimeco.egg-info/`; it also refreshes `PKG-INFO`'s README
  text and `SOURCES.txt` (which lists `tests/**`, since `find_packages()` packages `tests/`).
- From the repo root, `importlib.metadata.distribution("kimeco")` reads the tracked
  `kimeco.egg-info` (cwd is on `sys.path`); elsewhere it reads the installed dist-info, which only
  `pip install -e .` refreshes. `test_installed_metadata_extras_and_python_floor` checks only the
  extra names and `Requires-Python`, so adding a package to an extra needs no reinstall.

**Why:** these contracts are spread over three test files, CI YAML and two skills; breaking one
shows up as an unrelated-looking red test, or (for the `-k editable_install` pin) only in CI.
**How to apply:** before merging, renaming or deleting a test, or changing the test extra or a CI
command, check this list; use the `add-dependency` skill for dependency edits.

Sources: `tests/unit/test_installation_metadata_ci.py::test_tests_yml_has_mess_binary_job`,
`::EXPECTED_EXTRAS`, `::FORBIDDEN_TOKENS`, `::test_requirements_txt_is_subset_of_dependencies_and_test_extra`;
`tests/unit/test_installation_extras_ci.py::ALWAYS_REQUIRED_GROUPS`, `::DIST_TO_MODULES`;
`tests/unit/test_installation_imports_ci.py::fresh_runs`; `.github/workflows/tests.yml`.
Related: [[coverage-and-complexity-measurement]].
