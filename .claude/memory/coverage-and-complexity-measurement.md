---
name: coverage-and-complexity-measurement
description: "How to measure kimeco/ line coverage and Radon cyclomatic complexity, what --cov cannot see, how to get per-test and per-function coverage, and where the suite's runtime goes. Read before pruning, merging or adding tests, or when ranking untested complex functions."
type: project
verified: 2026-10-22 against working tree
---
**Tools** (in the `test` extra: `pytest-cov>=7.1.0`, `radon>=6.0.1`; coverage is off in CI, hooks
and pytest config, see the run-tests skill step 6)
- `python -m pytest tests/unit/ --cov=kimeco`; `radon cc kimeco -s` (score per function);
  `radon cc kimeco -s -n C` lists exactly CC ≥ 11. Ranks: A 1–5, B 6–10, C 11–20, D 21–30,
  E 31–40, F 41+. `radon cc kimeco -j -s` gives JSON with `lineno`/`endline` per block.
- `import radon` loads neither mando nor colorama; only `radon.cli` does (hence the import check
  maps `"radon": ("radon", "radon.cli")`).

**What `--cov=kimeco` does not count** (a low figure is not proof a module is untested)
- Subprocesses: pytest-cov 7 removed its `.pth` subprocess hook; re-enabling needs coverage's
  `[run] patch = subprocess`, and the repo has no coverage config. So the fresh-interpreter and
  fresh-venv installation tests add nothing.
- The automech driver script that `writers/automech_kin.py` emits and the tests load from
  `tmp_path` with importlib (it is not under `kimeco/`).
- Tests that only read source text or the AST (e.g. `test_save_load_output_arity_ci.py`,
  `test_kmoui_wiring.py`).

**Per-test and per-function coverage**
- `--cov-context=test` records which test ran each line. Lines run while pytest imports test
  modules (collection) sit under the empty context and belong to no test: a test file with zero
  attributed lines can still be the only importer of a module.
- The context DB stores executed *lines*, not statements; to compare with the report, map them
  through `coverage.python.PythonParser(filename).statements`.
- Join with Radon by line range (`lineno..endline`) and the JSON report's `executed_lines`/
  `missing_lines` to rank functions by CC × untested. The `def` line always counts as executed, so a
  few % coverage means the body never runs.
- Removing several overlapping tests together can lose lines that none of them covers alone:
  re-measure the total after each removal set.

**Runtime**
- After the 2026-10-22 consolidation: 316 tests, about 14.6 s, coverage 68.92 % (6068/8804).
- The first in-process `import mess_io` costs about 3–4 s cold (mostly `mess_io.writer`), paid once
  per pytest session by whichever test imports it first: deleting that test moves the cost, it does
  not save it.
- Statistical sampling tests are seeded (`SEED`). Their tolerances are sized for N = 10 000 draws.

**Why:** line coverage alone misjudges test value here, and the tools' blind spots are easy to miss.
**How to apply:** when choosing what to test next, rank by Radon CC and untested body; when pruning,
check the blind spots above before trusting "no unique line".

Sources: pytest-cov 7.1.0 `METADATA` changelog ("Dropped support for subprocesses measurement");
`radon cc --help` (6.0.1); `python -X importtime -c "import mess_io"`;
`tests/unit/test_automech_driver_ci.py::_load_driver`. Related: [[test-suite-contracts]].
