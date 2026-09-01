# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added
- Optional automech-driven two-pass MESS (WellExtension) path in the rate-coefficient pipeline, gated by a new boolean keyword `use_automech` (default `false`). When `false`, the existing single-pass MESS behavior is unchanged (KiMecO renders `{name}P{slot:02d}.inp` and runs `mess ...inp`). When `true`, KiMecO instead emits a self-contained per-job Python driver `{name}P{slot:02d}.py` that embeds the SOP's PES data inline (reads no database at runtime, avoiding concurrency errors), drives automech's stateless `mess_io` API to run MESS pass 1, moves the pass-1 output aside to `_{name}P{slot:02d}.out`, and then runs pass 2 **only if wells are merging**: `MessOutputReader.well_merging` inspects the pass-1 output and, when a rate coefficient is missing, `mess_io.well_lumped_input_file` derives the WellExtension caps and MESS pass 2 produces the final `{name}P{slot:02d}.out`; when no well merging is detected, pass 2 is skipped and the pass-1 output is moved back to `{name}P{slot:02d}.out`. If pass 1 produces no output at all, the driver prints `MESS pass 1 produced no output {name}P{slot:02d}.out, aborting.` and exits with code 0, leaving the job unpicked for retry. The emitted script honors postprocessing partial re-runs (restricted `(P, T)` sub-grid) and reads external rotor and barrierless rotd/pp files from disk at runtime.
- New public method `MessOutputReader.well_merging(filename: str) -> bool` (a `@staticmethod`, no SOP/settings needed) returning `True` as soon as a rate coefficient is missing (`***`) for any P/T condition in the `Species-Species Rate Tables` of a MESS output, and `False` otherwise. Only the `Temperature = X K  Pressure = Y` tables are scanned; the high-pressure-limit blocks — where `***` entries are legitimate — are skipped. Raises `FileNotFoundError` on a nonexistent path.

### Change
- The automech driver's bar-to-atm pressure conversion now goes through the cantera unit registry (`cantera.with_units.cantera_units_registry`), as everywhere else in the code; the hard-coded `_BAR2ATM` factor is removed and no hard-coded unit-conversion factor remains under `kimeco/`.


## [1.1.7] - 2026-08-27

### Added
- New `fix_theory_divider` setting (default `false`). When `true`, the theory divider used to average the active parameters' scores is fixed for the whole run, so models with different numbers of active parameters are never compared under different dividers. Exposed in the `kmo_start` launcher GUI Sensitivity tab (with save/load round-trip).
- In the `kmo_start` launcher GUI, the Resources tab "Partition (queue)" field (`q_name`) is now a dropdown automatically populated from the machine's live SLURM partitions (via `sinfo`), making it easy to pick a valid, non-empty partition (now required by the backend). On machines without SLURM (where `sinfo` is unavailable) the field falls back to a free-text input so the value can still be entered by hand.
- New public method `Model.different_parameters(other: "Model") -> int` returning the integer count of parameters that differ between two models. It compares the two models' `sop.parameters_names` values with `~np.isclose(rtol=1e-6, atol=1e-8)`, excluding experimental score parameters (`Ptype.SCORE` / keys containing `score`), and assumes both models share the same parameter key set.
- `automech` (`autoio`/`mess_io`) is an optional dependency required only when `use_automech=true`; its `mess_io` modules are imported during user-input reading (guarded by `_check_automech` in `user_input.full_run_settings`) and the run is cancelled early with a clear message if unavailable. No import is attempted when `use_automech=false`. Because the emitted driver now imports `kimeco.readers.mess_output.MessOutputReader`, KiMecO itself must additionally be importable in the job (compute-node) environment when `use_automech=true`.

### Changed
- The batch-perturbation frequency formula is now `freq * bfc**(100/freq)`. This affects numeric results: prior batch-mode runs are not bit-for-bit comparable.
- `active_p` now skips only the **initial** sensitivity analysis and is preserved; on-the-fly sensitivity analysis during the GA still runs and augments `active_p` (previously `active_p` bypassed the sensitivity analysis entirely).
- The GOAT list is reset after addition of a new sensitive parameter, to ensure it only contains comparable models, obtained with the same scoring metric for the theory.
- The SLURM partition keyword `q_name` is now **mandatory** (added to `mandatory_keys`) and no longer has a default value (its former default `"day-long-cpu"` was removed from `default_settings`); an input that omits `q_name` is now rejected by the basic checks.
- `q_name` is now validated live against the available SLURM partitions via a new `_check_partition` guard (mirroring `_check_automech`) invoked from `user_input.full_run_settings`. The guard runs `sinfo` (stripping SLURM's trailing `*` default-partition marker, exact case-sensitive match); if the requested partition is not among the available ones the run stops cleanly with a warning listing the available partitions. Fail-closed: if `sinfo` cannot be run, the run is cancelled with an actionable message to ensure SLURM is on `PATH`.

### Fixed
- Per-slot job cleanup (`q_sys.clean_files`) no longer leaks `{base}P*.log` and `{base}P*.inp` files: the `.log` files are now removed on both success and failure (mirroring the existing `P*.aux` sweep), and the MESS `.inp` files are removed only on success (`PICKED_UP`), so failed jobs keep their inputs next to the retained `.py` drivers for resubmission.
- The automech driver no longer writes its pass-1 result directly under the final `{name}P{slot:02d}.out` name, closing a race where the main process could transiently read an un-lumped pass-1 output while pass 2 was still running.
- Sensitivity-analysis averaging (`Linear.average`) of multiplicative parameters (`if`, `freq`, `sfc`, `bfc`, `mrc`) is now a geometric mean (`exp(mean(log(values)))`) instead of a plain arithmetic mean, making the SA central/averaged model (id 0) — and thus the finite-difference base and final ranked sensitivities — consistent with the rest of the pipeline (GA, perturbator, scoring, Nelder-Mead), which treat multiplicative parameters in log space. Additive and percentage parameters keep the arithmetic mean. A `ValueError` is raised if a multiplicative parameter's value list is empty or contains a non-positive value.
- `run_sensitivity` log ordering is corrected so the "goat list has been reset" notice is actually emitted (previously the message was logged before the reset text was appended, so the notice was lost).
- The `kmo_start` launcher GUI no longer errors out when loading a saved configuration: a phantom perturbation control that was referenced but never rendered has been removed, so loading a config now reliably restores all fields instead of failing with a "nonexistent object" error.
- Validating the SOP setup in the `kmo_start` GUI before a mechanism has been loaded now shows the normal red validation message instead of raising an uncaught error, and no longer leaves a stray logging handler or altered log verbosity behind afterwards.
- Validating or loading a mechanism in the `kmo_start` GUI no longer fails with `Mechanism validation error: 'rc_pres'`. The mechanism-only validation path builds the model from default settings before the rate-constant pressure/temperature grid has been derived from the experiments, so those grids are now treated as optional (empty) during validation instead of raising a missing-key error. Full runs are unaffected.
- Loading or validating an SOP in the `kmo_start` GUI no longer fails with `Error loading SOP: 'rc_temp'`. The SOP-validation path builds the MESS input reader from default settings before the rate-constant temperature/pressure grid has been derived from the experiments, so those grids are now treated as optional (empty) during validation instead of raising a missing-key error. Full runs are unaffected.


## [1.1.6] - 2026-08-26

### Added
- Input validation now rejects an odd population size (`n_mdl`) when the GA tournament selection style (`ga_type='tournament'`) is chosen, since tournament pairing silently drops a model on odd populations. 
- The MESS input reader (`readers/mess_input.py`) now rejects any Well, Bimolecular, Barrier, or Fragment name containing the reserved parameter-name separator `__` (dbs), logging an error and stopping the run gracefully. This protects the `<item>__<ptype>` naming contract that all parameter-type parsing relies on.


### Fixed
- Parameter-type (Ptype) identification strengthened throughout the code.
- Genetic-algorithm convergence of multiplicative parameters is now evaluated with geometric means and std.


## [1.1.5] - 2026-08-25

### Fixed
- Multiplicative-parameter perturbation, trust boundaries, and derivative steps are now computed in log space, fully consistent with the (already log-space) theory scoring. In the multiplicative branch only (`if`, `sfc`, `mrc`, `bfc`, frequencies), the arithmetic factor `1 + (std - 1) * max_std` / `1 + (uc - 1) * step` is replaced by the geometric/power factor `std**max_std` / `uc**step`: `get_boundaries` returns `(value / std**max_std, value * std**max_std)`, `get_scale` uses log-space sigma `ln(uncertainty)`, and the SA/Nelder-Mead `calculate_dstep` uses factor `uc**step` (SA `step = lin_fact / sensi_d`, NM `step = nm_dstep`). As a result the theory score at the trust boundary equals `max_std**2` exactly, and the lognormal log-space sampling sigma `ln(uncertainty)` yields ±2/3/4 sigma coverage of 95.45/99.73/99.99%. Additive and percentage parameters and `scoring.py` are unchanged.

### Changed
- The multiplicative trust region is now **wider** than before for `uncertainty > 1` (intended correction of the above reconciliation). Prior multiplicative-run results are therefore not bit-for-bit comparable.

## [1.1.4] - 2026-08-25

### Added
- New user-settable input keyword `q_name` (default `day-long-cpu`) exposing the queuing system's queue/partition as a free-form string passed to SLURM via `#SBATCH -p`. Registered in `default_settings`, read by `QueueingSystem`, and surfaced in the launcher GUI (Resources section, with save/load round-trip) and the dashboard metadata.

### Fixed
- The direction-dependent sensitivity-analysis and Nelder-Mead derivative step now handles multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, frequencies) with a truly multiplicative, direction-dependent step: with factor `f = 1 + (uc - 1) * sensi_d` (Nelder-Mead uses `nm_dstep`), the up step (side `+1`) is `value * f` and the down step (side `-1`) is `value / f` (e.g. `uc=1.1`, `sensi_d=0.1` → steps `[1/1.01, 1.01]`). Previously the step keyed off the parameter's log-normal **distribution** rather than its **class** and applied a log-space scale additively, producing a wrong / symmetric step for multiplicative parameters. Additive and percentage parameters (`value + scale * sensi_d * side`) are unchanged. This is the perturbation-step counterpart of the log-space multiplicative scoring fix in [1.1.3].
- Genetic-algorithm convergence (`actualize_conv`) now measures multiplicative-parameter convergence in log space (`|ln(old / new)|` for both the mean and the standard deviation) against `param_conv`, instead of a percent-style relative change. Percentage and additive parameters are unchanged.

## [1.1.3] - 2026-08-24

### Fixed
- Per-parameter `specific_std` overrides now govern the perturbation **boundaries** (the trusted range), not only the sampling scale and scoring weight.
- Theory-score contribution for multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, frequencies) is now computed in log space as `(ln(value / reference) / ln(uncertainty))**2`, replacing the previous linear distance/scale. The penalty is now symmetric under a factor `f` versus its inverse `1/f` and consistent with the perturbator's log-normal (log-space) sampling of those parameters. Additive and percentage parameters are unchanged. This is the scoring-side counterpart of the log-space perturbation correction shipped in [1.1.2].


## [1.1.2] - 2026-08-24

### Fixed
- Fixed a bug where the postprocessing was reading rates from files on disk even when the rates are in db, potentially ready from MESS output calculated on a different P/T grid. This was causing a crash with an error P not in list, with P being the value in the file on disk not being in the postprocess conditions list. This is now bypassed, and the rates already in DB are always read from the DB.
- CI now installs the `agentic` extra (`pip install -e .[test,agentic]`) so the agentic-pipeline tests (`test_agentic_pipeline_ci.py`) are collected and run, instead of aborting collection with `ModuleNotFoundError: No module named 'anthropic'`.
- Multiplicative-parameter log-normal perturbation and the asymmetric sensitivity-analysis / Nelder-Mead derivative steps were moved off a value-dependent, additive log-space treatment onto a value-independent log-space sigma so that `±max_std·σ` coincides with the perturbation boundaries; removed dead `get_mean_sigma`. (Superseded in [Unreleased]: the multiplicative sigma is now `ln(uncertainty)` and the boundary factor is `uncertainty**max_std` rather than the earlier `log(1 + (std - 1) * max_std) / max_std` sigma and `1 + (std - 1) * max_std` boundary.)

### Changed
- Error log entries in the KiMecO logfile now include the full Python traceback. Every backend `try/except` that logged its error through `KMOLogger` now passes `exc_info=True`, so the traceback is appended after the message (log-line format unchanged). Postprocessing GOAT-load failures and `well.py` uncertainty-parsing errors now log with a traceback instead of writing to stderr / a bare `print`.
- Perturbation distribution validation is now enforced per parameter category. Multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, and individual/batch frequencies) accept only `log-normal` or `log-uniform`, while additive (`we`, `be`, `pow`) and percentage (`hrs`, `sigma`, `epsilon`, `fact`) parameters accept only `uniform` or `normal`. The backend now hard-fails invalid category/distribution combinations (previously only the additive class was checked), and the GUI perturbation dropdowns present only the valid distributions for each category.

## [1.1.1] - 2026-08-04

### Added
- In the example folder, the Analysis notebook now also shows how plot the extrapolated results (rate coefficients and concentration profiles).
- Agentic delivery pipeline for repository development: a multi-stage subagent workflow (clarification, scope assessment, planning, spec review, boundaries, CI testing, version control) coordinated by a workflow orchestrator. It ships both as Claude Code subagents under `.claude/agents/` (with `.claude/settings.json`) and as a standalone Python/Claude-API implementation under `agentic_pipeline/`, runnable from the repository root via `python -m agentic_pipeline.cli "<request>"`.
- New optional dependency group `agentic` in `pyproject.toml` (`anthropic>=0.69`, `pydantic>=2`, `pyyaml`) providing the packages needed to run the Python agentic pipeline (`pip install -e .[agentic]`).
- New public query helper `SIM_DB.get_exp_for_table(exp_id, table)` returning, for a given experiment id and generation table, a list of `(profile.T, species)` for every model in that table (read-only accessor for analysis/plotting of postprocessed/extrapolated experiment profiles).
- New public accessor `GOATs.get_exp_for_gen(exp_id, gen)` returning, for a given experiment id and GOAT generation snapshot, a list of `(profile.T, (table, mdl_id))` by resolving each ensemble member to its native generation table (`{prefix}{gen:04d}`) via `prepare_batch_select`/`batch_select`; this is the public API for retrieving an optimized-ensemble experiment's profiles across the members' native tables (needed for extrapolation analysis).

## [1.1.0] - 2026-08-04

### Added
- TimeProfile data/error CSVs now accept an optional bracketed time unit on the first-column header (e.g. `time[s]`, `TIME [ms]`, `time[1e-3s]`, `time[1e-3]`). The `time` token is case-insensitive and whitespace tolerant; Cantera time units plus `ms`/`millisecond(s)` aliases and numeric-factor forms are supported, with seconds assumed when no bracket is given. A new `TimeProfile.time` property exposes the seconds-normalized time grid.
- New public accessor `GOATs.get_goat_param_values(gen, cols)` returning `dict[str, np.ndarray]` of the requested SOP columns for a generation, in GOAT token order, without reconstructing models or running scoring (`gen == -1` selects the last generation; out-of-range raises `IndexError`).
- Each optimizer now exposes a class-level `prefix` attribute (`GeneticAlgorithm='G'`, `NelderMead='NM'`, `NelderMeadSwarm='NMSG'`) recoverable without instantiation, and a settings→optimizer-prefix resolver drives the postprocessing table and GOATs-ensemble prefix.
- `Model` and `SOP` objects now support value equality and hashing. Two `Model`s are equal when they share the same `SOP`, status, generation and id (hash derived from the SOP parameters, generation and id); two `SOP`s are equal when their `parameters_names` are identical.

### Changed
- Postprocessing/extrapolation now writes results into the primary run databases (`KMO_DB_SOP` / `KMO_DB_KIN` / `KMO_DB_SIM`) instead of separate extrapolation databases. Extrapolated rate coefficients and simulations are stored in the same per-generation tables where the model was originally created (`{optimizer_prefix}{gen:04d}`, e.g. `G0003`, `NM0002`, `NMSG0001`); the `GT` token (GOATs ensemble) now resolves to the originating optimizer's prefix (e.g. `G` for the genetic algorithm), so `GT` and `X` never appear as table names.
- Extrapolation now reuses already-computed rate coefficients: if a postprocessing experiment's (P, T) already exists in the model's KIN table, MESS is not re-run for it, and only missing (P, T) conditions are computed and appended. The postprocessing simulation is always run and saved because the initial composition differs.
- Postprocessing simulations are appended into the existing SIM tables with banded experiment ids (offset past the original run's experiments), so the original run's simulation results are never overwritten.
- The postprocessing log (`set_postprocessing`) now prints the metadata of each `pp_experiment` (type, temperature, pressure, species, composition) instead of the flat `pp_temp` / `pp_pres` grids.
- The `kmoui` dashboard now reads extrapolated simulations from the unified SIM database; extrapolated experiments are labelled `Extrapolated (band b) — <experiment metadata>` in the simulations and database views.
- The SOP GUI plotting subsection ("Type of parameter to plot" → Plot) now fetches each selected generation's data once for all selected columns instead of reconstructing full SOP/Model objects and running scoring per parameter, making parameter plotting much faster. Plotted values (including the Score parameter) are byte-identical to before and the UX is unchanged (one overlaid-histogram figure per selected column).
- Internal `GOATs.get_goat_for_gen` row matching reduced from O(n²) to O(n) via an id→row map, and `GOATs.get_p_for_gen` optimized in place; observable behavior is unchanged (rows now returned in deterministic GOAT token order, identical shapes/dtypes and error contracts).
- API note: `database.sop_db.batch_select_cols` now returns an id-keyed `dict` of the form `{table: {row_id: (col_values...)}}` (the row id is included in each entry) and no longer emits an empty `.where()` clause.
- TimeProfile time grids are normalized to seconds on read (species columns untouched), and data/error files may declare different time units as long as their converted-seconds grids match (compared with a numerical tolerance).
- In the GUI KIN section, reaction pair selection now uses only wells and bimolecular species (fragments excluded), labels entries as `NAME [PES XX]`, enforces same-PES `From`/`To` pairing with reciprocal filtering and auto-clear of invalid selections, and blocks invalid cross-PES plotting with an explanatory message.
- In the GUI SIM section ("Concentration profiles"), selection is now driven by a single multi-select **experiment** dropdown instead of separate pressure/temperature/species controls. Each entry is labelled with its experiment metadata (for `TimeProfile` experiments: pressure converted Pa→bar with unit, temperature in K, and the measured species, e.g. `Time profile #3 — 1.013 bar, 300 K — A, B`; other experiment types fall back to `{exp_type} #{id}`). Selecting an experiment automatically produces a separate figure per measured species, each heading naming both the species and the experiment. The change is GUI-layer only; experiment classes, the SIM-DB schema, and settings keys are unchanged.
- A GOAT-load failure in postprocessing (`set_postprocessing`) now surfaces loudly: instead of silently `continue`-ing past a token, it prints the traceback and raises `ValueError`, so a failed ensemble/band is no longer silently dropped.

### Removed
- The separate postprocessing databases `PP_DB_KIN.db` and `PP_DB_SIM.db` are no longer created; extrapolation results now live in the primary run databases. The `PP` simulation source in the `kmoui` dashboard is removed accordingly.
- The `X`-prefixed extrapolation tables (e.g. `XG0001`, `XGT0005`, `XNM0001`) are removed; the `X` and `GT` tokens no longer appear as table names. This change is forward-only: existing `PP_DB_*.db` files and old `X`-prefixed tables from prior runs are not migrated.

### Fixed
- Plotting the `Score` parameter in the SOP GUI subsection ("Type of parameter to plot" → Plot) no longer raises `NotImplementedError: Parameter not parametrised.`. The `Score` output is a computed value (not a perturbed parameter), so `get_boundaries` now returns a `[0.0, init_val]` range for it instead of querying the perturbator, and its histogram plots correctly. Non-score parameters are unaffected.
- The `Score`-column histogram in the SOP GUI subsection ("Type of parameter to plot" → Plot) no longer draws the brown perturbation-boundary vertical lines; since a score is a computed output rather than a constrained/perturbed parameter it has no boundaries, so only the black init-value line is shown. Non-score parameters still draw their brown boundary lines as before.
- SOP parameter plotting in the analysis GUI no longer risks crashing from memory exhaustion, since it no longer redundantly rebuilds models and rescores once per selected parameter before plotting.
- Postprocessing the optimized (GOAT / `GT`) ensemble no longer crashes with a `KeyError` (e.g. `'exp_012'`) during scoring: the experiment-scoring loop now skips experiments whose name has no cached score in `mdl.sop.scores`, which is the case for the `pp_experiments` swapped in during postprocessing.
- When postprocess mode reuses an already-persisted (P, T) rate-coefficient grid (`missing_grid` is `False`), `CoreRun` now calls `mdl.rateCoef.recover_rslts()` before marking the model `KIN`, so the cached rate-coefficient results are actually recovered/loaded instead of left unpopulated.

## [1.0.4] - 2026-07-23

### Added
- Analysis notebook for the ethyl oxidation example included in the `example` folder.
- QoL improvements to the experiment class, allowing easy plotting of TimeProfile type experiments in a jupyter notebook.

### Fixed
- Bug in the scoring module that caused the count of active parameters to be incorrectly computed. The issue has been resolved, and the count of active parameters is now independent from the active parameter list used by the perturbation and updated by the sensitivity analysis.

## [1.0.3] - 2026-07-21

### Added
- Sensitivity analysis can restart with frozen parameters.

### Fixed
- Two-sided derivatives properly skipped for frozen parameters in the linear sensitivity analysis.
- Minor bug fix in the scoring module to correctly compute the experimental score when species weights are applied.

## [1.0.2] - 2026-07-20

### Added
- Frozen parameters can now be specified in the input JSON file using the `fixed_params` key. This allows users to exclude certain parameters from being perturbed during optimization.
- Working example for ethyl oxidation with frozen parameters included in the `example` folder.

## [1.0.1] - 2026-07-14

### Added
- Visualization and export of KMO databases in the database tab of the GUI.
- Improved score printing for clearer run output.

### Fixed
- Minor print formatting issue.

### Changed
- Unified the package version across `pyproject.toml`, `setup.py`, and `meta.yaml`.

## [1.0.0] - 2024

### Added
- Initial public release of KiMecO (Kinetic Mechanism Optimizer).

[1.1.7]: https://github.com/sandialabs/KiMecO/compare/v1.1.6...v1.1.7
[1.1.6]: https://github.com/sandialabs/KiMecO/compare/v1.1.5...v1.1.6
[1.1.5]: https://github.com/sandialabs/KiMecO/compare/v1.1.4...v1.1.5
[1.1.4]: https://github.com/sandialabs/KiMecO/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/sandialabs/KiMecO/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/sandialabs/KiMecO/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/sandialabs/KiMecO/compare/v1.0.4...v1.1.1
[1.1.0]: https://github.com/sandialabs/KiMecO/compare/v1.0.4...v1.1.0
[1.0.4]: https://github.com/sandialabs/KiMecO/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/sandialabs/KiMecO/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/sandialabs/KiMecO/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/sandialabs/KiMecO/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/sandialabs/KiMecO/releases/tag/v1.0.0
[Unreleased]: https://github.com/sandialabs/KiMecO/compare/v1.1.6...HEAD
