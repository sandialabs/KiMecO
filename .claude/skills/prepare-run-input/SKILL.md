---
name: prepare-run-input
description: "Prepare the input files for a KiMecO run: input.json, MESS input files, the Cantera mechanism, Cantera simulation templates, and experimental data and error CSVs. Use when setting up a new optimization or postprocessing run, adapting the example/ case, validating an input.json before submitting, adding a PES or an experiment, or building a configuration with the kmo_start launcher GUI."
---
# Prepare run input

## When to use

Setting up a new run directory, adapting `example/`, adding experiments or a PES, or checking an `input.json` before submission.

## Prerequisites

- A working env (`install-kimeco-env`) with `mess` on `PATH` to test MESS inputs.
- A run directory, preferably **outside the repository** (or under the gitignored `dev_tests/`).

## Steps

1. Start from the example:
   ```bash
   mkdir -p <run_dir> && cp <repo>/example/* <run_dir>/ && cd <run_dir>
   ```
   `example/` is the C2H5 + O2 case (`input.json`, `mess_input_ethyl_oxidation.inp`, `ThInK_Mech.yaml`, `concentration_time_isobar_adiabatic.tpl`, `pXtY.csv` / `epXtY.csv`). Its `input.json` has **no `q_name`**: add one or the run is rejected.
2. Mandatory keys (`mandatory_keys` in `kimeco/default_settings.py`): `mess_inputs` (list), `ct_yaml` (str), `experiments` (non-empty list), `q_name` (str, must be a partition listed by `sinfo`).
   Minimal skeleton (one experiment shown):
   ```json
   {
     "project_name": "my_run",
     "q_name": "<partition from sinfo>",
     "ct_yaml": "mechanism.yaml",
     "mess_inputs": ["pes1.inp"],
     "experiments": [
       {"temp": 550.0, "pres": 0.01, "pres_unit": "bar",
        "cantera_tpl": "concentration_time_isobar_adiabatic.tpl",
        "data_file": "p1t1.csv", "error_file": "ep1t1.csv",
        "initial_ratio": {"C2H5": 3.34e-5, "O2": 0.1, "HE": "base"}}
     ]
   }
   ```
3. Each experiment (`KMOInput.basic_checks` / `create_experiments`):
   - required: `temp` (K), `pres`, `cantera_tpl`, `data_file`, `error_file`;
   - exactly one of `initial_ratio` (mole fractions, sum ≤ 1) or `initial_concentration` (molecule/cm3); mark at most one species `"base"` to receive the remainder (if none is marked, the remainder goes to a species named `n2`);
   - optional: `weight` (number), `pres_unit` (default `bar`; Pa, kPa, MPa, mbar, atm, torr, psi accepted), `w_species` (per-species weights).
4. Data/error CSVs: first column header `time` (seconds) or `time[<unit>]` (e.g. `time[ms]`), then one column per species; data and error files must have matching headers and shape (`TimeProfile.validate_pair`). See `wiki/Mandatory-Keywords.md` section 1.3.2.
5. Cantera template: copy `example/concentration_time_isobar_adiabatic.tpl`. It is a Python `str.format` template and must contain every placeholder of `kimeco/templates/sim_arr_tpl.py`: `{input_file}`, `{init_loc}`, `{mdl_id}`, `{scratchdir}`, `{tbl_map_by_pes}`, `{rates_by_pes}`, `{all_tsteps}`, `{gen_name}` (`_validate_tpl` lists any that are missing). Literal braces in the Python code must be doubled (`{{`, `}}`).
6. MESS inputs: each file must run standalone:
   ```bash
   mess <file>.inp     # produces .out, .log, .aux like example/mess_input_ethyl_oxidation.*
   ```
   Rules enforced by `kimeco/readers/mess_input.py`: species names must exist in `ct_yaml` unless `force_new_molecules: true`; no name may contain `__`; a barrier name may appear in only one file; `Factor`, `Power`, the first `Epsilons` and the first `Sigmas` value must be identical across all files.
7. Paths: `data_file`, `error_file`, `cantera_tpl` are joined to the launch directory, so keep them relative and launch `kmo` from `<run_dir>`. `mess_inputs` and `ct_yaml` may be absolute or relative.
8. Optional: build/edit the JSON in the launcher GUI (Dash, port 8000):
   ```bash
   kmo_start [existing_config.json]
   ```
9. Optional postprocessing block: `pp_experiments` use the same schema minus `data_file`/`error_file`, plus `times` (non-empty, ascending) and `species` (non-empty list); see `postprocess-run-results`.
10. Submit with `submit-hpc-job`. There is no dry-run flag: `kmo input.json` validates the input first (errors go to `KiMecO.log` and the process exits), but a valid input immediately starts the optimization and submits jobs, so do not launch it interactively "just to check".

## Key files

- `kimeco/default_settings.py`, `kimeco/user_input.py`, `kimeco/experiments/t_profile.py`
- `kimeco/readers/mess_input.py`, `kimeco/templates/sim_arr_tpl.py`
- `example/`, `example/README.md`, `wiki/Mandatory-Keywords.md`, `wiki/Getting-Started.md`

## Checks & pitfalls

- `mess_inputs` order is part of the run identity: changing it on a restart makes `SOP_DB` raise `ValueError` ("item/PES_ID mapping that does not match"). To add a PES, append it to `mess_inputs` and start a fresh `project_name`.
- Tournament GA (`ga_type: "tournament"`) requires an even `n_mdl` (default `n_mdl` is 500, default `ga_type` is `"exp"`).
- A key with the wrong JSON type cancels the run (e.g. integer default given a float); unknown keys are silently ignored, so check spelling.
- Identical `cantera_tpl` contents are de-duplicated into one simulation script.

## Lane

Operational only when all files live outside the repository or under `dev_tests/`. Writing inputs into tracked paths (e.g. editing `example/`) is pipeline lane.
