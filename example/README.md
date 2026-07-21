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
This file encodes the PES of the C₂H₅ + O₂ system:
See the associated publication:
[https://doi.org/10.1016/j.proci.2016.07.100](https://doi.org/10.1016/j.proci.2016.07.100)
[https://www.sciencedirect.com/science/article/pii/S1540748916303583](https://www.sciencedirect.com/science/article/pii/S1540748916303583)


## Parameter classes, their SOP examples, and the `std_*` uncertainties

For each parameter class below the table gives: a concrete example taken from
this example's MESS input, the matching `std_*` keyword and its value, and how
that value is interpreted. Uncertainties fall into three kinds:

- **Additive** — nominal value in appropriate unit.
- **Percentage / ratio** — a fractional spread of the nominal value
  (`0.1` = ±10 %).
- **Multiplicative factor** — the nominal value is multiplied/divided by the
  factor (`1.1` ⇒ up to ×1.1 or ÷1.1). Used as standard deviation of a log-normal distribution.

| Parameter class | Example in this SOP | Keyword | Value | Interpretation |
|---|---|---|---|---|
| Well / fragment energy | `CH3CH2OO_we` (`ZeroEnergy[kcal/mol] -32.767`), ... | `std_we` | `0.5` | **Absolute, kcal/mol** |
| Barrier energy | `CH3CH2OO=HO2+C2H4_be` (`ZeroEnergy[kcal/mol] -2.40`) | `std_be` | `1` | **Absolute, kcal/mol** |
| Batch vibrational frequencies | `Frequencies[1/cm]` block of each well/fragment | `std_bfc` | `1.05` | **Multiplicative factor** |
| Imaginary frequency | `CH3CH2OO=HO2+C2H4_if`  (`ImaginaryFrequency[1/cm] 1340.6`) | `std_if` | `1.1` | **Multiplicative factor** |
| Hindered rotor | `CH2CH2OOH_hrs2` (3rd hindered rotor scan of `CH2CH2OOH`) | `std_hrs` | `0.1` | **Percentage (±10 %)** |
| Energy-transfer factor | `Factor[1/cm] 180`| `std_fact` | `0.25` | **Percentage (±25 %)** |
| Energy-transfer power | `Power				.95` | `std_pow` | `0.075` | **Absolute (dimensionless exponent)** |
| Lennard-Jones ε | `Epsilons[1/cm]	4.93  267.5` | `std_epsilon` | `0.1` | **Percentage (±10 %)** |
| Lennard-Jones σ | `Sigmas[angstrom]	2.576 4.144` | `std_sigma` | `0.1` | **Percentage (±10 %)** |
| Barrierless symmetry factor | `SymmetryFactor of C₂H₅O₂ = C₂H₅ + O₂` | `std_sfc` | `2` | **Multiplicative factor** (scales the density of states) |
| Multidimensional-rotor symmetry | `SymmetryFactor of Core MultiRotor` internal rotations of `C₂H₅O₂` | `std_mrc` | `1.5` | **Multiplicative factor** (scales the density of states) |

`max_std` (`3`) caps how many standard deviations away from the nominal SOP any
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
