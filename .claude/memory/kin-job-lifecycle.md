---
name: kin-job-lifecycle
description: "How a kin job moves through QueueingSystem and RateCo (submit, squeue polling, recover before pick-up, the only path to clean_files), how errors stop kmo, the stuck-in-SOP defect, Slurm afterok semantics and the log-name globs. Read before changing q_sys.py, RateCo's status flow, adding a job type, or debugging a run that waits forever."
type: project
verified: 2026-11-02 against 4efa377 + steps 3-4 working tree
---
**Flow.** One Slurm array per model (`templates/slurm_arr.py`, `--array=0-{n_pes-1}`);
`QueueingSystem.submit` stores the array master id in `kin_q['sub_id']` (prompt mode: the collector
id in `collector_id`, see [[prompt-branching-fractions]] §4). `actualize` marks FINISHED when the
id(s) left `squeue --format=%F` (a pending job is listed). `RateCo.recover_rslts` reads every
`.out` **before** calling `pickUp`; `pickUp` → `_pickup_kin` → `clean_files` is the only path that
deletes files (kin `pickUp` is called only from `recover_rslts`). `actualize` turns PICKED_UP and
FAILED into NOT_IN_QUEUE in the same `run()`, so FAILED is no durable marker. `kin_q` lives in
memory only: after a restart `set_status` sees NOT_IN_QUEUE and `q_up` resubmits, while orphans of
the old process may still run (nothing calls `scancel`; there is no `atexit`).

**Known defect (unfixed):** when a `.out` stays missing, `recover_rslts` returns `[]` after 20 s
without `pickUp`; the job stays FINISHED, `Model.save_kin` resets only when rows are empty **and**
the status is FAILED, so the model waits in SOP forever and is never resubmitted. A FAILED job
that still produced rows moves to KIN silently.

**Prompt-mode restart (step 4, uncommitted).** `RateCo.set_status` returns FINISHED only with the
`.out` files, the prompt-rates JSON and a full `is_in_db` (thermal rows and `__prompt` rows per cell,
see [[kin-units-and-row-ids]]); a KIN_DB lacking the prompt rows gets the model resubmitted. In every mode a job found FINISHED at restart is re-read from disk
(`set_status` → `save_kin` → `recover_rslts`), so every file `recover_rslts` reads must survive
cleanup; only the kmopp reuse branch (`core.py`, empty `missing_grid`) skips that.

**Stopping kmo.** An exception in a model worker reaches `core.py` (`future.result()`), is logged
with `klog.error(..., exc_info=True)` and ends in `sys.exit(-1)`; `qs.run()` sits outside that
try, so an exception from `submit`/`actualize` gives a bare traceback. Raise from `RateCo`
(`set_status`/`recover_rslts`), not from the queue. The NM swarm catches exceptions per NM thread
(see [[optimizer-tables-and-nm-swarm]]).

**Slurm `afterok` on an array id** waits for every task to exit 0; if one exits non-zero the
dependent job stays PENDING (DependencyNeverSatisfied) forever unless `--kill-on-invalid-dep=yes`
or `kill_invalid_depend` is set, and the `squeue` poll never sees it end. A per-PES driver exits 0
even when MESS failed (`_run_mess` `check=False`), so a dependent job must check its inputs.

**Log-name globs.** `_pickup_kin` waits for and checks `logs/{name}_*.err` (array logs
`logs/{filename}_%a.err`); `templates/slurm.py` writes `logs/{filename}.err`, so any extra job named
`{name}_...` would be counted. `{name}P*` (`.out/.py/.inp/.log/.aux`) and `{name}S*` (SIM) are taken
too. The empty `--exclude=` line is removed only from `slurmtpl`, not from the array template.
`JobStatus` is defined in `q_sys.py` (not `enums.py`).

**Why:** these interactions are spread over five files and cost a long scope pass in step 3 of the
prompt-reactions work.
**How to apply:** keep new job files out of the globs above; make "finished" wait for every
dependent job before `clean_files` can run.

Sources: `kimeco/q_sys.py` (`submit`, `actualize`, `get_all_running`, `pickUp`, `_pickup_kin`,
`clean_files`, `__init__`); `kimeco/rate_coef.py::RateCo.set_status`, `recover_rslts`;
`kimeco/model.py::Model.save_kin`; `kimeco/core.py` (worker loop); `kimeco/writers/automech_kin.py`
(`_run_mess`); Slurm `man sbatch` (`--dependency`, `--kill-on-invalid-dep`).
