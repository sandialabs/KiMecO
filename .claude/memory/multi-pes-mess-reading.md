---
name: multi-pes-mess-reading
description: "How MessInputReader reads several MESS inputs into one SOP (shared items, energy alignment, header-key classes, per-PES Lennard-Jones layout) and how both writers give each file back in its own frame; the invariants and test pins to respect when changing the reader, the SOP or the MESS writers."
type: project
verified: 2026-10-26 against working tree (uncommitted step 1 of multi-pes-mess-parsing)
---
**Reading (`kimeco/readers/mess_input.py`)**
- One input file = one PES; `pes_id` = index in `mess_inputs`. Slot index == `pes_id` only because
  `SOP.pes_ids` is the sorted set of well/bimolecular ids and `RateCo.__init__` raises when the
  template count differs: every file must own ≥ 1 well or bimolecular (the reader stops otherwise).
- Same label = same item. A label met again (another file, or another bimolecular block) is parsed
  into a throwaway copy in a scratch SOP (`_rereads`, `_target_sop`, `_target_item`) and compared
  with `differing_fields` (`Well`, `Bimolecular`, `Barrier`) when the block or file ends
  (`_flush_rereads`): any difference stops the read. So rotors are never appended twice.
- Energies: raw values per file go to `_file_energies`; after all files, `PesEnergyAlignment`
  solves one offset per file through shared items (first file of each linked group = reference,
  `TOLERANCE` 0.01 kcal/mol, inconsistent cycles stop). Stored `_energy` is in the aligned frame;
  the offset sits in `SOP.pes_file_data[k].energy_offset` (`PesFileData`, `kimeco/parameters.py`).
  `__we`/`__be` DB values are absolute aligned energies: changing the file order changes DB values,
  not rates. Values are rounded to 1e-10, so both file orders write byte-identical files.
- Header keys: dispatched first on the exact first token (`_header_token`), before the old prefix
  branches (`GroundEnergyShiftMax` was once read as `GroundEnergy`). Classes in
  `SAME_IN_ALL_FILES_KEYS` (value and presence must match; "absent" is a value) and `PER_PES_KEYS`
  (ModelEnergyLimit, AtomDistanceMin, WellExtension → `PesFileData`). Collider lines
  (`ColliderLine`): index 0 of Epsilons/Sigmas/Masses must match in all files.
- LJ layout: `SOP.epsilons/sigmas = [collider, PES0, …, PES N−1]` → PES k is `__epsilon{k+1}`;
  one file keeps `[e0, e1]`. Names ≥ 10 are safe (`get_parameter_type` startswith, `update`
  int-parse, exact-key `specific_std`/`active_p`/`fixed_params`); perturbator, uncertainties and DB
  loop over `range(len)`, so extending the lists needs no optimizer, DB or GUI change.

**Writing**
- `MessWriter`: the reader returns `MessTemplate` (a list with `pes_id`); the offset is added only to
  `{X.energy}` placeholders when ≠ 0. `{SOP.r_epsilons_pes[k]}` works because
  `_resolve_placeholder` does getattr then `[i]` (placeholders cannot call methods).
  `{__output__.rate|ped|micro}` → `<stem>.out`/`_ped.out`/`_ke.out`: `RateCo` puts 50 models in one
  folder (`rate_coef.py`, `id//50`), so fixed side-output names collide even with one PES. The
  header lists every `parameters_names` entry, so a new parameter changes every slot's header.
- `AutomechKinWriter._build_payload(pes_id)`: per-PES LJ pair `[x[0], x[pes_id+1]]`, masses,
  ModelEnergyLimit, energy offset; optional keys omitted when absent (not None); mess_io hard-code
  mismatches warn once per process (`_warn_once`, reset it in tests).
- The template path recomputes Eckart `WellDepth` from item energies (±0.01 vs AutoMech's value).

**Contracts pinned by tests**
- `SOP.from_db_row` is strict: any row/template length mismatch raises `ValueError` (old
  multi-file projects, and ones whose fragment rotors were duplicated, cannot restart or kmopp).
- `tests/unit/test_mess_input_header_keys_ci.py`: warnings only for real mismatches ("Different
  <Label> in <file>", one "bath mass" warning for Masses index 0); consistent inputs log info only.
- `tests/unit/test_automech_driver_ci.py:884-885`: with no header keys the `global_rates_input_v1`
  kwargs are exactly temperatures, pressures, well_extension, ktp_outname.
- Known gap: `KinMec.create_reactions` adds reactions PES by PES without dedup, so a shared item
  gives duplicate Cantera reactions (`kimeco/kinmec.py`).

**Why:** the logic spans the reader, SOP, both writers and RateCo; its invariants are implicit.
**How to apply:** read before changing `MessInputReader`, `SOP` header attributes, LJ parameters,
`MessWriter` placeholders or `AutomechKinWriter` payloads. MESS/mess_io keyword facts:
[[mess-global-keys-and-mess-io]]; labels: [[mess-label-rules]].

Sources: `kimeco/readers/mess_input.py::MessInputReader`, `::PesEnergyAlignment`, `::ColliderLine`;
`kimeco/parameters.py::SOP.from_db_row`, `::PesFileData`, `::SOP.pes_ids`; `kimeco/writers/mess.py`;
`kimeco/writers/automech_kin.py::_build_payload`; `kimeco/rate_coef.py::RateCo.__init__`;
`tests/unit/test_mess_multi_pes_{read,write}_ci.py`, `test_sop_lj_per_pes_ci.py`.
