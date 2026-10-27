# 1) Mandatory keywords

This section groups the required input blocks needed for a valid KiMecO run setup: mechanism, SOP, and experiments.

## 1.1 Initial MESS inputs (`mess_inputs`)

The files listed in `mess_inputs` should be valid standalone MESS inputs, meaning they can run with MESS independently of KiMecO.

Important consistency rules:

- They should use the same collider (bath gas) as the one used in your experiments.
- Species names (wells and fragments) in MESS input files should match species names in the chemical mechanism (`ct_yaml`).
- `mess_inputs` should include all PES files needed for the chemistry targeted by your experiments. The resulting reactions will constitute the kinetic submechanism to be optimized.
- Several MESS inputs are read into one SOP, one PES per file (in the order of `mess_inputs`). A well, fake well, bimolecular species or barrier with the same name in several files is one item shared by those PESs, so the same name must always designate the same species, and its data (frequencies, rotors, symmetry factor, ...) must be identical in all files, otherwise the read stops. This includes a well of one PES that is a fragment of a bimolecular species in another PES: with identical data it is one item (one set of parameters, perturbed once per perturbation cycle); with different data the read stops. AutoMech fake wells (labels starting with `FW-` or `FakeW-`) are recognised automatically and need no `force_new_molecules`.
- Energies are aligned through the items shared between files: the first file (in `mess_inputs` order) of each group of linked files is the energy reference, and the energies of the other shared items must agree after alignment (tolerance 0.01 kcal/mol). Each file is still written back in its own energy frame.
- The header keywords `Factor` and `Power` must be identical in all files, and so must the global keys `CalculationMethod`, `EnergyStepOverTemperature`, `ExcessEnergyOverTemperature`, `ChemicalEigenvalueMax`, `ExponentCutoff`, `ReductionMethod`, `GroundEnergyShiftMax` and `FloatType`: a different value in two files stops the read, but a global key set in only some files does not (its value holds for every PES and the key is added to the inputs that lack it). `ModelEnergyLimit`, `AtomDistanceMin`, `WellExtension`, `WellCutoff` and `WellReductionThreshold` are per-PES: each file keeps its own value, and a key absent from a file stays absent for that PES. A `HotEnergies` block (`HotEnergies[kcal/mol|1/cm|kJ/mol] N`, one energy or `start:step:finish` range per well) is read per PES; its energies move with the perturbation of their well when the input is written back, and each species must be a well of that file. Numbers in E-notation (`4.3E-05`) are accepted; a non-number inside a hindered-rotor potential stops the read. In `Epsilons`, `Sigmas` and `Masses`, the first value is the collider and must be identical in all files; the second values may differ per file.

| Keyword | Default value | Description |
|---|---|---|
| mess_inputs | [] | List of MESS input files (relative or absolute paths). Mandatory. |
| force_new_molecules | false | If false, missing species between MESS and mechanism cause validation/run stop. If true, missing species are allowed and will be created in the mechanism. This option should not be used if experimental simulations require thermo or transport properties. |


## 1.2 Chemical mechanism (`ct_yaml`)

Defines the chemical mechanism to optimize.

Mechanism requirements:

- It should be a Cantera YAML mechanism file.
- It should contain all secondary chemistry needed to model the provided experiments.
- Species names should be consistent with the names used in MESS inputs.

| Keyword | Default value | Description |
|---|---|---|
| ct_yaml | "" | Path to the Cantera mechanism YAML file. Mandatory. |


## 1.3 Experiments (`experiments`)

Defines experimental datasets and reactor templates. It also drives the rate-condition grids used for simulation and kinetic evaluation. Each experiment must have a valid temperature, pressure, and reactor template. The GUI validates that the template can be loaded and parsed by Cantera.

Example with one valid experiment:

```json
{
  "mess_inputs": [
    "mess/pes_01.inp"
  ],
  "ct_yaml": "gas.yaml",
  "experiments": [
    {
      "temp": 1000.0,
      "pres": 760.0,
      "pres_unit": "torr",
      "cantera_tpl": "templates/reactor_template.py",
      "data_file": "data/exp1_profile.csv",
      "error_file": "data/exp1_error.csv",
      "initial_ratio": {
        "C2H5": 0.01,
        "O2": 0.05,
        "HE": "base"
      }
    }
  ]
}
```

### 1.3.1 User JSON experiment keys

| Keyword | Default value | Description |
|---|---|---|
| experiments | [] | List of experiment objects. Mandatory and must contain at least one valid entry. |

Each experiment entry should be a dictionary with the following keys:
| Keyword | Default value | Description |
|---|---|---|
| temp | none (required) | Experiment temperature in K. |
| pres | none (required) | Experiment pressure (interpreted with pres_unit). |
| pres_unit | "torr" (or first compatible unit in GUI list) | Pressure unit for this experiment. Canonicalized and converted to Pa during ingestion. |
| weight | 1.0 | Relative experiment weight before normalization. |
| cantera_tpl | none (required) | Path to Cantera reactor template file. Must contain all required template placeholders. |
| data_file | none (required) | Path to experimental data CSV. |
| error_file | none (required) | Path to experimental error CSV. |
| initial_ratio | none (required if not concentration) | Initial mixture as species:fraction pairs. Exactly one of initial_ratio or initial_concentration must exist. |
| initial_concentration | none (required if not ratio) | Initial mixture as species:molecule_count pairs. Converted to mole fractions internally. Bath gas is denoted with value "base". Must be the same as used in the MESS template. |
| w_species | {} | Optional per-species scoring weights for this experiment. |

### 1.3.2 Data/error CSV time column and units

The first column of every `data_file` / `error_file` CSV must be the time
column. Its header is `time` and is **case-insensitive** and whitespace
tolerant. An optional bracketed unit may be appended to declare the unit of
the time values; KiMecO always normalizes and stores the time grid in
**seconds**. Accepted header forms:

| Header form | Meaning |
|---|---|
| `time` | Values already in seconds (default). |
| `time[s]`, `time[min]`, `time[us]` | Cantera-recognized time units. |
| `time[ms]`, `time[millisecond]`, `time[milliseconds]` | Milliseconds (aliases). |
| `time[1e-3s]`, `time[0.001 s]`, `time[1E-3s]` | Numeric factor combined with a unit. |
| `time[1e-3]` | Factor-only form (no unit token) interpreted as a multiplier to seconds. |

Notes:
- The `time` token is case-insensitive (e.g. `Time`, `TIME` are accepted).
- Whitespace inside and around the brackets is tolerated.
- An unknown or non-time unit (e.g. `time[kg]`), an empty bracket
  (`time[]`), or a malformed header raises a `ValueError` during ingestion.
- The data and error grids are compared in seconds with a numerical
  tolerance, so equivalent grids expressed in different units still match.
