---
name: mess-label-rules
description: "What a MESS label (Well, Bimolecular, Fragment, Barrier, PEDSpecies term) may contain and how long it may be, for MESS itself, for AutoMech mess_io readers and for KiMecO/Cantera; UseShortNames and fixed-width output pitfalls. Read before choosing or changing labels in MESS inputs."
type: project
verified: 2026-10-26 against working tree, Auto-Mech/MESS source c569e3a, mess-static 2026.2.4 binary, autoio mess_io source
---
**MESS itself** (Auto-Mech/MESS `src/libmess/model.cc`, `mess.cc`, `src/mess_driver.cc`)
- Labels are whitespace tokens read into unbounded `std::string` (`Well`/`Bimolecular`: `from >> name`; `Barrier`: `lin >> name >> lside >> rside`; `Fragment`: `lin >> name [density]`). No length check; `_name_size_max` is only a `setw` minimum.
- Enforced: one namespace for wells, bimoleculars and barriers ("name … already in use"); barrier endpoints declared earlier; no barrier from a species to itself; at most one barrier per unordered pair ("barriers connect the same pair of species"). So `<lside>=<rside>` barrier names are unique within a valid file.
- `=`, `+`, `-`, `(`, `)` are fine (barrier `CH3CH2OO=C2H5+O2` in `example/mess_input_ethyl_oxidation.inp`). `!` and `#` start comments. Avoid `/`: outputs print `name/energy`.
- Proven at runtime: mess-static 2026.2.4 ran 43-character barrier, 21-character well and 15-character bimolecular labels; relabelled and original inputs gave identical `rate.out` and `ped.out` values by key.
- Widths: `rate.out` tables max(10, len+1), `ped.out` len+1, `ke.out` "Bimolecular fragments density of states" header max(15, len+1): always separated. Fixed widths that run long labels together (no truncation, no failure): `ke.out` "microcanonical number of states" and per-well "state density, microcanonical rate constants" headers (`setw(15)`), log partition-function and tunnelling tables (10). AutoMech's own labels already overflow those. Log hot-energy/prompt tables: max(len+1, 10) in current MESS, fixed 10 in older builds.
- `PEDSpecies A+B=C+D`: each side is resolved by substring search over bimolecular names (earliest match, then longest), no separator needed; it must give exactly 2 bimoleculars ("wrong number of bimolecular species").
- `UseShortNames`: outputs print `W#`/`P#`/`B#`/`C#` plus a "Names Translation Tables" block. KiMecO `MessOutputReader` keys rate rows by the printed first token, so `kimeco/rate_coef.py` lookups miss and **store k = 0 silently**: never add it to inputs KiMecO reads (AutoMech mechdriver sets it).
- MESS writes `rate.out`, `ped.out`, `ke.out` and `<input stem>.log`/`.aux` into the cwd. On AutoMech prompt inputs stderr always shows "master_equation: WARNING: reference energy has not been initialized: using the default" (harmless).

**AutoMech mess_io readers** (autoio `src/mess_io/`)
- `reader/ped.py` splits `PEDSpecies` on `=`: a species label containing `=` breaks it. PED labels are split on `->`, bimoleculars on `+`.
- Bimolecular labels must be `frag0+frag1` with no `_`: `reader/rates.py` decides "bimolecular" (units) by `reactant[0] == 'P' or '+' in reactant`; `dos_rovib` splits `ke.out` tokens `<bimol>_<i>` on `_` and takes `bimol.split('+')[i]` (IndexError otherwise); mechanalyzer `calculator/nonboltz.py` skips PEDs whose product is not a pair.
- `reader/_pes.py`: any Well or Barrier label containing an uppercase `F` is treated as fake (dropped unless `read_fake`).
- Fake wells: `FakeW-<exact bimolecular label>`; filtering and merging rules in `.claude/memory/FakeWell_in_automech.md` §3.

**KiMecO and Cantera**
- `SOP._check_item_name` rejects `.` and `__` (`<label>__<ptype>` parameter names); `MessWriter` placeholders break on `.`, `{`, `}`; `MessInputReader` skips a `Fragment` line containing "geom" (any case).
- Well and Fragment labels must exist in the Cantera mechanism (`MessInputReader.validate_species`), except labels starting with `FW-` or `FakeW-` (`is_fake_well_label`), which are exempt without `force_new_molecules`. A missing Well or Fragment is added by `KinMec.add_species` when `force_new_molecules` is true (fragments are `Well` objects in `SOP.items`). The same label in several input files is one shared item (several `pes_ids`), so the same name must mean the same species in every file.
- `KIN_DB.batch_select` reads `from_name`/`to_name` back as 30-character numpy strings: a longer well or bimolecular name is silently not found. Barrier names never reach KIN_DB or Cantera.
- Equations go into an unquoted YAML scalar (`kimeco/templates/ct_reaction_tpl.py`): a species name must not start with a YAML indicator. Cantera `ck2yaml` reads NASA-7 thermo names from columns 1–24.
- SOP DB columns with `=`, `+`, `-` work (SQLAlchemy quotes them; an ethyl run stored `CH2CH2OOH=OH+c-CH2CH2O__hrs0`) and `tests/unit/test_mess_multi_pes_read_ci.py::test_sop_db_multi_pes_ids_and_symbol_columns` covers them (with several `pes_ids`). Barrier names with `=` are covered from reader to writers by `tests/unit/test_automech_normal_parity_e2e_ci.py`.

**Why:** these limits sit in three codebases; a label MESS accepts can still break mess_io or KiMecO silently (k = 0, missing KIN rows, skipped PEDs).
**How to apply:** check this list before renaming anything in MESS inputs; the `relabel-mess-by-structure` skill applies it. Naming rationale: [[structure-based-species-names]]. MESS source and binaries on this machine: [[mess-source-and-binaries]].

Sources: MESS `model.cc` (Well/Bimolecular/Barrier parsing ~2850–3000, widths ~3460–3640, short names ~20290, ~28270), `mess.cc` `MasterEquation::set_ped_pair`, `mess_driver.cc` (`ke.out` `setw(15)`); mess_io `reader/ped.py` (`get_ped`), `reader/rates.py` (`bimol`, `dos_rovib`), `reader/_pes.py`; `kimeco/parameters.py::SOP._check_item_name`, `kimeco/readers/mess_input.py`, `kimeco/kinmec.py::KinMec.add_species`, `kimeco/database/kin_db.py::batch_select`; paired MESS runs of 2026-10-25 (see [[c4h8-prompt-system-map]]).
