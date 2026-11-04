---
name: unit-test-stand-ins
description: "How to test heavy KiMecO pieces (GA/NM runs, CoreRun, Dash callbacks, plotting, DBs) fast and in-process, the global state that leaks between tests, and how to prove a fix test fails on the old code. Read before writing tests for optimizers, CoreRun subclasses or GUI callbacks."
type: project
verified: 2026-11-03 against working tree
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
`kimeco.__file__`). This works because setuptools' editable finder is appended to
`sys.meta_path` (`__editable___kimeco_*_finder.py`), after the path finder: keep the scratch root
free of an `__init__.py` so `kimeco/` there is found first.
If the new tests import names HEAD lacks (e.g. `MessTemplate`), every file fails at collection,
which proves nothing per test: append import-only shims (the names, no behaviour) to the scratch
HEAD copy to get a per-test verdict (step 1 of multi-pes-mess-parsing: 93/100 new cases failed).
Copy `example/` too: `test_mess_multi_pes_write_ci.py` reads `REPO / 'example'` for the golden
test, which otherwise fails with FileNotFoundError (not a verdict).
Hindered-rotor scans are `np.float32` (`kimeco/rotors/hrotor.py::HinRotor.scan`): compare parsed
potentials with `pytest.approx`, never with `==`.
To switch off one rule of the current code instead, with no copy of `kimeco/`: a scratch plugin
(`-p <plugin>`, on `PYTHONPATH`) takes `inspect.getsource` of the method, replaces the one line,
`exec`s it with the module's `__dict__` as globals and patches the class. Add
`-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1`. It follows the real source, unlike a copied
body: with the one-well-per-PES rule off, exactly the 24 stop cases failed.

**MESS reader stop messages** (`tests/unit/test_mess_multi_pes_read_ci.py`): `assert_one_stop`
counts only the messages holding every needle, so it misses extra stops: use `only_stop` to prove
one message in all. `stop_messages` is warnings plus errors, and `validate_species` warns on an
unknown species even with `force_new_molecules` on, when the read does not stop.

**Long `--basetemp`** breaks `tests/unit/test_q_sys_ci.py`: 9 failed at 93 characters, all 47
errored at 136 and 227, the default passes 47 (2026-11-03). Likely cause: `QueueingSystem.jobdata`
keeps `loc` in 150 characters, so longer job paths are cut. Keep the default.

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
`kimeco/database/sop_db.py::SOP_DB.__init__`; scratch run printing `kimeco.__file__` (2026-10-22);
`kimeco/q_sys.py::QueueingSystem.__init__` (`jobdata`).
Related: [[coverage-and-complexity-measurement]], [[test-suite-contracts]],
[[optimizer-tables-and-nm-swarm]].
