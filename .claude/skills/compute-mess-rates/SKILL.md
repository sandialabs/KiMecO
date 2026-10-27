---
name: compute-mess-rates
description: "Compute and check master-equation rate coefficients with MESS inside KiMecO. Use when running or debugging MESS for a model (the default single-pass input or the use_automech two-pass driver), checking that a MESS input runs standalone, understanding how SOP parameters are written into <name>P<NN>.inp files, or diagnosing failed, empty, negative, or NaN rate results in KMO_DB_KIN."
---
# Compute MESS rate coefficients

## When to use

Checking that a MESS input works, understanding the files KiMecO generates per model, or diagnosing rate-coefficient failures (missing/empty `.out`, NaN, all-zero rates).

## Prerequisites

- `mess` on `PATH` (`which mess`; see `install-kimeco-env`). `rc_software` must be `"mess"` (any other value raises `NotImplementedError` in `kimeco/rate_coef.py`).
- For `use_automech: true`: `mess_io` importable on the compute nodes (`_check_automech` only checks the launch env).

## Pipeline inside KiMecO

1. `MessInputReader` (`kimeco/readers/mess_input.py`) parses each file in `mess_inputs` into the initial SOP and a template; `KiMecO.copy_necessary_files` writes the templates as `<workdir>/mess_tpl_PES{NN}`. Several files give one SOP (shared items carry several `pes_ids`, file index = PES id); each file's side outputs are named after its input (`<stem>.out`, `<stem>_ped.out`, `<stem>_ke.out`) so slots in one job directory do not collide.
2. For each model, `RateCo.create_input` writes one input per PES slot into `<workdir>/<TABLE>/<id//50:02d>/`:
   - default: `MessWriter` (`kimeco/writers/mess.py`) → `<name>P<NN>.inp`, starting with one `!<param>: <value>` comment line per SOP parameter, then the filled template;
   - `use_automech: true`: `AutomechKinWriter` (`kimeco/writers/automech_kin.py`) → self-contained driver `<name>P<NN>.py`. It writes pass 1 (no WellExtension), runs `mess`, copies the output to `_<name>P<NN>.out`, calls `mess_io.well_lumped_input_file`, rewrites the input, and runs `mess` again for the final `<name>P<NN>.out`.
3. The Slurm array task runs `mess <name>P${ID}.inp` (`kimeco/templates/kin_arr_tpl.py`) or `python <name>P${ID}.py` (`kin_arr_py_tpl.py`); see `submit-hpc-job`.
4. `RateCo.recover_rslts` reads each `.out` with `MessOutputReader` (`kimeco/readers/mess_output.py`), sets negative rates to 0, marks the job `FAILED` if any rate is NaN, and builds `KMO_DB_KIN` rows `(P, T, kin_id, pes_id, from_name, to_name, k)`.
5. Rotor/rotd side files listed in `SOP.files2copy` are copied to `<workdir>` and symlinked into each job subfolder.

## Steps — check an input standalone

1. Work in a scratch directory outside the repo:
   ```bash
   mkdir -p <scratch> && cp <file>.inp <rotor/rotd files> <scratch>/ && cd <scratch>
   mess <file>.inp
   ls  # expect <file>.out, <file>.log, <file>.aux
   ```
   Compare with `example/mess_input_ethyl_oxidation.{inp,out,log,aux}`.
2. Re-run a failed model's generated input in its job folder copy:
   ```bash
   cp <workdir>/G0003/01/<name>P00.inp <scratch>/ && cd <scratch> && mess <name>P00.inp
   ```
   The `!param: value` header shows exactly which perturbed values produced the failure.
3. For automech drivers, run `python <name>P00.py` in a copy; the driver calls `subprocess.run(["mess", ...], check=False)`, so MESS errors do **not** stop it — inspect `<name>P00.log`/`.out` and `_<name>P00.out` (pass 1).

## Key files

- `kimeco/rate_coef.py`, `kimeco/q_sys.py`, `kimeco/core.py`
- `kimeco/readers/mess_input.py`, `kimeco/readers/mess_output.py`
- `kimeco/writers/mess.py`, `kimeco/writers/automech_kin.py`
- `kimeco/templates/kin_arr_tpl.py`, `kimeco/templates/kin_arr_py_tpl.py`
- `wiki/Outputs.md` (KIN_DB columns, `_<name>P<NN>.out`)

## Checks & pitfalls

- `<out> not found after 20s.` → the result is not there yet; recovery returns no rows and is retried.
- `<out> is empty after 2 minutes.` → `FileNotFoundError`; check the array task `.err` in `logs/` and the MESS `.log`.
- A non-empty array `.err` marks the kin job `fail` and deletes its `.out` files before resubmission.
- `NaN detected in rate coefficients` → model reset; "The master equation likely didn't converge properly." Inspect the `.log` for that model's parameters (often extreme perturbed energies; consider `max_std`/`std_*`).
- All-zero rates for a pair usually mean the species name in MESS does not match the mechanism or the pair is absent from the output table map.
- Do not edit generated `.inp` files in place inside a running workdir; KiMecO may resubmit them.

## Lane

Operational for standalone checks run outside the repository (or in `dev_tests/`). Changing readers/writers/templates is pipeline lane.
