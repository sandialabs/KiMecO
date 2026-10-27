---
name: mess-global-keys-and-mess-io
description: "What each global MESS key does to the rates and its default when absent (from the MESS source and manual), how MESS combines the Lennard-Jones pair, and the AutoMech mess_io writer defaults, hard-codes and pass-2 quirks that change a written input. Read before classifying, forwarding or checking MESS header keys."
type: reference
verified: 2026-10-26 against Auto-Mech/MESS c569e3a, the 2016 MESS manual and autoio (mess_io) source
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
  (the 2016 manual says projection).
- `AtomDistanceMin` — geometry sanity check only; default 1.4 bohr.
- `WellReductionThreshold` — well-reduction method only; default 10.
- `WellExtension` — extends wells below the WellCutoff bound; bare keyword = 0; default off; MESS
  keeps the last assignment of a repeated key.
- `GroundEnergyShiftMax` (Model section) — a barrier below its well by ≤ x is raised to the well
  bottom; absent → any submerged barrier stops MESS.
- `FloatType` — solver precision; non-`double` needs an MPACK/MPLAPACK build, else MESS stops.
- `ExponentCutoff` (EnergyRelaxation) — kernel truncated when ΔE/ΔE_down > x; default 10.
- `RateOutput` replaces the default `<stem>.out`; `PEDOutput`/`MicroRateOutput` names are used verbatim.
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
- Pass 2 (`mess_io/_wellextend.py`): `_format_well_extension_inp` un-comments `!WellExtension` or
  inserts a bare `WellExtension` before `Model` (overrides a valued pass-1 line: bare = 0);
  `_get_well_reactions` treats only labels without `+` as wells, so `FakeW-A+B` gets no cap or
  lumping.
- `rotor_hindered(potential_form='spline')` writes `PotentialSpline N N-1`.

**Why:** these defaults decide whether a key may differ between PES files, and mess_io silently
adds or changes keys in AutomechKinWriter output.
**How to apply:** use with [[multi-pes-mess-reading]] when touching header keys or the automech
writer. Where the source checkouts live: [[mess-source-and-binaries]], [[automech-fake-wells-doc]].
