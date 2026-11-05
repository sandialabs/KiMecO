---
name: mess-global-keys-and-mess-io
description: "What each global MESS key does to the rates and its default when absent (from the MESS source and manual), how MESS combines the Lennard-Jones pair, and the AutoMech mess_io writer defaults, hard-codes and pass-2 quirks that change a written input. Read before classifying, forwarding or checking MESS header keys."
type: reference
verified: 2026-10-27 against Auto-Mech/MESS c569e3a, the 2016 MESS manual, autoio (mess_io) source and mechdriver 0.2026.1
---
**Global keys (MESS `src/mess_driver.cc`, `src/libmess/mess.cc`; manual §5)** — default if absent:
- `CalculationMethod` direct | low-eigenvalue | well-reduction — default `direct` (manual: "compulsory").
- `ModelEnergyLimit` — upper bound for partition functions, no other effect; absent → MESS stops.
- `EnergyStepOverTemperature` — grid step x·kT, sets accuracy; absent → MESS stops.
- `ExcessEnergyOverTemperature` — grid top = highest barrier + x·kT; absent → MESS computes one per
  T and prints "WARNING: reference energy has not been initialized: using the default".
- `ChemicalEigenvalueMax` — chemical/relaxation split (which wells merge): 0<x<1 projection,
  x>1 ratio, x<−1 successive ratio; default −2.
- `WellCutoff` — truncates wells at dissociation limit − x·kT (Boltzmann below); default none.
- `ReductionMethod` diagonalization|projection — only when wells merge; source default diagonalization
  (the 2016 manual says projection). No effect on the C4H7 hot input, 2026-11-04: `projection` against
  absent gave the same 3128 rate values; `diagonalization` against absent, on its harmonised copy, a
  byte-identical `rate.out`.
- `AtomDistanceMin` — geometry sanity check only; default 1.4 bohr.
- `WellReductionThreshold` — well-reduction method only; default 10.
- `WellExtension` — extends wells below the WellCutoff bound; bare keyword = 0; value must lie in
  [0, 1); default off; MESS keeps the last assignment of a repeated key.
- `ExtensionCorrection` — must lie in (0, 1), default 0 (`libmess/mess.cc` `well_ext_corr`).
  `WellExtensionCap[kcal/mol]` (inside a Well block) must be > 0; `WellCutoff` must be > 0.
- `GroundEnergyShiftMax` (Model section) — a barrier below its well by ≤ x is raised to the well
  bottom; absent → any submerged barrier stops MESS.
- `FloatType` — solver precision; non-`double` needs an MPACK/MPLAPACK build, else MESS stops.
- `ExponentCutoff` (EnergyRelaxation) — kernel truncated when ΔE/ΔE_down > x; default 10.
- `RateOutput` replaces the default `<stem>.out`; `PEDOutput`/`MicroRateOutput` names are used verbatim. Without `MicroRateOutput` no `ke.out` is written at all (mess-static 2026.2.4, a `HotEnergies` input).
- `PotentialSpline[kcal/mol] N M`: N angles then N energies; M optional (Fourier size, made odd).

**Lennard-Jones pair** (`libmess/model.cc::LennardJonesCollision`): reads exactly two numbers per
line (rest = comment), uses √(ε1ε2), (σ1+σ2)/2 and 1/(1/m1+1/m2): order irrelevant to MESS. The
manual lists "buffer gas, complex" (collider first); AutoMech writes the target first
(`Masses 56.063 39.962` = C4H8, Ar) and both ε/σ entries as the pre-combined pair value
(`mechroutines/models/etrans.py::make_energy_transfer_strs`).

**mess_io writer** (`autoio/src/mess_io/writer/_glob.py::global_rates_input_v1`, templates):
- Defaults `calculation_method='well-reduction'` (≠ MESS), kwarg `well_reduction_thresh`; asserts
  `calculation_method in ('direct','well-reduction')` and `float_type in ('double','quadruple')`
  (`FloatType dd` only for quadruple); `ground_ene_shift_max` is in Hartree (× EH2KCAL).
- Always writes `EnergyStepOverTemperature` (0.2), `WellCutoff 10`, `ReductionMethod diagonalization`,
  `AtomDistanceMin[angstrom] 0.68793`; `full_rates_inp.mako` writes `GroundEnergyShiftMax 10`
  after `Model`; `edown.mako` writes `ExponentCutoff`. `ped_outname`/`ke_outname` only with
  `ped_spc_lst`/`micro_out_params`.
- `bimolecular(calc_spc1_density, calc_spc2_density)`: `density` belongs to each bimolecular
  occurrence (OH is `density` as a product, not as a reactant, in AutoMech inputs).
- `global_rates_input_v1` has no WellCutoff kwarg; given both `hot_enes_dct` and `ped_spc_lst` it
  forces `calculation_method='well-reduction'`; `format_hot_enes` writes one `a:b:c` token per
  species, one decimal (`_glob.py`, `_format.py::format_hot_enes`).
- Pass 2 (`mess_io/_wellextend.py`): `_format_well_extension_inp` un-comments `!WellExtension` or
  inserts a bare `WellExtension` before `Model` (overrides a valued pass-1 line: bare = 0; KiMecO
  therefore comments the input's line in pass 1 as `!WellExtension`, which `! WellExtension` would
  not match, and mess_io gives the value back in pass 2),
  **always** inserts `ExtensionCorrection    0.6` before `Model`, and adds a
  `WellExtensionCap[kcal/mol]` after a well's line only when that well's k(T) stops below the
  run's highest T (energy from the pass-1 log; a None there raises TypeError). So a pass 2 on a PES
  whose wells never merge still changes the input and the rates; the KiMecO driver skips pass 2 on a
  non-prompt PES with no merging, and prints a warning on stdout if that PES's input has WellExtension. `well_lumped_input_file(...,
  lump=True)` builds a `LumpingScheme`/`WellSeparator` block (after `Model`) only when `lump` and
  pass 1 has > 1 well; mechdriver calls it with `lump=False` (`mechroutines/ktp/rates.py`), KiMecO
  with the default `lump=True`. `_get_well_reactions` treats only labels without `+` as wells, so
  `FakeW-A+B` gets no cap or lumping.
- Effect measured on the C4H8/C4H7 system (2026-11-04), one key at a time, KiMecO automech prompt
  mode against the plain input, measured while the driver still kept the input's `WellExtension` in
  pass 1 (it now comments it there): on the C4H7 hot PES, the input's `WellExtensionCap` (53, 40) was
  not forwarded and pass 2 computed none, because with the line active in pass 1 wells never vanish
  and `well_energies` says "No cap needed" (mechdriver comments it out in pass 1;
  `well_extension_pressure` defaults to 1 atm, the KiMecO driver then used the top of the grid, now the
  lowest pressure). Pass 1 without it gives caps 53.4, 44.0 at 1 atm and 68.0, 53.1 at 100 atm. No cap
  moved k by a factor 0.80-75 above about 1500 K, computed 1 atm caps by 0.91-6.8 (with the 0.6
  below); `ExtensionCorrection` 0.4 becoming 0.6 gives 0.95-5.0; `WellCutoff` 20 becoming 10
  gives 0.99-1.02. On abstractions, pass 2's bare `WellExtension` makes k1 pressure dependent
  (up to -9.4 % at 100 atm); `GroundEnergyShiftMax 10` changes nothing. mess_io also rounds
  `ImaginaryFrequency` to an integer (515.37 to 515).
- `rotor_hindered(potential_form='spline')` writes `PotentialSpline N N-1`.

**Why:** these defaults decide whether a key may differ between PES files, and mess_io silently
adds or changes keys in AutomechKinWriter output.
**How to apply:** use with [[multi-pes-mess-reading]] when touching header keys or the automech
writer. Where the source checkouts live: [[mess-source-and-binaries]], [[automech-fake-wells-doc]].
