---
name: postprocess-run-results
description: "Postprocess and inspect the results of a finished or running KiMecO run. Use when the user wants to extrapolate GOAT or generation ensembles to new conditions with kmopp (pp_experiments, pp_ensembles), open the kmoui dashboard to browse the SOP, KIN, SIM, correlation, and database tabs, export database tables, or reach the dashboard running on a cluster."
---
# Postprocess run results

## When to use

Extrapolating optimized ensembles to new (T, P, composition) conditions, or browsing a run's results in the `kmoui` dashboard.

## Prerequisites

- The original launch directory and `input.json` of the run, with `<workdir>` (`<launch dir>/<project_name>`) containing `KMO_DB_SOP.db`, `KMO_DB_KIN.db`, `KMO_DB_SIM.db`, and `goats.txt`.
- `kmoui` and `kmopp` call `KMOInput.full_run_settings`, so they need the same validation as `kmo`: a valid `q_name` and a working `sinfo`. Run them on a cluster login node (or a node where Slurm is available).

## Steps — extrapolate with `kmopp`

1. Add to `input.json` (see `wiki/Postprocessing.md`):
   - `pp_experiments`: same schema as `experiments` **without** `data_file`/`error_file`, plus `times` (non-empty, ascending, seconds) and `species` (non-empty list);
   - `pp_ensembles` (default `["G0001", "GT-1"]`). Tokens: `G####` (all models of a GA generation), `GT####` / `GT-1` (GOAT ensemble of a generation / the final one), `NM####` / `NM-#` (Nelder-Mead best model), `NMS` (Nelder-Mead Swarm; requires `NMS_start`). Stick to these documented tokens.
   Minimal block added to the existing `input.json` (based on `example/input.json`):
   ```json
   "pp_experiments": [
     {"temp": 700.0, "pres": 1.0, "pres_unit": "bar",
      "cantera_tpl": "concentration_time_isobar_adiabatic.tpl",
      "times": [0.0, 0.001, 0.002, 0.003],
      "species": ["C2H4", "CH3CH2OO"],
      "initial_ratio": {"C2H5": 4.26e-7, "O2": 0.1, "HE": "base"}}
   ],
   "pp_ensembles": ["GT-1"]
   ```
2. Run from the original launch directory (exactly one argument, or `-h`); it submits MESS and Cantera jobs, so use a batch script like `submit-hpc-job`:
   ```bash
   kmopp input.json
   ```
3. What it does (`kimeco/postprocessing/postprocess.py`): sets `postprocess=True`, writes `<workdir>/_kmopp_input.json` (the flagged copy used by simulation jobs), loads `goats.txt`, computes only the (P, T) cells missing from each model's KIN table, and appends results to **`KMO_DB_KIN.db` and `KMO_DB_SIM.db`** (no separate PP databases). Postprocessing simulations are stored with banded experiment ids offset past the original experiments, so original results are not overwritten. Progress is logged to `PostProcess.log` in the launch directory.

## Steps — browse with `kmoui`

1. From the original launch directory:
   ```bash
   kmoui input.json
   ```
   Dash serves on `http://127.0.0.1:8000`. Tabs: Set of parameters (SOP), Rate coefficients (KIN), Concentration profiles (SIM), Correlation plots (COR), Databases (DB). It needs table `G0000` in `KMO_DB_SOP.db` and `<workdir>/goats.txt`.
2. Databases tab: pick a `.db` file and a table, then use the copy button to copy it to the clipboard as tab-separated text (paste into a spreadsheet).
3. Remote cluster (suggestion, **unverified**, not documented in the repo): forward the port from your workstation, then open `http://127.0.0.1:8000` locally:
   ```bash
   ssh -L 8000:127.0.0.1:8000 <user>@<login-node>
   ```

## Key files

- `kimeco/postprocessing/postprocess.py`, `kimeco/postprocessing/extrapolate.py`
- `kimeco/gui/kimecoapp.py`, `kimeco/gui/dbsection.py`
- `wiki/Postprocessing.md`, `wiki/Outputs.md`

## Checks & pitfalls

- `kmo_start` also binds port 8000: do not run it and `kmoui` at the same time on the same host.
- `kmoui` also runs `copy_necessary_files` (rewrites `mess_tpl_PES{NN}` in `<workdir>`) and logs to `kmo_UI.log` in the launch directory.
- A token whose table is missing from `KMO_DB_SOP.db` makes `kmopp` fail; list tables in the `kmoui` Databases tab first.
- `pp_experiments` entries that define `data_file`/`error_file`, or unsorted `times`, cancel the run.
- Back up `<workdir>/KMO_DB_*.db` before a large postprocessing run; it appends into them.

## Lane

Operational if the run directory is outside the repository or under `dev_tests/`. Changing postprocessing or dashboard code is pipeline lane.
