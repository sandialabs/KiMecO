---
name: kin-db-readers-and-writers
description: "Who reads and writes KIN_DB rows (the only path to Cantera, the GA report, the kmoui KIN and DB tabs), how ids are allocated per optimisation table and in kmopp, and what happens to extra or colliding rows. Read before adding a new kind of KIN row, changing row ids, or wondering why a row does or does not show up somewhere."
type: project
verified: 2026-11-03 against 56e465a + step 5 working tree
---
**Readers of KIN rows** (grep of `kimeco/`):
- `KIN_DB.get_rates_for_kin_id`: only `RateCo` (`is_in_db`, `load_rates_from_db`).
- `KIN_DB.get_rates_for_models`: only `GeneticAlgorithm.write_ga_rates_output` (`GA_rates.out`,
  `extrapolated_rates.out`); it prints only `sop.reaction_iterator()` pairs, other names become
  unused keys.
- `KIN_DB.batch_select`: only `GOATs.get_rate_coefficients` (`goat.py`), i.e. the kmoui KIN tab,
  whose From/To lists come from SOP names (SQL `to_name IN (...)`); names come back as `str_, 30`.
  The other `batch_select` calls (`core.py`, `nm_swarm_runner.py`, `gui/simsection.py`) are SIM_DB's.
- `get_kin_rc`, `get_kin_rc_for_kin_id`, `get_ids_from_kin_id`: no caller.
- kmoui DB tab (`gui/dbsection.py`): an unfiltered `SELECT *` of every table of every `.db` in the
  workdir, so every KIN row (prompt rows, postprocessing ids) is visible there.
- Generation-complete checks compare `kin_id` sets only.

**Only path to Cantera**: `CoreRun.run_simulation` → `RateCo.load_rates_from_db` → `SIM.q_up`, which
embeds `rates_by_pes` in the SIM script (`templates/sim_arr_tpl.py`) → `KiMec`. SIM tasks never open
KIN_DB. `load_rates_from_db` silently skips rows whose from/to are not names of the PES's
`tbl_map` or whose P/T are not exact grid floats. In prompt mode (step 5, uncommitted) the `tbl_map`
of each PED PES is the species plus its `__prompt` to_names (`prompt_to_names_by_pes`), so a prompt
row is used only when `(pes_id, from_name, to_name)` is a channel key; a channel without a row at
some (P, T) cell raises `PromptRatesError` (`_check_prompt_rows_complete`), and a `A -> B__prompt`
row that is no channel is ignored. Other PESs and non-prompt runs keep species-only tables; it has no ORDER BY, so two rows with one key give
a value that depends on row order. No code splits KIN values or KIN table names on `__` or `+`.

**Rebuilding the mechanism a SIM used** (read-only, e.g. after a run): `KiMecO(input_file,
init_loc=RUN, name=..., sim_job=True)` without `initialize_workdir()` (writes only `<name>.log` in the
cwd), then `RateCo.load_rates_from_db` on `object.__new__(RateCo)` with `db` (anything with
`get_rates_for_kin_id`), `id`, `sop`, `name`, `pres`, `temp`, `prompt_reactions` set, then
`KiMec.prepare_mech` + `get_updated_mech`; open the DBs with the SQLite URI `mode=ro&immutable=1`.

**Writers.** `Model.save_kin` turns the rows into `np.array(rows)` (every value, ids included,
becomes a numpy string; SQLite converts back) and calls `prepare_batch_upsert`, which keeps
`_upsert[table][id] = values`: two rows with one id in a batch silently keep the last, and an id
already stored is overwritten. `Linear.save_initial_model` and kmopp also write through `save_kin`.

**Ids.** Optimisation runs: `rate_coef.py` layout from `id * n_p * n_t * n_pairs` (prompt rows from
`PROMPT_KIN_ROWID_BASE`, see [[kin-units-and-row-ids]]). Model ids per table: GA `G####` 0..n_mdl−1;
`SA####` (in `SA_DB_KIN`) 0..2·n_active; `NM####` always 0; `NMSG####` < ensemble size; nothing caps
them. kmopp always takes ids from `KIN_DB.pp_row_ids` (one id per distinct `(P, T, pes_id, from,
to)` key, from `max(PP_KIN_ROWID_BASE, table max id + 1)`, stored ids reused on rewrite), into the
optimisation's own tables. The "Safeguard" in `CoreRun.run` compares `self.models[idx]` with itself
and never fires; id = list index is enforced only by `reset_model` (`self.models[mdl.id]`).

**Why:** step 4 of the prompt-reactions work needed this map to add prompt rows without touching the
DB layer; a key collision would have changed the Cantera input silently.
**How to apply:** give any new row kind a name no species can have (labels refuse `__`) or its own
storage, and keep its ids disjoint per table.

Sources: `kimeco/database/kin_db.py`, `kimeco/database/kimeco_db.py::prepare_batch_upsert`,
`kimeco/model.py::Model.save_kin`, `kimeco/rate_coef.py`, `kimeco/core.py` (`run`,
`run_simulation`), `kimeco/simulation.py`, `kimeco/goat.py`, `kimeco/gui/dbsection.py`,
`kimeco/optimizers/GeneticAlgo/ga.py`, `kimeco/sensitivity/linear.py`.
