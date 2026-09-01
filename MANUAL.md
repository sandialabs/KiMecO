# KiMecO Input Manual (GUI-Sectioned)

This manual documents the input keywords handled by KiMecO.

- Scope: keywords that are written into the JSON config, validated by input checks. Unspecified keywords will have default values.
- Organization: mirrors the tabs in the kmo_start GUI.
- Source of defaults: kimeco/default_settings.py unless noted otherwise.

## Installation from source

These instructions are written for users who are not familiar with command-line tools.

### 1) Create a dedicated conda environment

Using a dedicated environment avoids conflicts with other Python projects.

```bash
conda create -n kimeco -c conda-forge python=3.10 -y
conda activate kimeco
```

After activation, your terminal prompt usually shows `(kimeco)`.

### 2) Install KiMecO

From the repository root, run:

```bash
pip install -e .
```

Yes: in most cases this simple command works after creating the environment.

### 3) Optional: faster dependency solving with mamba

Recommended method (faster dependency solving):

```bash
conda install -c conda-forge mamba -y
mamba install -c conda-forge --file requirements.txt -y
```

Then install KiMecO:

```bash
pip install --no-build-isolation --no-deps -e .
```

This optional route is mainly useful if you want conda-forge builds for dependencies.

### 4) Verify installation

Run one or more of the following commands:

```bash
which kmo
```

If `which kmo` returns a path and the `--help` commands print help messages, the Python-side installation is working.

### 5) MESS dependency (required)

KiMecO relies on MESS for master-equation calculations.

- MESS can be downloaded from GitHub: https://github.com/Auto-Mech/MESS
- Build or obtain the static MESS binaries separately.
- The static binaries should be manually copied into the conda environment binary directory.

On Linux, this is typically:

```bash
$CONDA_PREFIX/bin
```

Once copied there, the MESS executables are available from the active conda environment. You can check whether MESS is available by running:

```bash
which mess
```

## Getting started

### 1) Create the initial JSON input

You have two options:

- Recommended: use the GUI utility `kmo_start`.
	- Run `kmo_start`.
	- Fill the tabs in order.
	- Save/write the generated JSON file.
- Manual: build the JSON yourself.
	- Read the sections below in this manual.
	- Create a JSON file containing the mandatory keys first.
	- Add optional keys to specify your run conditions.

### 2) Utilities overview

- `kmo_start`: input builder GUI. Use this first if you are new to KiMecO.
  - KIN section behavior: `From` and `To` lists include only wells and bimolecular species (fragments are excluded).
  - KIN section behavior: entries are shown as `NAME [PES XX]`; selecting `From`/`To` enforces same-PES pairs via reciprocal filtering, invalid selections are auto-cleared, and plotting blocks cross-PES pairs with an explanatory message.
- `kmo input.json`: main optimization run command. It reads your input JSON and launches KiMecO.
- `kmoui input.json`: analysis/inspection GUI for completed runs.
- `kmopp input.json`: postprocessing command-line utility.

## 1) Mandatory keywords

This section groups the required input blocks needed for a valid KiMecO run setup: mechanism, SOP, and experiments.

### 1.1 Initial MESS inputs (`mess_inputs`)

The files listed in `mess_inputs` should be valid standalone MESS inputs, meaning they can run with MESS independently of KiMecO.

Important consistency rules:

- They should use the same collider (bath gas) as the one used in your experiments.
- Species names (wells and fragments) in MESS input files should match species names in the chemical mechanism (`ct_yaml`).
- `mess_inputs` should include all PES files needed for the chemistry targeted by your experiments. The resulting reactions will constitute the kinetic submechanism to be optimized.

| Keyword | Default value | Description |
|---|---|---|
| mess_inputs | [] | List of MESS input files (relative or absolute paths). Mandatory. |
| force_new_molecules | false | If false, missing species between MESS and mechanism cause validation/run stop. If true, missing species are allowed and will be created in the mechanism. This option should not be used if experimental simulations require thermo or transport properties. |


### 1.2 Chemical mechanism (`ct_yaml`)

Defines the chemical mechanism to optimize.

Mechanism requirements:

- It should be a Cantera YAML mechanism file.
- It should contain all secondary chemistry needed to model the provided experiments.
- Species names should be consistent with the names used in MESS inputs.

| Keyword | Default value | Description |
|---|---|---|
| ct_yaml | "" | Path to the Cantera mechanism YAML file. Mandatory. |


### 1.3 Experiments (`experiments`)

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

#### 1.3.1 User JSON experiment keys

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


#### 1.3.2 Data/error CSV time column and units

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


## 2) Sensitivity Analysis

This section controls both static sensitivity-based parameter selection and on-the-fly periodic sensitivity analysis during optimization.

| Keyword | Default value | Description |
|---|---|---|
| sensi_d | 0.1 | Derivative step multiplier applied to parameter uncertainty in sensitivity analysis. |
| cumul_sensi | 0.95 | Cumulative sensitivity threshold (0 to 1) used to select active parameters. |
| active_p | [] | Explicit list of parameters to perturb. If set, it skips only the **initial** sensitivity analysis; the listed parameters are preserved, and the on-the-fly sensitivity analysis during the GA still runs and augments this list. Leave empty to run the initial sensitivity analysis. |
| SA_start | 1 | Generation index to start on-the-fly sensitivity analysis. |
| SA_end | 80 | Generation index to stop on-the-fly sensitivity analysis. |
| SA_freq | 20 | Frequency (in generations) for running on-the-fly sensitivity updates. |
| fix_theory_divider | false | When `true`, the first theory divider used to average the active parameters' scores is fixed for the whole run, so models with different numbers of active parameters are never compared under different dividers. |

The derivative step is direction-dependent and set by the parameter's class (not its sampling distribution). For multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, frequencies) the step is truly multiplicative and computed in log space: with factor `f = uc**sensi_d` (where `uc` is the parameter uncertainty), the up step is `value * f` and the down step is `value / f` (e.g. `uc = 1.1`, `sensi_d = 0.1` → perturbed values `[value / 1.1**0.1, value * 1.1**0.1]`). Additive and percentage parameters use an additive step, `value + scale * sensi_d * side`.

## 3) Optimizer

This section selects optimization mode and maps GUI scheme choices to runtime optimizer fields.

### 3.1 Core optimization controls

These keywords control the optimizer type, GA selection strategy, and convergence thresholds.

| Keyword | Default value | Description |
|---|---|---|
| optimizer | "ga" | Type of optimizer. Possible values: "ga" or "nelder-mead". |
| ga_type | "exp" | Genetic algorithm selection strategy. Possible values: "exp" or "tournament". |
| NMS_start | "" | Optional seed generation for NM swarm. For example G0001 is the first generation ran by a GA (which only correspond to models perturbed from the initial model). GT-1 point to the last (pythonic -1) GOAT ensemble, which is the ensemble of top models from all previously ran generation. |
| n_mdl | 500 | Number of models per generation. |
| goat_length | 250 | Size of top models kept in the GOAT ensemble. |
| max_gen | 10 | Maximum generations. Note: use 1 if you only want to perform a "Swarm of Nelder-Mead".|

### 3.2 Nelder-Mead controls

These keywords control Nelder-Mead behavior. They are only used if optimizer is set to "nelder-mead". See SciPy documentation for details on the Nelder-Mead algorithm and its parameters (https://docs.scipy.org/doc/scipy/reference/optimize.minimize-neldermead.html).

| Keyword | Default value | Description |
|---|---|---|
| nm_fatol | 1 | NM function absolute tolerance. |
| nm_xatol | 0.5 | NM parameter absolute tolerance. |
| nm_maxiter | 0 | NM max iterations (0 means solver default behavior where applicable). |
| nm_maxfev | 0 | NM max function evaluations (0 means solver default behavior where applicable). |
| nm_dstep | 0.5 | Initial simplex scaling step for NM. The simplex is created using a derivative step of every active parameters, plus the initial model. |
| nm_adaptive | false | Enables adaptive Nelder-Mead variant. |

The derivative step used to build the initial simplex is direction-dependent and set by the parameter's class. For multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, frequencies) the step is truly multiplicative and computed in log space: with factor `f = uc**nm_dstep`, the up step is `value * f` and the down step is `value / f`, so the two sides are symmetric under a factor and its inverse. Additive and percentage parameters use an additive step.

During the final stage of optimization, the Nelder-Mead algorithm is run again with tighter tolerances after a second sensitivity analysis from the previously optimized simplex. These keywords control the final-stage NM behavior. They are only used if optimizer is set to "nelder-mead". See SciPy documentation for details on the Nelder-Mead algorithm and its parameters (https://docs.scipy.org/doc/scipy/reference/optimize.minimize-neldermead.html).

| Keyword | Default value | Description |
|---|---|---|
| nm_final_fatol | 0.05 | Final-stage NM tolerance (in defaults, currently not surfaced in GUI controls). |
| nm_final_xatol | 0.005 | Final-stage NM parameter tolerance (not surfaced in GUI controls). |
| nm_final_maxiter | 0 | Final-stage NM max iterations (not surfaced in GUI controls). |
| nm_final_maxfev | 0 | Final-stage NM max evaluations (not surfaced in GUI controls). |
| nm_final_adaptive | false | Final-stage adaptive flag (not surfaced in GUI controls). |


## 4) Theoretical Uncertainties

This section controls perturbation model, uncertainty magnitudes, distributions, and convergence thresholds for parameter classes.

### 4.1 Global perturbation and score-balance keys

| Keyword | Default value | Description |
|---|---|---|
| max_std | 4 | Maximum deviation from initial model. |
| freq_mode | "batch" | Frequency perturbation mode. Possible values: "batch" or "individual". Individual mode has not been thoroughly tested. |
| weight_theory | 1.0 | Raw theory contribution weight; normalized at runtime with weight_experiments. |
| weight_experiments | 1.0 | Raw experiment contribution weight; normalized at runtime with weight_theory. |
| specific_std | {} | Per-parameter override map for standard deviations. An entry overrides the global `std_<ptype>` for that parameter and governs the sampling scale, the scoring weight, **and** the perturbation boundaries (trusted range): a larger value widens the accepted bounds, a smaller one tightens them. Parameters without an entry fall back to the global `std_<ptype>`. |
| frozen_params | [] | List of parameters (strings) that are frozen and will not be perturbed. The parameters names of a system are listed at the top of the logfile after starting a run. |

In `batch` frequency mode, the set of perturbed batch frequency factors is derived from the batch frequency coefficient (`bfc`) and the number of frequencies (`freq`) as `frequencies = freq * bfc**(100/freq)`. Changing this formula affects numeric results, so runs from before and after such a change are not bit-for-bit comparable.

Parameters names, used in `specific_std` and `frozen_params`, are constructed by concatenating the species name, two underscores, and the parameter type. For example, `C2H5__we` is the well energy of C2H5, and `O2__we` is the well energy of O2.
To freeze the energy of a bimolecular specie, one has to freeze the energy of its 2 fragments.
The parameter types are:
`we`: well energy
`be`: barrier energy
`bfc`: batch frequency coefficient
`hrs`: hindered rotor scan
`if`: imaginary frequency
`sfc`: symmetry factor coefficient for barrierless reactions
`mrc`: multi-dimensional rotor coefficient
`fact`: energy transfer factor (`\Delta E_{down}` at 300K)
`pow`: energy transfer power (`n` in `\Delta E_{down} = \Delta E_{down,300K} * (T/300K)^n`)
`epsilonX`: Lennard-Jones epsilon
`sigmaX`: Lennard-Jones sigma

Note: the X in `epsilonX` and `sigmaX` is the order in the MESS input.
0 is for the bath gas and 1 for the reactive complex.
These parameters are currently not associated with a species name, so they are not prefixed by a species name.
Hence, to fix the Lennard-Jones parameters of the bath gas, one has to freeze `__epsilon0` and `__sigma0`.
The same is applicable to `__fact` and `__pow` for the energy transfer parameters.

### 4.2 Standard deviations (std_*)

| Keyword | Default value | Description |
|---|---|---|
| std_we | 1.0 | Well and bimolecular fragments energy uncertainty (kcal/mol). |
| std_be | 1.5 | Barrier energy uncertainty (kcal/mol). |
| std_ifc | 1.1 | Individual vibrational frequency multiplicative uncertainty. Multiplicative factor. |
| std_bfc | 1.05 | Batch vibrational frequency multiplicative uncertainty. Multiplicative factor. |
| std_hrs | 0.1 | Hindered rotor uncertainty. Percentage. |
| std_if | 1.1 | Imaginary frequency multiplicative uncertainty. Multiplicative factor. |
| std_fact | 0.25 | Energy transfer factor uncertainty. Percentage. |
| std_pow | 0.075 | Energy transfer power uncertainty. Percentage. |
| std_epsilon | 0.1 | Lennard-Jones epsilon uncertainty. Percentage. |
| std_sig | 0.1 | Lennard-Jones sigma uncertainty. Percentage. |
| std_sfc | 2.0 | Symmetry-factor uncertainty for barrierless reactions. While the symmetry has no uncertainty, this parameter allows to scale the state density. Multiplicative factor. |
| std_mrc | 1.5 | Multi-dimensional rotor symmetry uncertainty. While the symmetry has no uncertainty, this parameter allows to scale the state density. Multiplicative factor. |

**Distribution restrictions.** Each parameter belongs to a category that constrains which sampling distribution (`distrib_*`) it may use:

- Multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, and the individual/batch frequencies) accept only `log-normal` or `log-uniform`.
- Additive (`we`, `be`, `pow`) and percentage (`hrs`, `sigma`, `epsilon`, `fact`) parameters accept only `uniform` or `normal`.

Any other combination cancels the run. In the GUI, only the valid distributions for a parameter's category are selectable.

For multiplicative parameters the theory-score distance is measured in log space as `ln(value / reference) / ln(uncertainty)`, so the penalty is symmetric under a factor and its inverse and consistent with the log-normal (log-space) perturbation of these parameters. Additive and percentage parameters keep their linear distance.

<!-- ### 4.3 Distributions (distrib_*)
|---|---|---|
| distrib_we | "normal" | Distribution for well energies. Additive class: no log distributions allowed. |
| distrib_be | "normal" | Distribution for barrier energies. Additive class: no log distributions allowed. |
| distrib_ifc | "log-normal" | Distribution for individual frequencies. |
| distrib_bfc | "log-normal" | Distribution for batch frequencies. |
| distrib_hrs | "normal" | Distribution for hindered rotors. |
| distrib_if | "log-normal" | Distribution for imaginary frequencies. |
| distrib_fact | "normal" | Distribution for energy transfer factor. |
| distrib_pow | "normal" | Distribution for energy transfer power. Additive class restrictions apply. |
| distrib_epsilon | "normal" | Distribution for Lennard-Jones epsilon. |
| distrib_sig | "normal" | Distribution for Lennard-Jones sigma. |
| distrib_sfc | "log-normal" | Distribution for barrierless symmetry factor. |
| distrib_mrc | "log-normal" | Distribution for multi-dimensional rotor symmetry factor. | -->

### 4.3 Convergence thresholds (conv_*)

| Keyword | Default value | Description |
|---|---|---|
| max_score | 4.0 | Convergence threshold. Maximum score for the best-model ensemble. |
| score_conv | 2 | Convergence threshold. Average score for best-model ensemble. |
| param_conv | 0.01 | Parameter-space convergence threshold used for both parameter values and standard deviations. For additive and percentage parameters it is a percentage (relative change), computed from the arithmetic per-generation mean/std. For multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, frequencies) the per-generation statistics are the **geometric** mean and geometric standard deviation, and genetic-algorithm convergence is measured in log space as `|ln(old / new)|` for both the mean and the standard deviation, consistent with their log-normal perturbation. |
| conv_we | 0.1 | Convergence threshold for well energies.(kcal/mol) |
| conv_be | 0.1 | Convergence threshold for barrier energies.(kcal/mol) |
| conv_pow | 0.01 | Convergence threshold for energy transfer power. |


## 5) Postprocessing

After a KiMecO run completes, postprocessing uses a user specified ensemble (ex: [`G0001`, `GT-1`]) of models to calculate their rate coefficients at new T,P conditions. This is useful for extrapolating mechanism performance beyond the original optimization temperatures and pressures, or analyzing specific ensembles.

### Running postprocessing

Postprocessing is invoked **after the main optimization run finishes**. Use the CLI command:

```bash
kmopp input.json
```

This reads the same JSON input file (with `pp_*` keywords added) and the existing run's workdir, then executes the postprocessing workflow. The command loads all databases and GOAT file from the original run automatically.

### Required keywords

| Keyword | Default value | Description |
|---|---|---|
| pp_experiments | `[]` | **List of dicts** — postprocessing conditions to simulate. Same schema as `experiments` but without `data_file`/`error_file`; each entry adds its own `times` and `species`. See below. |
| pp_ensembles | `["G0001", "GT-1"]` | **List of strings** — tags of ensembles to process (see token syntax below). |

> The MESS extrapolation grid is derived automatically from the unique temperatures and pressures of `pp_experiments`; it is not specified directly. Rate coefficients already present in a model's existing KIN table are reused, so only the missing (P, T) conditions are computed.

> When postprocessing starts, the log prints the metadata of each `pp_experiment` (type, temperature, pressure, species, composition).

### Specifying postprocessing experiments (`pp_experiments`)

Each entry mirrors an `experiments` entry but is **only simulated, never scored**, so it has no `data_file`/`error_file`. Instead it must provide:

- `times` — **list of floats** (seconds, ascending): the solver/output time grid.
- `species` — **list of strings**: species recorded in the output profiles.

Required keys per entry: `temp` (K), `pres`, `cantera_tpl`, `times`, `species`, and exactly one of `initial_ratio` / `initial_concentration`. Optional: `pres_unit` (defaults to the global `pres_unit`). The composition syntax — including marking one species as `"base"` to auto-fill the remainder — is identical to `experiments`.

The unique temperatures/pressures across all `pp_experiments` define the MESS rate-coefficient grid used for extrapolation. Identical `cantera_tpl` files are de-duplicated, so each unique template becomes a single simulation array task.

**Example entry**:
```json
{
  "temp": 500,
  "pres": 1.0,
  "pres_unit": "bar",
  "cantera_tpl": "templates/reactor_template.py",
  "initial_ratio": {"CH4": 0.01, "O2": 0.21, "N2": "base"},
  "times": [0.0, 0.01, 0.02, 0.03],
  "species": ["CH4", "O2", "HO2", "CH3"]
}
```

### Ensemble tokens (`pp_ensembles`)

Each token specifies which models to extrapolate:

| Token syntax | Example | Meaning |
|---|---|---|
| `G####` (4 digits) | `G0005` | All models from a specific GA generation (e.g., generation 5). |
| `GT####` or `GT-#` | `GT0010`, `GT-1` | GOAT (elite) ensemble for a generation. `GT-1` → final/elite list. |
| `NM####` or `NM-#` | `NM0002`, `NM-1` | Best model from Nelder-Mead optimization for a specific NM generation. |
| `NMS` | `NMS` | Nelder-Mead Swarm — all final simplex members from the last NM run. |
| `NMSG####` | `NMSG0003` | All Nelder-Mead Swarm candidates from a specific GA generation (advanced). |

**TIP**: Ensembles are stored in the `SOP_DB` as tables named `G0001`, `NM0001`, etc. They must exist in your database for the postprocessing command to succeed. To get a GOAT ensemble, one can construct a GOAT object from the goats.txt file generated by the main run.

### Example postprocessing input

```json
{
  "mess_inputs": ["mess_input.inp"],
  "ct_yaml": "mechanism.yaml",
  "experiments": [...],
  "pp_experiments": [
    {
      "temp": 500,
      "pres": 1.0,
      "pres_unit": "bar",
      "cantera_tpl": "templates/reactor_template.py",
      "initial_ratio": {"CH4": 0.01, "O2": 0.21},
      "times": [0.00, 0.01, 0.02, 0.03],
      "species": ["CH4", "O2", "HO2", "CH3"]
    },
    {
      "temp": 600,
      "pres": 10.0,
      "pres_unit": "bar",
      "cantera_tpl": "templates/reactor_template.py",
      "initial_ratio": {"CH4": 0.01, "O2": 0.21},
      "times": [0.00, 0.01, 0.02, 0.03],
      "species": ["CH4", "O2", "HO2", "CH3"]
    }
  ],
  "pp_ensembles": ["G0001", "GT-1", "NM0005"]
}
```

### Output and results

Postprocessing does **not** create separate databases. Extrapolated results are written back into the **primary run databases** (`KMO_DB_KIN.db` and `KMO_DB_SIM.db`), into the **same per-generation tables** where the models were originally created:

1. **Rate coefficients** — written into `KMO_DB_KIN.db`, in the table named after the originating optimizer prefix and generation (`{prefix}{gen:04d}`, e.g. `G0003`, `NM0002`, `NMSG0001`).
   - Already-computed k(T, P) are **reused**: MESS is only re-run for the (P, T) conditions in `pp_experiments` that are not already present in the model's KIN table; missing conditions are computed and appended.
   - The `GT` token (GOATs ensemble) resolves to the originating optimizer's prefix (e.g. `G` for the genetic algorithm), so `GT` and the old `X` prefix never appear as table names.

2. **Simulation profiles** — appended into the existing `KMO_DB_SIM.db` tables for the same generation.
   - The postprocessing simulation is **always** run and saved because the initial composition differs from the original run.
   - Profiles are stored with **banded experiment ids** (offset past the original run's experiments), so the original run's simulation results are never overwritten.

> **Forward-only change**: earlier versions wrote separate `PP_DB_KIN.db` / `PP_DB_SIM.db` files with `X`-prefixed tables. Those files are no longer created, and old `X`-prefixed tables from prior runs are not migrated.

**Where files are saved**: All results are written to the run's `KMO_Project/` (or your configured `project_name`) directory, alongside the original databases. Intermediate job scripts (SLURM or local) and scratch files are created there.

### Workflow overview

1. **Validate pp settings** — check that all P/T/composition/time combinations are consistent.
2. **Open existing run databases** — SOP_DB, KIN_DB, SIM_DB from the original run.
3. **Load GOAT file** — read `workdir/goats.txt` to reconstruct elite ensembles.
4. **Loop over `pp_ensembles`**:
   - Resolve the token to its originating optimizer prefix and generation table.
   - Load models (SOP parameters) from the SOP_DB table matching the token.
   - Submit **rate-coefficient jobs** (MESS) only for (P, T) conditions missing from the model's KIN table, then append them into that table.
   - Submit **Cantera simulation jobs** to run reactor dynamics and append the profiles (with banded experiment ids) into the SIM table.
5. **Finalize** — no re-scoring; results are persisted as-is.


## 6) Resources

This section controls per-job SLURM resources and global scheduling limits.

| Keyword | Default value | Description |
|---|---|---|
| cpu_kin | 1 | CPUs requested per master-equation job. |
| mem_kin | 1000 | Memory (MB) per master-equation job. |
| cpu_sim | 1 | CPUs requested per simulation job. |
| mem_sim | 1000 | Memory (MB) per simulation job. |
| max_cpu | 2000 | Global CPU budget per generation/submission cycle. |
| max_mem | 1000000 | Global memory budget (MB) per generation/submission cycle. |
| max_jobs | 600 | Maximum submitted jobs for current KiMecO instance. |
| max_user_jobs | 1500 | Maximum submitted jobs for the current user. |
| exclude_nodes | "" | Comma-separated SLURM nodes to exclude. |
| q_name | none (required) | SLURM partition/queue name passed to #SBATCH -p. **Mandatory** (no default): the run is rejected if it is omitted. Validated live against the partitions reported by `sinfo`; if the requested partition is unavailable (or `sinfo` cannot be run) the run stops cleanly and lists the available partitions. Ensure SLURM is on `PATH`. In the `kmo_start` GUI this field is a dropdown auto-populated from the live `sinfo` partitions; on machines without SLURM (where `sinfo` is unavailable) it falls back to a free-text input. |


## Additional Global Keywords

These settings are still part of default_settings and therefore can appear in runtime settings if present in input JSON.

| Keyword | Default value | Description |
|---|---|---|
| scratch_base | dynamic path under /scratch/<user>/kmo/... | Base directory for simulation work. Generated dynamically at runtime import. |
| project_name | "KMO_Project" | Work directory/project folder name. |
| log_level | 20 (INFO) | Logging verbosity. |
| rc_software | "mess" | Master equation software backend selector. Currently the only other supported Master Equation backend. |
| use_automech | false | Optional rate-coefficient path. When false, KiMecO runs the standard single-pass MESS. When true, KiMecO emits a per-PES Python driver that uses automech's `mess_io` API to run MESS pass 1 and then checks the pass-1 output for well merging (missing rate coefficients); the extended pass 2 with automatic WellExtension well-lumping is run **only when well merging is detected**, otherwise the pass-1 result is kept as the final output. Requires `automech` (`autoio`/`mess_io`) installed in both the run and job environments; the run is cancelled early with a clear message if it is missing. The emitted driver also imports KiMecO itself, so `kimeco` must be importable in the job (compute-node) environment too. In the `kmo_start` GUI this appears under the "Rate Coefficients" category. |
| restart | "default" | Restart strategy for database/table handling. Only other possible value is "rescore". Will not produce new models but will rescore existing ones. Be sure you know what you're doing if changing this option. Backing up your databases ahead is recommended as the scores will be overwritten.|
| db_user | current username | Database user name. |
| db_host | "127.0.0.1" | Database host address. |
| threads | 1 | Main-process I/O thread count. Increase to run multiple NM instances during Nelder-Mead Swarm optimization. This option does not require MPI.|


## 7) Outputs

KiMecO writes both text outputs and SQLite databases.

### 7.1 Text output files

| File | Location | Content |
|---|---|---|
| KiMecO.log | Run launch directory (where `kmo input.json` is started) | Main run log. Contains progress messages, validation and initialization status, timing information, warnings, and errors (errors now include the full Python traceback). Existing log files are rotated with a date suffix when a new run starts with the same log filename. |
| score_info.txt | `KMO_Project/` (or your configured `project_name`) | Per-generation score summary for GOAT tracking. First line is a header (`ITER`, `BEST SCORE`, `GOAT AVERAGE`), followed by one row per generation with the best score and mean GOAT score. |
| goats.txt | `KMO_Project/` | GOAT membership history by generation. Each line corresponds to one generation and stores model tokens as `gen_id_model_id` pairs (for example `3_42`), representing the selected best models used as the GOAT ensemble for that generation. |
| GA_rates.out | `KMO_Project/` | Rate-statistics report written at GA convergence. Contains the selected model count after `max_score` filtering, then pressure/temperature-resolved tables of reaction rates (organized by PES), with geometric-mean and geometric-standard-deviation summaries across eligible models. |
| `{name}P{slot:02d}.out` | Per-job work directory | Final MESS rate-coefficient output for a PES slot. |
| `_{name}P{slot:02d}.out` | Per-job work directory | Transient MESS pass-1 output, written only when `use_automech=true`. The pass-1 result is always moved here first, but it only survives when well merging was detected: in that case it is the first-pass result kept before the automatic WellExtension well-lumping produces the extended pass-2 input whose result becomes `{name}P{slot:02d}.out`. When no well merging is detected, pass 2 is skipped and this file is moved back to `{name}P{slot:02d}.out`. |


### 7.2 Databases (run state and results)

Three SQLite databases are created in `KMO_Project/` and together contain the accumulated data necessary for restart and analysis. The databases contain one table per generation/iteration with names such as `G0001` for the first generation of a GA, `NM0001` for the first Nelder-Mead simplex and `NMS0001` for the first Nelder-Mead Swarm simplexes.

| Database | File name | Content |
|---|---|---|
| SOP_DB | `KMO_DB_SOP.db` | Contains the set of parameters (SOPs) for all models. Each row corresponds to one model and stores the full SOP parameter vector used to build kinetics/simulations. The columns are dynamically built depending on the system's parameters. Also contains SOP metadata (`__sop_item_pes_ids`) that maps SOP items to PES IDs to enforce restart consistency. |
| KIN_DB | `KMO_DB_KIN.db` | Contain the rate coefficients. Rows store pressure (`P`), temperature (`T`), model kinetics id (`kin_id`) , `pes_id`, `from_name`, `to_name`, and rate coefficient `k`. Tables are organized per generation/iterations as described above.|
| SIM_DB | `KMO_DB_SIM.db` | Simulation outputs for each model and experiment pair. Rows are keyed by (`mdl_id`, `experiment_id`) and store a binary `result` blob (Feather-encoded profile data). Currently, the content of the decoded result includes time and species profiles used for scoring and postprocessing. However, in the future, it will depend on the specific experimental data provided for the scoring. |

> **Postprocessing writes into these same databases.** Extrapolation no longer creates separate `PP_DB_KIN.db` / `PP_DB_SIM.db` files. Extrapolated rate coefficients are appended into the existing KIN tables for the originating generation (reusing any (P, T) already computed), and extrapolated simulations are appended into the existing SIM tables with **banded experiment ids** (offset past the original run's experiments) so nothing is overwritten. In the `kmoui` dashboard these appear from the unified SIM database and are labelled `Extrapolated (band b) — <experiment metadata>`.

The content of these databases is accessible from the **Databases** tab of the analysis GUI (`kmoui`): select one of the `.db` files in the run folder, pick a table to display it as a dataframe, and use the copy button to copy the table to the clipboard (tab separated) for pasting into a spreadsheet such as Excel.


## Extra Notes

- Mandatory top-level keys: mess_inputs, ct_yaml, experiments.
- Exactly one of initial_ratio or initial_concentration must be set for each experiment.
- Experiment pressure units are canonicalized and converted to Pa for cantera simulation; MESS pressure grid is built in bar.
- Ensembles (generations, GOAT, Nelder-Mead Swarm) are referenced by a tag name (e.g., G0001, GT-1, etc.) and must exist in the database for postprocessing to succeed.
- Postprocessing writes extrapolated results back into the primary run databases (`KMO_DB_KIN` / `KMO_DB_SIM`), into the same per-generation tables where the models were created; it no longer creates separate `PP_DB_KIN.db` / `PP_DB_SIM.db` files or `X`-prefixed tables. Already-computed rate coefficients are reused (only missing (P, T) conditions are recomputed), and extrapolated simulations are appended with banded experiment ids so the original run's results are never overwritten. This change is forward-only: pre-existing `PP_DB_*.db` files and old `X`-prefixed tables are not migrated.
- Inputs can be prepared using the command `kmo_start`, which will generate a JSON file with the correct structure and chosen values. The JSON can then be edited manually or reloaded into the GUI for further editing.
- While some analysis is possible using the GUI (called with keyword `kmoui`), it is still in development, and analysis of the results is best done using Jupyter notebooks or scripts that load the database and perform postprocessing.
- When `use_automech=true`, the emitted per-PES driver currently assumes the following physical-fidelity defaults when building the two-pass MESS input: Lennard-Jones collider masses (bath N2 = 28.0134, species = heaviest well mass), `edown_cutoff = 15.0`, well/TS rigid-rotor `sym_factor = 1.0`, Fourier-expansion hindered rotors are skipped, and electronic levels are parsed from the original MESS input (defaulting to a singlet `[[0.0, 1]]` when absent). Verify these are appropriate for your system before relying on the automech path.

