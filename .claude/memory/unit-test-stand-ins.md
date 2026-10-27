---
name: unit-test-stand-ins
description: "How to test heavy KiMecO pieces (GA/NM runs, CoreRun, Dash callbacks, plotting, DBs) fast and in-process, the global state that leaks between tests, and how to prove a fix test fails on the old code. Read before writing tests for optimizers, CoreRun subclasses or GUI callbacks."
type: project
verified: 2026-10-26 against working tree
---
**Global state that leaks between tests**
- `Generation.total()` is a class-level counter (name-mangled `__id`) of every `Generation` built
  in the process. GA `get_gen_one`/`get_next_gen`/`run`/`stop_run` and
  `NelderMead.objective_function` read it, so tests patch `Generation.total` (or `ga.Generation`,
  `nelder_mead.Generation` with a fake class).
- `CoreRun.__init__` ends with `os.chdir(base_path)`: build it only after
  `monkeypatch.chdir(tmp_path)`. Its default `prefix='C'` names tables, folders and the stale-file
  cleanup `C####`; pass `prefix='G'` to mimic a GA run.

**Fast stand-ins**
- Dash `@callback` functions in `kimeco/gui/input_sections/*` are plain module-level functions:
  call them directly and drive pattern-matched triggers with
  `monkeypatch.setattr(<module>, 'callback_context', SimpleNamespace(triggered_id=...))`.
  `_EXP_BROWSER` / `_SOP_BROWSER` are built at import, rooted at the cwd: replace them with
  `FileBrowserDropdown(root_dir=tmp_path)`.
- matplotlib is not a declared dependency (it comes in through ase) and only
  `TimeProfile.plot` imports it, lazily: stub it in `sys.modules` (set it to `None` to hit the
  ImportError path).
- `SOP_DB`, `KIN_DB` and `SIM_DB` load every existing table when they open, so a DB re-opened on a
  tmp file sees the tables written before. SQLite returns SOP-table rows in id order, so "first
  row" vs "row with id 0" can only be told apart with a table that lacks id 0.
- `Kimeco_db.upsert_entries` (all three DBs) catches every exception except "database is locked",
  logs it to `db.log` in the cwd, retries, then moves on to the next chunk: a failed write is
  silent. Tests and probes must read the values back (`kimeco/database/kimeco_db.py`).
- Heavy runs (GA `run`, NM objective functions, `Linear.run`) are tested by patching
  `Generation`/`CoreRun.run`; such tests prove control flow, not a real MESS/Cantera workflow.

**Proving a fix test fails on the old code (without touching the repo)**
Copy `kimeco/`, `tests/` and `pyproject.toml` to a scratch directory, replace the fixed files with
`git show HEAD:kimeco/<path>`, and run pytest from there. pytest puts that rootdir first on
`sys.path`, so the scratch `kimeco` shadows the editable install (check with a test printing
`kimeco.__file__`).
If the new tests import names HEAD lacks (e.g. `MessTemplate`), every file fails at collection,
which proves nothing per test: append import-only shims (the names, no behaviour) to the scratch
HEAD copy to get a per-test verdict (step 1 of multi-pes-mess-parsing: 93/100 new cases failed).

**Reusable helpers in other test modules** (`tests/unit/__init__.py` makes them importable as
`from tests.unit.test_<x> import …`; import only non-`test_*` names, or pytest collects those tests
again in the importing module): `test_perturbator_boundary_coverage_ci.py::_scripted_pert(select,
sop)` (scripted draws, no RNG); `test_automech_normal_parity_e2e_ci.py::_install_stubs` records the
`mess_io.writer.*` kwargs, but its `_driver` hard-codes `pes_id=0` (multi-PES tests define their own).

**Why:** without these, tests change the process cwd, depend on test order through the
Generation counter, or need a cluster, MESS or a display.
**How to apply:** reuse the helpers in the existing files (`test_ga_ci.py`, `test_core_ci.py`,
`test_goat_ci.py`, `test_experiments_gui_schema_ci.py`) before writing new stubs; seed both
`random` and `np.random`.

Sources: `kimeco/generation.py::Generation.total`; `kimeco/core.py::CoreRun.__init__`;
`kimeco/gui/input_sections/experiments_section.py` (`_EXP_BROWSER`), `sop_section.py`
(`_SOP_BROWSER`); `kimeco/experiments/t_profile.py::TimeProfile.plot`;
`kimeco/database/sop_db.py::SOP_DB.__init__`; scratch run printing `kimeco.__file__` (2026-10-22).
Related: [[coverage-and-complexity-measurement]], [[test-suite-contracts]],
[[optimizer-tables-and-nm-swarm]].
