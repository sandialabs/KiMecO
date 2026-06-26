# 1) Mandatory keywords

This section groups the required input blocks needed for a valid KiMecO run setup: mechanism, SOP, and experiments.

## 1.1 Initial MESS inputs (`mess_inputs`)

The files listed in `mess_inputs` should be valid standalone MESS inputs, meaning they can run with MESS independently of KiMecO.

Important consistency rules:

- They should use the same collider (bath gas) as the one used in your experiments.
- Species names (wells and fragments) in MESS input files should match species names in the chemical mechanism (`ct_yaml`).
- `mess_inputs` should include all PES files needed for the chemistry targeted by your experiments. The resulting reactions will constitute the kinetic submechanism to be optimized.

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
