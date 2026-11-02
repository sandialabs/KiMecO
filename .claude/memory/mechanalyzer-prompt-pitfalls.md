---
name: mechanalyzer-prompt-pitfalls
description: "External pitfalls of mess_io/mechanalyzer prompt (BF) calculations: pressure units mixed when MESS writes bar, NAVO conversion rule, PED precision and T rounding in MESS outputs, silent NaN/skip/sys.exit sites, cuts and cwd writes of bf_tp_df_todct, label quirks. Read before calling mechanalyzer's BF or prompt functions, or reading ped.out/.log with mess_io."
type: reference
verified: 2026-10-31 against AutoMech checkouts (mechanalyzer 0.2026.1, autoio), MESS c569e3a
---
**Pressure units mix when PressureList is not atm.** MESS writes every pressure in the
PressureList unit (`.out`, `ped.out` "pressure[bar]", `.log` "Pressure = ... bar"). mess_io converts
only the k1 rates to atm (`reader/rates.py::_pdep_kts` → `_convert_pressure`); `reader/ped.py::get_ped`
and `reader/hoten.py::extract_hot_branching` keep the raw numbers. `calculator/bf.py::merge_bf_rates`
then fills each side from the other's nearest pressure: values are right only by luck. KiMecO writes
bar (see [[kin-units-and-row-ids]]); its collector uses mechanalyzer for BFs only.

**k units.** `rates.py` multiplies k by `phycon.NAVO` (6.0221409e23, not scipy's 6.02214076e23) iff
the reactant label contains `+` or starts with `P`; filtering (k ≤ 1e-24) happens before.
`builder/_prompt.py::multipes_prompt_dissociation_ktp_dct` removes the thermal fw/rev entries of the
prompt keys and merges: the BF-scaled thermalised channel carries the thermal abstraction's key.

**MESS output precision.** `ped.out` is written with `PedPrecision` significant digits (default 3,
range 2-6; P header, energies, values), the `.log` with default precision; T in both is
`(int)floor(T + 0.5)` (Python `round()` differs at .5). `get_ped` builds DataFrames with
`index=set(T)`, `columns=set(P)`: two pressures equal at 3 digits collapse into one column.
mechanalyzer intersects T as exact floats and calls `sys.exit()` when a PED T is missing from the hot
T (`calculator/rates.py`, after "does not cover the full range").

**Silent failures** (status-0 `sys.exit()` satisfies Slurm `afterok`): unknown hot-block layout
(`hoten.py`, "Yuri changed output again"), `extract_fne`, unknown model / missing DOS in
`calculator/ene_partition.py` (listed in [[prompt-branching-fractions]] §4). NaN sources: a NaN PED
block (`ped.py`), an empty PED or ≤ 3 hot energies in the PED range (`bf.py::bf_tp_df_full`), 0/0
normalisation giving an all-NaN Series that the NaN-row drop does not catch.
`bf_tp_df_full` drops a whole T row when any P cell is NaN.

**`bf_tp_df_todct` cuts unconditionally**: BF < 1e-30 and BF > 1 − 1e-12 (several species) dropped
point by point (the thermalised channel at BF ≈ 1 vanishes), species below the threshold everywhere
dropped, and with `savefile=True` it writes `bf_{model}_{rxn}_{spc}.txt` to the cwd.

**Labels.** `extract_hot_branching` merges only `FakeW-X` columns into `X` (not `FW-`);
`bf.py::rename_ktp_dct` pops entries from its input dict (pass a copy) and picks `spc0` from all
hot-PES species; `_prompt.py::isconnected` also counts reactant fragments.

**Why / how to apply:** each of these silently changed or dropped prompt rates during the design of
KiMecO's collector; check grids, NaN and the sum of BFs yourself around any mechanalyzer call.

Sources (AutoMech checkout, see the local note `automech-fake-wells-doc`): `autoio/src/mess_io/reader/{rates,ped,hoten}.py`,
`mechanalyzer/src/mechanalyzer/calculator/{bf,rates,ene_partition,nonboltz}.py`,
`mechanalyzer/src/mechanalyzer/builder/_prompt.py`; MESS `src/libmess/model.cc` (`ped_precision`),
`src/mess_driver.cc` (`PedPrecision`), `src/libmess/mess.cc` (T output).
