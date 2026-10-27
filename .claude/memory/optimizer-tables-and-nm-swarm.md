---
name: optimizer-tables-and-nm-swarm
description: "How the GA's SOP tables are laid out (G0000 vs G####), when G0000 gets written, how get_ensemble seeds the Nelder-Mead swarm (NMSG#### tables), how NMSRunner locks and collects models, and known unfixed optimizer defects. Read before touching the GA, NM or NM-swarm code, NMS_start, or postprocessing of G####/NMSG#### tables."
type: project
verified: 2026-10-26 against working tree
---
**GA table layout (SOP_DB)**
- `G0000` holds the initial model under id 0. It is written by `Linear.save_initial_model` only
  when the sensitivity analysis is not read from the DB, or `restart == RESCORE`
  (`KiMecO.set_important_parameters`); otherwise only by GA `gen_0`, and only if `f_mdl` is not
  DONE. `gen_0` still creates the table, so `G0000` can exist and be **empty**.
- `G####` from gen 1 hold only that generation's new models: gen 1 = `[f_mdl (gen 0)] + G0001`
  (ids 1..n_mdl-1). kmoui reads `G0000` row 0 as the initial values (`gui/kimecoapp.py`).

**Seeding the NM swarm (`NMS_start`)**
- `KiMecO.get_ensemble('G0001')` returns the `G0000` row with id 0 (rescored, id 0 / gen 0)
  followed by the `G0001` rows: n_mdl models with unique ids. It returns `[]` with a warning when
  `G0001` is missing or empty, `G0000` is missing, or `G0000` has no id-0 row; `run_nms` then
  stops early. (Before 2026-10-22 it used `G0001` row 0 twice and crashed on a missing table.)
- Each NM instance's `nm_id` is its index in that list (`nelder_mead_swarm.py`). The postprocess
  `G0001` token returns only the n_mdl-1 `G0001` rows, not this n_mdl ensemble.
- Swarm tables are `NMSG####` (`NelderMeadSwarm.prefix = 'NMSG'`); code parsing table names as
  `G####` breaks on them.

**NMSRunner (shared `CoreRun` for all NM instances)**
- `CoreRun.__init__` builds `mdl_locks` from its initial `models` list; NMSRunner starts empty, so
  `NMSRunner.run` registers `mdl_locks[(table name, id)]` (e.g. `('NMSG0003', 2)`) under
  `el_locks_lock`, and the inherited `_process_model_locked` releases it. Any other `CoreRun`
  subclass with a dynamic pool must do the same, or it hits `KeyError` in that `finally`.
- `_process_single_model` calls `collect_sim_profiles()` once per thread after each step, so one
  thread can move another thread's pooled model to SCORING. Models are matched by
  `get_table_name(model) == table` and id, with the `_sim_offset` banding as in `CoreRun`.

**Known unfixed defects (2026-10-22)**
- `NelderMead.get_options` final stage gates `maxfev` on `nm_maxfev` instead of `nm_final_maxfev`,
  and reads `nm_adaptive`; `nm_final_adaptive` is never read.
- GUI scheme SWARM_NM sets `NMS_start='G0001'` with `max_gen=1`, but the GA loop counts gen 0, so
  G0001 is never built and the ensemble is empty.
- `Exponential.create_next_gen`: a median score of 0 gives NaN probabilities (IndexError or a
  near-endless loop); `n_mdl == 1` raises IndexError.

**Frozen parameters**: the setting is `fixed_params` (`default_settings.py`; MANUAL calls it
`frozen_params`). Only the linear sensitivity honours it (`sensitivity/linear.py`, two `in
self.settings['fixed_params']` tests); GA and NM perturb exactly `active_p`. The linear sensitivity
builds two models (±) per non-fixed parameter, and each model runs every PES slot.

**Why:** these tables and locks are shared by GA, NM, NM swarm, postprocessing and kmoui, and their
conventions are spread over many files; the swarm path had never run end to end before 2026-10-22.
**How to apply:** check this before changing table names, ensemble seeding, CoreRun locking or the
NM options; test new swarm code with a real `NMSRunner` on a tmp SIM_DB (see `test_core_ci.py`).

Sources: `kimeco/_kimeco.py::KiMecO.get_ensemble`, `::KiMecO.set_important_parameters`;
`kimeco/optimizers/GeneticAlgo/ga.py::GeneticAlgorithm.get_gen_one`; `kimeco/core.py::CoreRun.__init__`,
`::CoreRun._process_model_locked`; `kimeco/optimizers/NelderMead/nm_swarm_runner.py::NMSRunner`;
`kimeco/optimizers/NelderMead/nelder_mead.py::NelderMead.get_options`;
`kimeco/gui/input_sections/optimizer_section.py` (SCHEME_SWARM_NM);
`kimeco/optimizers/GeneticAlgo/exponential.py::Exponential.create_next_gen`.
Related: [[unit-test-stand-ins]].
