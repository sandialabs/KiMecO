---
name: submit-hpc-job
description: "Submit and monitor a KiMecO optimization run on a Slurm cluster. Use when the user wants to launch `kmo input.json` as a batch job, write or adapt the master submission script, check job or queue status with squeue/sacct, size the per-job resources KiMecO requests (cpu_kin, mem_kin, cpu_sim, mem_sim, max_cpu, max_mem, max_jobs, max_user_jobs, exclude_nodes, q_name, scratch_base), or triage failed or stuck array jobs (empty outputs, 'Missing files for', 'Failed to submit', 'SLURM submission script missing'). Slurm only."
allowed-tools: Bash(sbatch *) Bash(squeue *) Bash(sacct *)
---
# Submit a KiMecO run on HPC (Slurm)

## When to use

Launching or babysitting `kmo input.json` on a Slurm cluster, sizing resources, or diagnosing array jobs KiMecO submits. KiMecO only supports Slurm (`QueueingSystem` raises `NotImplementedError` otherwise).

## Prerequisites

- A validated run directory (see `prepare-run-input`). Launch **from that directory**: `KMOInput` sets `init_loc` to the launch directory and `workdir = init_loc + project_name`. `data_file`, `error_file`, `cantera_tpl` are joined to `init_loc`, so keep them relative; `mess_inputs` and `ct_yaml` may be absolute or relative.
- `q_name` set in `input.json` (mandatory). It is checked against `sinfo` by `_check_partition`; if `sinfo` cannot run, the run is cancelled.
- On compute nodes: the same conda env, `mess` on `PATH`, and `sinfo` on `PATH` (simulation jobs re-create `KiMecO(...)`, which re-runs the full input validation including `_check_partition`). If `use_automech` is true, `mess_io` must import there too.
- `scratch_base` writable from compute nodes (default `/scratch/$USER/kmo/<timestamp>_<rand>/`).

## Steps

1. Copy the master script into the run directory:
   ```bash
   cp <repo>/example/submit_kmo.slurm ./submit_kmo.slurm
   ```
   It contains `-N 1`, `--ntasks=1`, `-q medium`, `-p week-long-cpu`, `--mem=500`, `OMP_NUM_THREADS=1`, and `/usr/bin/time -v kmo input.json`. `medium` / `week-long-cpu` are the maintainer's cluster values: replace them with `<qos>` / `<partition>` valid on your cluster. The master job runs for the whole optimization, so give it a long walltime partition.
2. Make the environment available in the master job. Generated job scripts do **not** activate conda; they inherit the master job's environment. The variant `tests/parse_pes/dme/kmo_dme.slurm` adds:
   ```bash
   source ~/.bashrc
   conda activate <env>
   ```
   It also writes `-o logs/input.stdout` — if you use that, run `mkdir -p logs` first.
3. Submit and check:
   ```bash
   sbatch submit_kmo.slurm
   squeue -u $USER
   sacct -j <jobid> --format=JobID,State,Elapsed,MaxRSS
   ```
4. Size resources in `input.json` (defaults from `kimeco/default_settings.py`):

   | Key | Default | Meaning |
   | --- | --- | --- |
   | `cpu_kin` / `mem_kin` | 1 / 1000 MB | per MESS array task |
   | `cpu_sim` / `mem_sim` | 1 / 1000 MB | per Cantera array task |
   | `max_cpu` / `max_mem` | 2000 / 1000000 MB | budget for running KiMecO jobs |
   | `max_jobs` | 600 | jobs for this KiMecO instance |
   | `max_user_jobs` | 1500 | all jobs of `$USER` (from `squeue`) |
   | `exclude_nodes` | `""` | `--exclude=` list |

   `QueueingSystem.enough_resources_for` only submits a job when all four budgets (jobs, user jobs, CPU, memory) can absorb the whole array (`n_pes` tasks for kin, `n_exp` tasks for sim).

## What KiMecO submits

- Scripts are written to `<workdir>/<TABLE>/<id//50 as 2 digits>/<name>.slurm` (e.g. `KMO_Project/G0003/01/`), built from `kimeco/templates/slurm_arr.py`: `--array`, `--cpus-per-task`, hard-coded `-q medium`, `--exclude`, `-p {q_name}`, `--mem`; no `--time` (partition default applies). Logs go to `logs/<name>_%a.stdout|.err` next to the script.
- Kin jobs run `mess <name>P${ID}.inp` (`templates/kin_arr_tpl.py`), or `python <name>P${ID}.py` when `use_automech` is true (`templates/kin_arr_py_tpl.py`).
- Sim jobs run `python <name>_expNN.py $SLURM_ARRAY_TASK_ID` (`templates/pyjobarray.py`), writing JSON under `scratch_base + project_name`, then `mv` it back.
- Submission uses `sbatch <name>.slurm`; polling uses `squeue -u $USER --format="%.20F"`.
- `JobStatus` (`kimeco/q_sys.py`): `ready`, `running`, `finished`, `pickedUp`, `fail`, `notInQueue`.

## Monitoring

- `KiMecO.log` in the launch directory (an existing log is renamed with a timestamp when a new run starts).
- `<workdir>/<TABLE>/<NN>/logs/*.stdout|*.err` for array tasks; `E####_sims.log` per simulation model (written in the job folder the array runs from).
- `<workdir>/score_info.txt` (best score / GOAT average per generation) and `<workdir>/goats.txt`.

## Checks & pitfalls

- Non-empty kin `.err` → job marked `fail`, outputs removed, model re-queued.
- `SLURM submission script missing for ...` / `Missing files for ...` → `submit()` waited ~10 s for the script or its inputs and gave up for this cycle; check disk/quotas in `<workdir>`.
- `Failed to submit <name>: ...` → `sbatch` returned non-zero; the job stays `ready` and is retried on the next cycle. Check `q_name`, QoS, and account limits.
- `<out> not found after 20s.` → MESS output not there yet; `<out> is empty after 2 minutes.` → raises `FileNotFoundError`. Inspect the matching `.err`/`.log` (see `compute-mess-rates`).
- `Missing file: ...S##.json - resubmitting` → sim JSON missing after 30 s; check `scratch_base` permissions and sim `.err`.
- `scancel` is **not** pre-approved: always ask the user before cancelling jobs.

## Lane

Operational only if the run directory is outside the repository or under the gitignored `dev_tests/`; a run inside the repo creates non-ignored files, so use the pipeline lane or relocate the run.
