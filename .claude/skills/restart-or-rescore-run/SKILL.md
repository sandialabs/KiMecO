---
name: restart-or-rescore-run
description: "Restart an interrupted KiMecO run or rescore an existing one from its databases. Use when a run crashed, hit walltime, or was cancelled and should continue; when scores must be recomputed after changing experiments or scoring settings (restart: \"rescore\"); when reusing a previous sensitivity analysis via SA_restart; or when diagnosing restart errors such as SOP_DB parameter or PES mismatches."
---
# Restart or rescore a run

## When to use

A run stopped (walltime, crash, `scancel`) and should continue, or existing models must be rescored without new MESS/Cantera calculations.

## Prerequisites

- The original launch directory, the same `input.json` (same `project_name`), and the run's `<workdir>` (`<launch dir>/<project_name>`) containing:
  `KMO_DB_SOP.db`, `KMO_DB_KIN.db`, `KMO_DB_SIM.db`, `SA_DB_SOP.db`, `SA_DB_KIN.db`, `SA_DB_SIM.db`, `goats.txt`, `score_info.txt`.

## Choose the path

| Situation | Action |
| --- | --- |
| Run interrupted, inputs unchanged | Plain restart, same `project_name` |
| Scoring settings or weights changed; keep existing models | Rescore (`"restart": "rescore"`), after a DB backup |
| `mess_inputs` order/content, SOP parameters, `n_mdl`, or `fixed_params` changed | New `project_name` (fresh run) |
| Reuse a known parameter selection at a given generation | `SA_restart` in a plain restart |

## Steps — plain restart (`"restart": "default"`)

1. Make sure no job of the old run is still running (`squeue -u $USER`). Cancelling leftovers with `scancel` needs explicit user approval.
2. Re-launch **from the same directory** with the **same `project_name`** (via `submit-hpc-job`):
   ```bash
   sbatch submit_kmo.slurm      # which runs: kmo input.json
   ```
3. What happens (GA, `kimeco/optimizers/GeneticAlgo/ga.py`):
   - a generation `G####` is reused when its table exists in all three `KMO_DB_*` databases with identical model ids; its models are reloaded and scored;
   - the first generation that is not complete is wiped from the three DBs and regenerated;
   - the sensitivity analysis is read back from the `SA_DB_*` databases when present (`Linear.SA_is_in_db`);
   - a non-empty `active_p` skips the **initial** sensitivity analysis;
   - `SA_restart` (`{"<gen>": ["param", ...]}`) supplies the parameter list for an on-the-fly SA at that generation instead of running it.
4. `KiMecO.log` from the previous run is renamed with a timestamp suffix when the new run starts logging.

## Steps — rescore only (`"restart": "rescore"`)

1. **Back up the databases first** (scores are overwritten):
   ```bash
   mkdir -p <backup> && cp <workdir>/KMO_DB_*.db <workdir>/SA_DB_*.db <workdir>/goats.txt <workdir>/score_info.txt <backup>/
   ```
2. Set `"restart": "rescore"` in `input.json` (parsed into `RestartType.RESCORE`), change the scoring settings as needed, and launch as above. Rescoring reuses the simulation profiles stored in `KMO_DB_SIM.db`; whether editing the experiment data/error files (same conditions) or the experiment list itself is handled correctly was not traced — **unverified**, check `kimeco/scoring_f/` and `kimeco/core.py` first.
3. Existing generations are rescored with no new calculations. When the optimizer reaches a generation that is not in the DB it raises
   `TypeError('Rescoring only but next generation not in DB.')` (`ga.py`, around lines 279 and 358). That is the **expected end** of a rescore, not a failure.
4. Set `"restart"` back to `"default"` before continuing the optimization.

## Key files

- `kimeco/optimizers/GeneticAlgo/ga.py` (`is_generation_finished`, `get_gen_one`, `get_next_gen`, `run_sensitivity`)
- `kimeco/sensitivity/linear.py`, `kimeco/database/sop_db.py`, `kimeco/goat.py`, `kimeco/logger_config.py`
- `wiki/Additional-Global-Keywords.md` (`restart`), `wiki/Sensitivity-Analysis.md`, `wiki/Outputs.md`

## Checks & pitfalls

- `SOP_DB ... contains an item/PES_ID mapping that does not match the current input` (`ValueError`) → `mess_inputs` order or content changed. Restore the original list/order, or start a new `project_name`.
- Changing `n_mdl`, `fixed_params`, the set of SOP parameters/PESs, or the `mess_inputs` order makes the stored generations unusable: a generation with fewer models than `n_mdl` is wiped and regenerated. Use a new `project_name` instead.
- `score_info.txt` is rewritten with a fresh header when the GOAT tracker is created with `overwrite=True` (`goat.py`); keep a copy if you need the old history.
- Nelder-Mead restart: `NelderMead.restart_simplex()` exists (`kimeco/optimizers/NelderMead/nelder_mead.py`) but its restart behaviour was not traced for this skill — **unverified**; read the code before promising a resume.
- Never delete or edit the `.db` files by hand without a backup and user approval.

## Lane

Operational if the run directory is outside the repository or under `dev_tests/`. Submission itself follows `submit-hpc-job`.
