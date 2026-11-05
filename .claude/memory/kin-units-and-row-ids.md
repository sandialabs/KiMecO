---
name: kin-units-and-row-ids
description: "Units of the KIN rows (P in bar, k exactly as MESS prints it), how KiMecO matches P/T against them, the stale 'Torr' labels, and why row ids need a fixed pair count per model. Read before adding rows to KIN_DB (e.g. prompt channels) or comparing a rate from another tool with a KIN row."
type: project
verified: 2026-10-31 against 4efa377 + step-3 working tree
---
**Pressure is in bar.** `user_input.py` converts the experiments' pressures from Pa to bar
(`np.round(..., 5)`) into `rc_pres` / `pp_pres` and forces `pres_unit = 'bar'`. The template path
writes `PressureList[{SOP.pres_unit}]` (`readers/mess_input.py`), the automech driver replaces
mess_io's `PressureList[atm]` by `PressureList[bar]` (`writers/automech_kin.py::_globkey_str`).
The "Torr" in `database/kin_db.py` docstrings (P arguments) and in
`gui/parameters_metadata.py` (`rc_pres`, `pp_pres` labels) is stale.
`rc_temp` / `rc_pres` are the experiments' exact values (no rounding of T): 298.15 K is normal.
`KMOInput.create_experiments` overwrites any `rc_temp`/`rc_pres` given in `input.json` with the sorted
unique experiment T and P, so an n-temperature rate grid needs experiments at those n temperatures.

**k is stored exactly as MESS prints it**: s⁻¹ (unimolecular), cm³ molecule⁻¹ s⁻¹ (bimolecular;
MESS header "Bimolecular Rate Units: cm^3/sec"). Nothing is converted on read or store:
`MessOutputReader` turns `***` into 0.0, `RateCo.recover_rslts` clamps negatives to 0 and stores an
absent pair as 0.0; the stored P/T are the grid floats, not the numbers MESS printed (matched with a
relative tolerance by `MessOutputReader._safe_index`). Only Cantera converts:
`kinmec.py` multiplies bimolecular k by `scipy.constants.Avogadro / 1000` (m³ kmol⁻¹ s⁻¹).
mess_io / mechanalyzer instead return atm and cm³ mol⁻¹ s⁻¹ (see [[mechanalyzer-prompt-pitfalls]]).

**Grid pressures must fit 3 significant digits in bar.** MESS prints pressures in its `.out` with 3
digits and `MessOutputReader._safe_index` accepts a relative error of 1e-4 only, so 101.325 bar
(100 atm, printed `101`, 0.32 % off), and most other atm values, stop the read with `ValueError: 101.0 is not in list` (verified 2026-11-04,
in the prompt collector; a 1 bar grid never shows it). Use 3-digit bar values.

**KIN queries use exact float equality** on P and T (`kin_db.py`, `c.P == pres`): any writer of
KIN rows must store the exact `rc_*` / `sub_*` grid floats.

**Row ids assume a fixed pair count per model**: `recover_rslts` gives model `id` the block
`base_id = id * n_p * n_t * n_pairs`, one row per `sop.reaction_iterator()` pair and (P, T) cell
(`rate_coef.py`); `missing_grid` / `is_in_db` count rows against `n_pairs`. Extra per-model rows
need a count fixed per SOP, or ids collide and the counts break.

**Prompt rows (step 4, uncommitted)** live in the same table, tagged by `to_name`
`'+'.join(product_fragments) + PROMPT_TO_NAME_SUFFIX` (`'__prompt'`, `prompt_collector.py`; `__` is
refused in SOP items and fragments); `pes_id` = PED PES, `from_name` = `ped_reactant`, all-zero channels
stored. Ids: optimisation runs `PROMPT_KIN_ROWID_BASE (5e11) + id*n_p*n_t*n_ch + cell*n_ch + ch_idx`,
with `RateCo._check_prompt_row_ids` raising `PromptRatesError` when thermal ids pass 5e11 or prompt ids
pass `PP_KIN_ROWID_BASE`; kmopp: ids from `pp_row_ids` (>= 1e12) in the one call for thermal + prompt
rows, only for `missing` cells. `is_in_db` counts thermal rows (>= `n_pairs`) and suffixed rows
(>= `n_ch`, prompt mode only) apart; suffixed rows never count as thermal. In prompt mode `load_rates_from_db`
uses the suffixed rows of the channels (step 5, uncommitted; Cantera gets them as irreversible
reactions, see [[prompt-branching-fractions]] §4), and elsewhere ignores them. Two channels with one (pes_id, from_name, to_name) key stop the run
(`_check_prompt_row_keys`).

**Why:** a Stage-2 review assumed Torr and mechanalyzer's units were taken as KIN units; both would
have shifted prompt rates by 750x in P or by Avogadro in k.
**How to apply:** convert to bar and MESS k units before writing or comparing KIN rows; pin the
units with a round-trip test against a row read by `MessOutputReader`.

Sources: `kimeco/user_input.py::create_experiments`, `create_pp_experiments`, `KMOInput.__init__`
(`pres_unit`); `kimeco/rate_coef.py::RateCo.recover_rslts`; `kimeco/readers/mess_output.py`;
`kimeco/database/kin_db.py`; `kimeco/kinmec.py`; MESS `src/mess_driver.cc` (units header).
