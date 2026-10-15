# MESS input -> SOP: how KiMecO parses its parameters

Project memory for Claude Code sessions, agents and developers who read or change how KiMecO turns
MESS input files into the SOP ("set of parameters") and its templates. Written from the code on
`Development` on 2026-09-30; the code is the authority. References are `path::symbol`. Background:
`dev_tests/dev_plan_nb.txt` Appendices K, P, Q, R.5/R.7, S.5-S.8.

## 1. Big picture

- `settings['mess_inputs']` (one file per PES; PES id = file index `fid`) ->
  `kimeco/readers/mess_input.py::MessInputReader(settings, mechanism_species, klog, postprocess).read()`
  -> `(SOP, tpls)`: ONE `kimeco/parameters.py::SOP` shared by all files, ONE template per file (its
  MESS lines, every value the SOP owns replaced by a `{Item.attr}` placeholder).
- Callers: `kimeco/_kimeco.py::KiMecO.set_initial_sop` and the GUI check in
  `kimeco/gui/input_sections/sop_section.py`. `KiMecO.copy_necessary_files` saves the templates as
  `mess_tpl_PES<NN>` and copies `SOP.files2copy` (Rotd `File`, MultiRotor `PotentialEnergySurface`).
- Per model, `kimeco/rate_coef.py::RateCo.create_input` writes `<name>P<NN>.inp` with
  `kimeco/writers/mess.py::MessWriter` (template path), or `<name>P<NN>.py` with
  `kimeco/writers/automech_kin.py::AutomechKinWriter` when `use_automech` (SOP objects, no template).
- `SOP.temp` / `SOP.pres` come from the settings (`rc_temp`/`rc_pres`, or `pp_temp`/`pp_pres` in
  postprocessing), never from the file; `SOP.pres_unit = 'bar'`.
- `SOP.items` (name -> `Well` | `Bimolecular` | `Barrier`, fragments included) is the placeholder
  namespace; `SOP.wells`, `.bimolecular`, `.barriers` hold the PES-owning items. A species that is
  both a Well and a Fragment is ONE shared object. Names may not contain `.` or `__`.

## 2. Per-file, line-by-line parse (`MessInputReader.read`)

- Each line goes through an `if/elif` chain on `line.lstrip().casefold().startswith(<keyword>)`: a
  case-insensitive PREFIX match where order matters (`Masses` is tested before the Atom `Mass`; the
  Fragment branch ignores lines containing `geom`). Unmatched lines are copied verbatim. `save_*`
  helpers read ahead, append their own template lines and return the count the loop must `skip`.
- Current block: `name` (Well / Bimolecular / Barrier), `fname` (Fragment), `last_item` in
  `well|bimo|barr|frag`. Species keywords go to `fname` if `last_item == 'frag'`, else to `name`.
- Bookkeeping (never consumes the line): block headers and `GroundEnergy` close the open
  `DeclarationRegion` (section 6); an `Atom` line opens an Atom core its `Mass[amu]` must close.
- Blocks: `Well`, `Bimolecular` (+ `Fragment`, `Dummy`, `GroundEnergy`), `Barrier <name> <left>
  <right>`; models `RRHO` (verbatim), `Atom`; cores `RigidRotor` (verbatim), `MultiRotor`
  (`save_multirotor`), `PhaseSpaceTheory` / `Rotd` (`save_phasespacetheory` / `save_rotd`, only in a
  Barrier, which becomes `barrierless`); `Tunneling` (`save_tunneling`), `Rotor Hindered`
  (`save_rotor`). `Variational` has no branch of its own (behaviour NOT verified).
- Numbers: `MessNumber.is_float` = what MESS reads (`.5`, `5.`, `4.3E-05`; ASCII digits; no Fortran
  `D`, `inf`, `nan`), `is_int` for Group/Axis. List readers (Epsilons, Sigmas, Masses, Frequencies,
  rotor grids) stop at the first non-number (a trailing comment).
- Units: `MessEnergyUnit` converts with MESS's own constants (`HARTREE_PER_UNIT`, from
  `libmess/units.cc`) and checks `ACCEPTED_UNITS[keyword]`; another unit gives a warning + stop
  (`_energy_scale`). Stored units: **kcal/mol** for ZeroEnergy, GroundEnergy, WellDepth,
  CutoffEnergy, rotor `Potential`, MultiRotor `InterpolationEnergyMax`/`QuantumLevelEnergyMax`,
  ModelEnergyLimit, WellExtensionCap; **1/cm** for ElectronicLevels, Epsilons (`[K]` converted),
  Factor. No unit = stored unit. A line rendered from the SOP is relabelled with the stored unit
  (`MessEnergyUnit.relabel`: `ZeroEnergy[1/cm]` -> `ZeroEnergy[kcal/mol]`); verbatim lines keep theirs.
- After the last file: `_check_redeclared_pairs` -> `FirstDeclarationRule.resolve` ->
  `PhaseSpaceBarrierSplice.add_edits` -> `TemplateEdits.apply` (splices, end-first) ->
  `_default_elec_levels` (singlet) -> `shift_PESs` -> dummy side energy `bar.energy - _well_depth[i]`.

## 3. What is stored where

`X` = item name, `B` = barrier name, `L`/`R` = its sides. Columns are SOP_DB names (`dbs = '__'`).

| MESS keyword (block) | Stored on | Template | Ptype, column |
|---|---|---|---|
| `TemperatureList` / `PressureList` | not read (settings) | `<keyword> {SOP.r_rc_temp}`; `PressureList[{SOP.pres_unit}] {SOP.r_rc_pres}` | - |
| `Factor` (1/cm), `Power` | `SOP.factor`, `SOP.power` | `{SOP.factor}`, `{SOP.power}` | ETF `__fact`, ETP `__pow` |
| `Epsilons`, `Sigmas` | `SOP.epsilons` (1/cm), `SOP.sigmas` | relabelled `{SOP.r_epsilons}`, `{SOP.r_sigmas}` | EPSI `__epsilon<i>`, SIG `__sigma<i>` |
| `Masses` | `SOP.masses` (bath, species) | verbatim | - |
| `CalculationMethod`, `ModelEnergyLimit`, `ExcessEnergyOverTemperature`, `ChemicalEigenvalueMax` | `SOP.calculation_method`, `.model_ene_limit` (kcal/mol), `.excess_ene_temp`, `.chem_eig_max` | verbatim | - |
| other globals (e.g. `ExponentCutoff`) | not stored | verbatim | - |
| `WellExtension`, `ExtensionCorrection`, `WellExcludeGroup`, `WellExtensionCap`, `NoWellExtension` | `SOP.well_extension_inputs[fid]` (`WellExtensionInput`) | verbatim | - |
| `Well`/`Bimolecular`/`Fragment`/`Barrier` header | `SOP.add_new_*`, `SOP.items` | `{X.name}` (Barrier: `{B.name} {L.name} {R.name}`) | - |
| `Dummy` | `item.dummy = True` | verbatim | excluded |
| `ZeroEnergy` (Well, Barrier) | `item._energy` | relabelled, `{X.energy}` | WE `X__we`; saddle: BE `B__be` |
| `ZeroEnergy` (Fragment) | not stored | verbatim | (fragment WE, below) |
| `GroundEnergy` (Bimolecular) | `bim._energy` (first file only) | relabelled, `{X.energy}` | via its fragments' WE |
| `ElectronicEnergy` | NOT parsed | verbatim | - (section 9) |
| `Frequencies N` + values | `item._freq`, `item.ifc` (`SOP.set_freqs`) | header verbatim + `{X.r_freq}` | BFC `X__bfc` (IFC `X__freqNN`) |
| `Geometry[unit] N` | `item.structure` (ase `Atoms`, `SOP.set_structure`) | verbatim | - |
| `Mass[amu]` of an `Atom` core | one-atom `structure` with that mass, no frequency (`save_atom`) | verbatim | - |
| `ElectronicLevels N` | `item.elec_levels` `[[E (1/cm), g], ...]` | verbatim | - |
| `SymmetryFactor` (RigidRotor) | Well `sym_factor`; Barrier `_symFact` | verbatim | - |
| `Rotor Hindered`: `Group`, `Axis`, `Symmetry`, `ThermalPowerMax`, `Geometry`, `FourierExpansion` | `HinRotor` in `item.h_rotors` (`SOP.set_hrotor`) | verbatim | - |
| rotor `Potential[unit] N` + grid | `HinRotor._scan` (kcal/mol) | relabelled header + `{X.r_scan(i)}` | HRS `X__hrs<i>` (not Fourier-only rotors) |
| `Core MultiRotor`: `SymmetryFactor`, `InterpolationEnergyMax`, `PotentialEnergySurface`, `QuantumLevelEnergyMax`, `InternalRotation` | `MultiRotor` in `item.m_rotors` | `{X.m_rotors[i].symFact}`, `.iem`, `.file`, `.qlem`; InternalRotation verbatim | MRC `X__mrc<i>` |
| `Tunneling`: `ImaginaryFrequency` | `bar.ifreq` | `{B.r_ifreq}` | IF `B__if` |
| `Tunneling`: `WellDepth` (x2), `CutoffEnergy` | `bar._well_depth` (dummy energies only); cutoff unit checked only | `{B.r_lenergy}`, `{B.r_renergy}`, `{B.r_coff}` (recomputed) | - |
| PST/Rotd `SymmetryFactor` | `bar._symFact` | `{B.symFact}` | SFC `B__sfc` |
| PST `PotentialPrefactor`, `PotentialPowerExponent`, `TSTLevel` | `bar.pp`, `bar.ppe`, `bar.tst_level` | verbatim | - |
| PST `FragmentGeometry` | not stored | verbatim, then rewritten from the fragments (section 6) | - |
| Rotd `File` | `bar.file`, `SOP.files2copy` | verbatim | - |

A barrierless barrier's `Frequencies` render `Barrier.frequencies` = its Bimolecular side's fragment
frequencies; it has no BE/IF/BFC column (only `B__sfc`) and its energy is max(side energies).

## 4. Templates back to MESS inputs

- Grammar: `{Root.attr[.attr...]}`, `Root` = `SOP` or a `SOP.items` key; `attr[i]` indexes a list;
  `r_scan(i)` is resolved by `Well.__getattr__`. `MessWriter._resolve_placeholder` resolves each
  placeholder; `MessWriter.write` replaces every `{...}` by `str(value)` and first writes one
  `!<column>: <value>` comment line per `SOP.parameters_names` entry. The postprocessing sub-grid
  (`pres`, `temp`) only overrides `SOP.r_rc_temp` / `SOP.r_rc_pres`.
- Formatters (stored values are never rounded): `Well.r_freq` `{: 9.3f}`, 4 per line;
  `Well.r_scan` `{: 7.3f}`; `Barrier.r_ifreq` 3 decimals (`ValueError` unless finite and > 0);
  `r_lenergy`/`r_renergy` = E(TS) - E(side) to 3 decimals, `r_coff` = their min; `r_nfreq` =
  `len(frequencies)`; `SOP.r_epsilons`/`r_sigmas` `{: 7.4f}`; `MessGridFormatter`: T with exactly 3
  decimals, P with >= 3 decimals and >= 6 significant digits, refused if the written P is more than
  1e-5 (relative) away; both raise `ValueError` on values <= 0.
- Rendered values include the perturbation: `Well.energy = _energy + dE`; `Bimolecular.energy =
  _energy + sum(frag.dE)`; `Barrier.energy = _energy` (saddle); `Well.frequencies = _freq *
  bfc**(100/_freq)` (BATCH) or `_freq * ifc`; `HinRotor.scan = _scan * pert`; `Barrier.symFact =
  _symFact * sfc`; `MultiRotor.symFact = _sf * sfc`. Geometry lines are never rendered.

## 5. Perturbation and storage

- `kimeco/enums.py::Pclass`: ADDITIVE `we`, `be`, `pow`; MULTIPLICATIVE `if`, `sfc`, `mrc`, `bfc`,
  `freq`; PERCENT `hrs`, `sigma`, `epsilon`, `fact` (`score` is not a physical parameter).
  `kimeco/Perturbators/perturbator.py::Perturbator.get_boundaries`: v +/- std*max_std, v +/-
  v*std*max_std, or v/std**max_std .. v*std**max_std; only names in `settings['active_p']` move. std:
  `SOP.set_uncertainties` (`std_<ptype>` settings, `specific_std` overrides; unknown key -> `KeyError`).
- `SOP.parameters_names` (ordered; = `SOP_DB.columns`): `__fact`, `__pow`, `exp_<NNN>__score`,
  `__epsilon<i>`, `__sigma<i>`, then the `db_dict` of non-dummy wells, barriers and bimoleculars.
  `Factor` and `Power` are effectively mandatory: `SOP.__init__` only annotates them.
- `Well.db_dict`: `we` (value = `energy`, if `pert_e`), `freq_dict` (`bfc`, or `freqNN` in
  INDIVIDUAL mode), `h_rotors_dict` (skips `fourier` rotors), `m_rotors_dict`. `Barrier.db_dict`:
  barrierless -> `sfc` only; saddle -> the Well dict minus `we`, plus `be` (`_energy`) and `if`.
  `Bimolecular.db_dict` = its fragments' (a fragment-only species keeps `_energy` 0.0: `we` = `dE`).
- `SOP.update(key, value)` (type from `kimeco/scoring_f/scoring.py::get_parameter_type`, suffix after
  the last `__`): WE -> `dE = value - _energy`; BE -> `_energy`; IF -> `ifreq`; SFC -> `sfc`; BFC ->
  `bfc`; IFC -> `ifc[idx]`; HRS -> `h_rotors[idx].pert`; MRC -> `m_rotors[idx].sfc`; ETF/ETP/EPSI/SIG
  -> SOP globals; SCORE -> `scores`.
- `SOP.from_db_row(sop_tpl, row)`: deepcopy of the template SOP, walks `parameters_names` BY POSITION
  and calls `update` where the value differs. Column order is therefore part of the contract.
- `kimeco/_kimeco.py::SopDbGuard`, run in `KiMecO.initialize_databases` right after `SOP_DB(...)`:
  every table must have exactly `SOP_DB.columns` in order; a SHA-256 per species (frequencies,
  structure with masses, rotors, `sym_factor`, `elec_levels`; no energies or factors) is kept in
  `KMO_DB_SOP.db.species.json`. A changed, new or removed species -> `ValueError` ("start the run in
  a new folder"); an old DB without the file -> warning, file written.

## 6. Multi-file rules

- **Energy frames.** A shared Bimolecular keeps the FIRST file's GroundEnergy; a later file b records
  `dE[(a, b)] = E_a(S) - E_b(S)` (`record_frame_offset`; two bimoleculars of the same pair must agree
  within `FRAME_TOL = 1e-6` kcal/mol). `frame_offsets` composes offsets along linked files (root =
  lowest index; inconsistent paths stop). `shift_PESs` adds the offset ONCE to each item's `_energy`,
  by `pes_ids[0]`, and logs one INFO per shifted file. Fragments (`pes_ids == []`) are not shifted.
- **Species declared several times** ("first definition wins"). Each Well/Fragment block is a
  `DeclarationRegion`, read from an emptied item (`SpeciesState.clear`) and snapshotted at its end
  (`SpeciesState.take`): nothing accumulates. `FirstDeclarationRule.winner` = the first `Well`
  declaration, else the first one (`mess_inputs` order, then line order); its state is `put` back.
  - Stop (`SpeciesComparison.stop_reasons`): different composition, atom vs molecule, masses > 0.5 u
    apart, different frequencies + torsions count, different ground-state degeneracy (a missing
    ElectronicLevels block = singlet).
  - Otherwise the loser's model body (`RRHO`/`Atom` line up to its `End`) is replaced by the winner's
    body, minus the depth-1 `MessTemplateBlocks.KEPT_TOKENS` (`ZeroEnergy`, `ElectronicEnergy`,
    `WellExtensionCap`, `NoWellExtension`), plus the loser's own such lines: each file keeps its
    energies.
  - Messages per (species, file): INFO if identical; WARNING listing `differences()` with an energy
    note (ZeroEnergy: not shifted; ElectronicEnergy: moves by dZPE = ZPE(kept) - ZPE(here), 0.5*sum
    of frequencies, because MESS adds the kept ZPE); then one INFO summary per species.
- **Bimolecular already defined.** Never re-declared (`_bimol_redeclared`): its Fragment blocks are
  losing species declarations (`_redeclared_fragment`); a different or partial pair stops
  (`_check_redeclared_pairs`); a block without Fragment blocks receives the first definition's ones
  before its `GroundEnergy` (`FirstDeclarationRule._fill_fragmentless_blocks`, INFO). Same name in a
  later file: WARNING "already exists"; twice in one file: stop.
- **Barrierless barriers** (`PhaseSpaceBarrierSplice`, needs a 2-fragment Bimolecular side): the
  `Frequencies` count becomes `{B.r_nfreq}` (PST and Rotd). PST only: each `FragmentGeometry` is
  matched to a fragment by composition (no match: stop) and replaced by the winner's `Geometry` (an
  atom keeps its own); the barrier's `Rotor` blocks are replaced by the fragments' winning rotor
  blocks (their `{frag.r_scan(i)}` placeholders, so HRS perturbations reach the TS), unless a
  fragment has multi-rotors (WARNING, own blocks kept). The barrier keeps its own `SymmetryFactor`,
  never compared. One WARNING per barrier whose block differed; frequencies + torsions must equal the
  fragments' internal modes, else stop.
- **PENDING user decision** (U1 in `dev_tests/reviews/S6d_regression_chem.md`, finding 16): PST
  total-symmetry double count. Today the barrier keeps its `SymmetryFactor` while the spliced
  fragment rotors bring their own `Symmetry`, so the product can change (C4H71-4: 4 x 2 = 8 vs 4).
  The code at most logs the generic "rotor i differed" barrier warning: no factor, no rescaling.
  Options under discussion: warn with the factor / also rescale / stay silent.
- **Topology hard errors** (stop): a `Well` already registered in a PES (`SOP.check_well`, "Well X
  already exists", same file or another PES; a species first met as a Fragment, `pes_ids == []`, is
  registered instead, Appendix K); a duplicated `Barrier` name.

## 7. Stops vs warnings

- Deferred stop: log, then `self._trigger_stop = True`; reading goes on so every problem is logged
  (the rule/splice `stop_requested` flags feed it). `KiMecO.set_initial_sop` then raises
  `ValueError("Input file reading failed due to missing species in the mechanism file...")` whatever
  the cause: read the log. The GUI raises "MESS/SOP parsing flagged consistency errors".
- Deferred stops: species missing from the mechanism with `force_new_molecules` false; `__` in a
  name; Factor, Power, Epsilons[0], Sigmas[0], Masses[0], CalculationMethod, ModelEnergyLimit (rel.
  1e-4), ExcessEnergyOverTemperature or ChemicalEigenvalueMax differing between files; an energy unit
  MESS rejects; `TSTLevel` not in `EJ|E|T|J=0` (case-sensitive); topology errors; malformed Barrier
  or Geometry line; a third Fragment, or a Fragment outside a Bimolecular or naming a Barrier;
  `FragmentGeometry` outside a PST core; Atom core without (or with an unreadable) `Mass[amu]`, or
  element not identifiable (name first, else the only element within 0.5 amu); rotor grid with a
  wrong count, an unreadable line or a second `Potential`; a well-extension keyword out of MESS range
  or outside a Well block; inconsistent frame offsets; the section 6 stops.
- Immediate exceptions: missing file (`FileNotFoundError`); `n_exp <= 0` (`sys.exit(1)`); `.` in a
  name (`ValueError`, `SOP._check_item_name`); wrong number of frequencies, non-integer Group/Axis,
  missing MultiRotor/InternalRotation keywords (`TypeError`); unknown keyword or missing `End` in a
  Rotor/MultiRotor/InternalRotation/PST/Rotd/Tunneling block (`Error` = `uu.Error`,
  `AttributeError`); two rotors with the same Group/Axis but different data in one declaration
  (`Well.add_hrotor`, `ValueError`); overlapping template edits (`RuntimeError`, a reader bug).
- Write time: `MessGridFormatter`, `Barrier.r_ifreq` raise `ValueError`. Warnings only: Bimolecular
  in another file, species re-declarations, PST block differences, missing species if forced.

## 8. The AutoMech path

- `AutomechKinWriter(sop, pes_id, sub_p, sub_t, settings)._build_payload()` reads SOP objects, not
  templates: non-dummy `SOP.wells_in(pes_id)`, `SOP.bimols_in(pes_id)`, barriers of that PES.
- Species (`_species_payload`): `zero_ene = item.energy`, `geo`, `mass`, `sym_factor`, `freqs =
  item.frequencies` (perturbed), `elec_levels`, `hind_rotors` (scan-based only; Group/Axis made
  0-based), `multi_rotors`. A one-atom structure is written as a MESS `Atom`.
- Saddle barriers: `zero_ene`, `geo`, `sym_factor = bar.symFact`, `freqs`, rotors, `ifreq`, well
  depths `r_lenergy`/`r_renergy`. Barrierless: `rotd` if the barrier has `file`, else `phasespace`
  (fragment geometries, `pp` default 10.0, `ppe` default 6.0, `tst_level` default `EJ` = MESS's);
  PST rotors = the fragments' (`_pst_hind_rotors`); `_check_pst_dof` / `_check_rotd_dof` raise
  `ValueError` when frequencies + rotors differ from the fragments' 3N-6 (3N-5 linear, 0 atom).
- Globals: `calc_method`, `model_ene_limit`, `excess_ene_temp`, `chem_eig_max`, `factor`, `power`,
  `epsilons`, `sigmas`, `lj_masses` (first two `SOP.masses`, else N2 28.0134 + heaviest well, with a
  warning), `edown_cutoff = 15.0` (fixed), the grids; plus `fake_wells`, `well_extension_input` (from
  `SOP.well_extension_inputs[pes_id]`), `extension_correction_setting` and `nb`. The driver
  re-renders frequencies and `ImaginaryFrequency` with 3 decimals (`_render_freqs`).

## 9. Known limitations (verified in code unless marked)

- `ElectronicEnergy` is not parsed: the line stays verbatim and `_energy` stays 0.0, so WE
  perturbations and frame shifts do not reach that line, and the AutoMech payload sends
  `zero_ene = 0.0 + dE` (derived from the code, not run).
- `PotentialSpline` is not supported (comment in `save_rotor`); MANUAL.md says the reader stops on it.
- FourierExpansion-only rotors (no `Potential` grid): `HinRotor.fourier = True`, never perturbed, and
  skipped by the AutoMech payload, so a PST fragment with one fails `_check_pst_dof`.
- AutoMech, species with multi-rotors: only `multi_rotors[0]` is written, without hindered rotors
  (`_species_data`). `ExponentCutoff` is not read (the driver uses 15.0).
- Cross-file checks compare only the first value of Epsilons, Sigmas and Masses. The `freq_mode`
  setting reaches only the Perturbator: items keep `FreqMode.BATCH`, so SOP columns are `__bfc`.
- `_build_payload` drops Dummy bimoleculars but keeps their barriers (spec R.5: MESS then fails).
- `Error` comes from the stdlib `uu` module, which Python 3.13 removed (package: Python >= 3.11).
- Raw AutoMech folders still need harmonising (fake wells declared as Wells in two PESs,
  `PotentialSpline`, per-file bath blocks), per spec S.8.

## 10. Where to look when ...

- Keyword ignored or misread: the `elif` chain in `MessInputReader.read` (prefix match, order).
  Unit rejected or converted: `MessEnergyUnit.ACCEPTED_UNITS`, `MessInputReader._energy_scale`.
- Rendered value wrong: `r_*` in `well.py` / `barrier.py`, `MessGridFormatter`,
  `MessWriter._resolve_placeholder`; AutoMech content: `AutomechKinWriter._build_payload`.
- New perturbable parameter: `Ptype`/`Pclass`, the item's `db_dict`, `set_uncertainties`,
  `SOP.update`, the Perturbator, a template placeholder and the payload (old SOP_DBs then fail
  `SopDbGuard.check_columns`).
- Redefinition messages or stops: `FirstDeclarationRule`, `SpeciesComparison`; PST barrier rewrite:
  `PhaseSpaceBarrierSplice`; energies off between PESs: `record_frame_offset`, `frame_offsets`,
  `shift_PESs`; restart refused: `SopDbGuard`.
