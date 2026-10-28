---
name: multi-pes-mess-reading
description: "How MessInputReader reads several MESS inputs into one SOP (shared items, energy alignment, header-key classes, per-PES Lennard-Jones layout) and how both writers give each file back in its own frame; the invariants and test pins to respect when changing the reader, the SOP or the MESS writers."
type: project
verified: 2026-10-27 against working tree (uncommitted steps 1-2 of prompt-reactions)
---
**Reading (`kimeco/readers/mess_input.py`)**
- One input file = one PES; `pes_id` = index in `mess_inputs`. Slot index == `pes_id` only because
  `SOP.pes_ids` is the sorted set of well/bimolecular ids and `RateCo.__init__` raises when the
  template count differs: every file must own ≥ 1 well or bimolecular (the reader stops otherwise).
- Same label = same item. A label met again (another file, or another bimolecular block) is parsed
  into a throwaway copy in a scratch SOP (`_rereads`, `_target_sop`, `_target_item`) and compared
  with `differing_fields` (`Well`, `Bimolecular`, `Barrier`) when the block or file ends
  (`_flush_rereads`): any difference stops the read. So rotors are never appended twice.
- A well of one PES may be a fragment of a bimolecular of another PES (same label): one object in
  `SOP.items`, attached to the fragment with `attach_fragment(existing)`; identical data required
  (stop otherwise). Its `Well.db_dict` keys (`{label}__*`) are merged into the bimolecular's, and
  the bimolecular energy includes `sum(frag.dE)`. Fragment `ZeroEnergy` never enters
  `_file_energies`, so the well energy of a shared item never reaches the PES where it is a fragment
  (the automech driver never writes `frag*.zero_ene`; the template path copies the fragment line).
- `HotEnergies` (`_read_hot_energies`, grammar of MESS `mess_driver.cc`): unit kcal/mol, 1/cm or
  kJ/mol (stored in kcal/mol), N species lines `<well> <energy | start<sep>step<sep>finish>`, sep in
  `:;,&%$@#`; blank/comment lines skipped, `End` ends early; any error stops the read. Stored as
  read in `PesFileData.hot_energies` (`{name: (v,) | (start, step, finish)}`, the file's own energy
  zero: no `energy_offset`, no perturbation); species must be wells of that file
  (`_check_hot_species`). The template holds `{SOP.r_hot_energies_pes[<fid>]}`, replacing the block.
  Written values come from `SOP.shifted_hot_energies(pes_id)`: start/finish (or the single value) +
  `items[name].dE`, step unchanged, rounded 1e-10 (dE is frame-independent). `AutomechKinWriter`
  puts them in the payload as `hot_energies` (lists, key absent when the file has no block) and the
  emitted driver passes `hot_enes_dct` to `global_rates_input_v1`.
- Energies: raw values per file go to `_file_energies`; after all files, `PesEnergyAlignment`
  solves one offset per file through shared items (first file of each linked group = reference,
  `TOLERANCE` 0.01 kcal/mol, inconsistent cycles stop). Stored `_energy` is in the aligned frame;
  the offset sits in `SOP.pes_file_data[k].energy_offset` (`PesFileData`, `kimeco/parameters.py`).
  `__we`/`__be` DB values are absolute aligned energies: changing the file order changes DB values,
  not rates. Values are rounded to 1e-10, so both file orders write byte-identical files.
- Header keys: dispatched first on the exact first token (`_header_token`), before the old prefix
  branches (`GroundEnergyShiftMax` was once read as `GroundEnergy`). Classes: `SAME_IN_ALL_FILES_KEYS`
  (global: one value for every PES, a different value stops; presence in only some files does NOT
  stop) and `PER_PES_KEYS` (ModelEnergyLimit, AtomDistanceMin, WellExtension, WellCutoff,
  WellReductionThreshold → `PesFileData`; absent stays absent for that file). ModelEnergyLimit,
  WellCutoff, WellReductionThreshold are also stored on the SOP as the first carrying file's value
  (`_SOP_FALLBACK_ATTRS`, for SOPs without file data). ReductionMethod is global.
- Global key in only some files: `_key_lines` keeps the line of the first carrying file;
  `_add_missing_global_lines` (after all files) inserts it verbatim into the templates lacking it, at
  `_MISSING_LINE_ANCHORS`: before `Model` (index 0 without one) for global-section keys,
  `GroundEnergyShiftMax` right after `Model` (read stops if no `Model` line), `ExponentCutoff` right
  after `Exponential` (stops if absent). One info log per completed file. Collider lines
  (`ColliderLine`): index 0 of Epsilons/Sigmas/Masses must match in all files, and
  Factor/Power/Epsilons/Sigmas/Masses present in some files only still stops. Pitfall: AutoMech
  writes the target first (`Masses 56.063 39.962` = C4H8, Ar), so index 0, called "collider" here,
  holds the target's value and the per-PES second value is the bath. A PES with another target
  species (a C4H7 hot PES next to C4H8 abstractions) stops on index 0; Factor/Power are compared
  exactly too, so there is no per-PES collision model: such files need a harmonised copy.
- Numbers: `_is_number` (regex, E-notation, no nan/inf) is used by frequencies, rotor potentials and
  T/P lists. `save_rotor` raises TypeError on a non-number potential token (before, it swallowed
  lines and merged rotors); `PotentialSpline` angle lines still go through `_leading_numbers`, which
  skips a non-number silently.
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
  ModelEnergyLimit, WellReductionThreshold (`well_red_thresh`), HotEnergies, energy offset; optional
  keys omitted when absent (not None); mess_io hard-code mismatches warn once per process
  (`_warn_once`, reset it in tests); the WellCutoff warning is per PES (key `WellCutoff:<pes>:<v>`,
  mess_io writes 10).
- Perturbator (`perturbator.py`): one instance perturbs a `deepcopy` of the SOP; `already_perturbed`
  records items by `id()` in `_perturbed_in_cycle`, reset at the start of `perturb`, so a shared
  fragment or a well that is also a fragment is drawn once per call (`perturb_well` and the fragment
  loop of `perturb_bimolecular`). Calling `perturb_well` twice outside `perturb` skips the second.
- The template path recomputes Eckart `WellDepth` from item energies (±0.01 vs AutoMech's value).

**Contracts pinned by tests**
- `SOP.from_db_row` is strict: any row/template length mismatch raises `ValueError` (old
  multi-file projects, and ones whose fragment rotors were duplicated, cannot restart or kmopp).
- `tests/unit/test_mess_input_header_keys_ci.py`: warnings only for real mismatches ("Different
  <Label> in <file>", one "bath mass" warning for Masses index 0); consistent inputs log info only.
- `tests/unit/test_automech_driver_ci.py:884-885`: with no header keys the `global_rates_input_v1`
  kwargs are exactly temperatures, pressures, well_extension, ktp_outname.
- Prompt mode (setting `prompt_reactions`, step 2): `AutomechKinWriter._build_payload` adds the
  payload key `prompt_reactions` (`True`) only then, so non-prompt payloads stay byte-identical to the
  goldens. The reader takes the flag with `settings.get('prompt_reactions', False)` (tests build it
  with partial settings) and, after the per-file loop, `_check_prompt_links` stops (via `_stop`) when
  no `PEDSpecies` product (`rhs.split('+')`) equals a `HotEnergies` key of another PES, on a
  malformed pair, or when a linked PED PES has incomplete `MicroEner*`; an unlinked PED PES warns.
  The check is off in non-prompt reads, so the three-file H-group still reads there.
- `test_emitted_main_structure` (`test_automech_driver_ci.py`) pins the driver `If`: a `BoolOp(Or)`
  whose first operand is the Name `prompt_mode` (assigned once from `PES_PAYLOAD.get("prompt_reactions")`)
  and whose last is the bare `MessOutputReader.well_merging(...)` Call; plus exactly six placeholders
  and no other brace in the template.
- `test_installation_mess_ci.py` scans the whole `automech_kin_tpl` source, comments included: every
  `subprocess.run([...])` argv starting with `mess` must have 2 items, and `/mess` and `CONDA_PREFIX`
  must not appear anywhere (a comment containing them fails the test).
- Known gap: `KiMec.create_reactions` adds reactions PES by PES without dedup, so a pair shared by
  two PES gives two Cantera reactions; Cantera 3.2 `Solution(species=, reactions=)` accepts them
  and sums the rates (only a YAML file raises "Undeclared duplicate") (`kimeco/kinmec.py`).

**Why:** the logic spans the reader, SOP, both writers and RateCo; its invariants are implicit.
**How to apply:** read before changing `MessInputReader`, `SOP` header attributes, LJ parameters,
`MessWriter` placeholders or `AutomechKinWriter` payloads. MESS/mess_io keyword facts:
[[mess-global-keys-and-mess-io]]; labels: [[mess-label-rules]].

Sources: `kimeco/readers/mess_input.py::MessInputReader`, `::PesEnergyAlignment`, `::ColliderLine`;
`kimeco/parameters.py::SOP.from_db_row`, `::PesFileData`, `::SOP.pes_ids`, `::SOP.shifted_hot_energies`;
`kimeco/Perturbators/perturbator.py::already_perturbed`; `kimeco/writers/mess.py`;
`kimeco/writers/automech_kin.py::_build_payload`; `kimeco/rate_coef.py::RateCo.__init__`;
`tests/unit/test_mess_multi_pes_{read,write}_ci.py`, `test_sop_lj_per_pes_ci.py`.
