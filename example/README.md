# Example: Ethyl + O₂ (C₂H₅ + O₂) optimization

This folder is a complete, self-contained KiMecO run for the **ethyl radical
oxidation** system. It optimizes theoretical kinetics models of the
C₂H₅ + O₂ system against synthetic time-resolved
species concentration profiles.

## What this run does

In this run, KiMecO takes a nominal *Set Of (Master Equation) Parameters* (SOP) describing one PES (multiple PESs can be used as well) and corresponding partition functions, generates
ensembles of perturbed models within the theoretical uncertainties, runs the
master-equation code (MESS) and the reactor simulations (cantera) for every experiment,
scores each model against the all experimental data and the initial SOP, and lets a genetic algorithm
drive the parameters toward the values that best minimize the least squares error of both experimental measurements and theoretical data.

The experiments are 12 isothermal/isobaric time profiles arranged as a grid of
**4 pressures** (`0.01, 0.1, 1, 10 bar`) × **3 temperatures**
(`550, 600, 650 K`). Each experiment (`pXtY.csv` data, `epXtY.csv` errors)
starts from an initial `C2H5` / `O2` mixture diluted in helium
(`"HE": "base"`) and follows the concentrations of the tracked species over
time using the reactor template `concentration_time_isobar_adiabatic.tpl`
(constant-pressure reactor).

Files:

| File | Role |
|---|---|
| `input.json` | Run configuration (this document explains it). |
| `mess_input_ethyl_oxidation.inp` | Nominal MESS input — **source of the first SOP**. |
| `ThInK_Mech.yaml` | Cantera mechanism with the surrounding secondary chemistry. |
| `concentration_time_isobar_adiabatic.tpl` | Cantera reactor template used to simulate each experiment. |
| `pXtY.csv` / `epXtY.csv` | Experimental concentration profiles and their errors. |

## Where the first SOP comes from

The initial (nominal) SOP is read directly from the MESS input listed under
`mess_inputs`: [`mess_input_ethyl_oxidation.inp`](mess_input_ethyl_oxidation.inp).
This file encodes the *ab initio* PES of the C₂H₅ + O₂ system:

- **Wells:** `W1` (RO₂, CH₃CH₂O₂) and `W2` (C₂H₄OOH).
- **Bimolecular channels:** `R` (C₂H₅ + O₂), `P1` (HO₂ + C₂H₄), `P2` (OH + c-C₂H₄O).
- **Barriers:** `B1`–`B5` connecting those species
  (e.g. `B5`: C₂H₅O₂ ⇌ C₂H₄OOH, `B1`: the barrierless C₂H₅O₂ ⇌ C₂H₅ + O₂).
- **Molecular data** for each stationary point: harmonic frequencies, hindered
  and multidimensional internal rotors, symmetry factors, plus the bath-gas
  energy-transfer model and Lennard-Jones collision parameters.

KiMecO reads every one of these quantities as a **parameter** and perturbs it
inside its theoretical uncertainty. The `std_*` keywords in `input.json` set
the standard deviation (uncertainty magnitude) for each parameter class.

## Parameter classes, their SOP examples, and the `std_*` uncertainties

For each parameter class below the table gives: a concrete example taken from
this example's MESS input, the matching `std_*` keyword and its value, and how
that value is interpreted. Uncertainties fall into three kinds:

- **Additive** — nominal value in appropriate unit.
- **Percentage / ratio** — a fractional spread of the nominal value
  (`0.1` = ±10 %).
- **Multiplicative factor** — the nominal value is multiplied/divided by the
  factor (`1.1` ⇒ up to ×1.1 or ÷1.1).

| Parameter class | Example in this SOP | Keyword | Value | Interpretation |
|---|---|---|---|---|
| Well / fragment energy | `W1` ground energy (`ZeroEnergy -32.767 kcal/mol`), fragments `R`, `P1`, `P2` | `std_we` | `0.5` | **Absolute, kcal/mol** |
| Barrier energy | transition states `B1`–`B5` (e.g. `B5`: C₂H₅O₂ ⇌ C₂H₄OOH) | `std_be` | `1` | **Absolute, kcal/mol** |
| Batch vibrational frequencies | `Frequencies[1/cm]` block of each well/fragment | `std_bfc` | `1.05` | **Multiplicative factor** |
| Imaginary frequency | the imaginary mode at each barrier (`B1`–`B5`) | `std_if` | `1.1` | **Multiplicative factor** |
| Hindered rotor | `Rotor Hindered` scans of `W2` (CH₂, OOH, OH tops) | `std_hrs` | `0.1` | **Percentage (±10 %)** |
| Energy-transfer factor | `EnergyRelaxation … Factor[1/cm] 180` (He) | `std_fact` | `0.25` | **Percentage (±25 %)** |
| Energy-transfer power | `EnergyRelaxation … Power 0.95` (exponent of `(T/298)`) | `std_pow` | `0.075` | **Absolute (dimensionless exponent)** |
| Lennard-Jones ε | `CollisionFrequency … Epsilons[1/cm] 4.93 267.5` | `std_epsilon` | `0.1` | **Percentage (±10 %)** |
| Lennard-Jones σ | `CollisionFrequency … Sigmas[angstrom] 2.576 4.144` | `std_sigma` | `0.1` | **Percentage (±10 %)** |
| Barrierless symmetry factor | `SymmetryFactor` of the barrierless channel `R = C₂H₅ + O₂` | `std_sfc` | `2` | **Multiplicative factor** (scales the density of states) |
| Multidimensional-rotor symmetry | `Core MultiRotor` internal rotations of `W1` | `std_mrc` | `1.5` | **Multiplicative factor** (scales the density of states) |

`max_std` (`4`) caps how many standard deviations away from the nominal SOP any
perturbed parameter is allowed to reach.

> Note: the symmetry factors carry no genuine physical uncertainty; `std_sfc`
> and `std_mrc` are provided so the corresponding density of states can be
> scaled during the optimization.

## Optimizer and its settings

No `optimizer` key is set, so the run uses the default: a **genetic algorithm
(GA)**. The GA-related settings in `input.json` are:

| Keyword | Value | Meaning |
|---|---|---|
| `ga_type` | `"exp"` | Exponential selection strategy for choosing parent models. |
| `n_mdl` | `500` | Number of models per generation. |
| `max_gen` | `100` | Maximum number of generations. |
| `max_score` | `4` | Convergence: maximum score allowed for the best-model ensemble. |
| `param_conv` | `0.01` | Convergence: parameter-space change threshold (1 %) on parameter means/standard deviations. |

The optimization is guided by a periodic **sensitivity analysis** that selects
which parameters are worth perturbing:

| Keyword | Value | Meaning |
|---|---|---|
| `sensi_d` | `0.1` | Derivative step (as a multiple of each parameter's uncertainty) used for sensitivity. |
| `cumul_sensi` | `0.95` | Cumulative-sensitivity threshold (95 %) used to keep only the most influential parameters. |
| `SA_freq` | `20` | Run the on-the-fly sensitivity analysis every 20 generations. |
