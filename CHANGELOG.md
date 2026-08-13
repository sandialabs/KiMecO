# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Perturbation boundaries for multiplicative parameters (`if`, `sfc`, `mrc`, `bfc`, `freq`) are now geometric: the `max_std`-sigma wall of a lognormal prior with uncertainty factor `f` sits at `i_val * f**max_std` instead of `i_val * (1 + (f-1)*max_std)`. The previous linear form is the correct wall for a *normal* proposal, but all five multiplicative types default to `log-normal`, and it placed the wall short of the requested `max_std` — increasingly so as `f` grows (at `max_std = 4`: 3.74 sigma for `f = 1.05`, 2.32 sigma for `f = 2`, 1.57 sigma for `f = 10`). This widens the sampled volume (9x to 81x at `f = 3`), so runs made with earlier versions will not reproduce.
- Sampling a `log-normal` distribution for an additive parameter (`we`, `be`, `pow`) now raises `TypeError` instead of silently taking `log()` of a possibly negative energy.

### Fixed
- The `log-normal` branch of the perturbator converted the distribution's location to log space but passed `get_scale`'s linear-space spread, `(f-1)*value`, through unchanged as the scale of a normal in log space; the sigma actually used therefore scaled with the parameter's magnitude. The correct log-space sigma is `ln(f)`, with no dependence on the value. A new `Perturbator.get_log_scale` supplies it; `get_scale` is unchanged and still serves the `normal` branch and the derivative steps in the linear sensitivity and Nelder-Mead modules.
- As a consequence of the above, the imaginary frequency `if` — the only multiplicative parameter carrying a physical value rather than a coefficient of order 1 — was effectively not being sampled from its intended distribution. At a realistic 1000 cm-1 with `f = 1.1` the log-space sigma used was 100 rather than 0.095, so draws spanned tens of orders of magnitude, were rejected against the boundaries by the retry loop in `perturb_ifreq`, and what survived was uniform in log across the allowed band (Kolmogorov-Smirnov against Uniform(0,1) in log space: D = 0.005, p = 0.68) at a cost of some 370 rejected draws per accepted sample. Coefficient-valued multiplicative parameters were only mildly affected, since `(f-1)*x` approximates `ln(f)` when `x` is near 1.

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

### Removed
- The separate postprocessing databases `PP_DB_KIN.db` and `PP_DB_SIM.db` are no longer created; extrapolation results now live in the primary run databases. The `PP` simulation source in the `kmoui` dashboard is removed accordingly.
- The `X`-prefixed extrapolation tables (e.g. `XG0001`, `XGT0005`, `XNM0001`) are removed; the `X` and `GT` tokens no longer appear as table names. This change is forward-only: existing `PP_DB_*.db` files and old `X`-prefixed tables from prior runs are not migrated.

### Fixed
- Plotting the `Score` parameter in the SOP GUI subsection ("Type of parameter to plot" → Plot) no longer raises `NotImplementedError: Parameter not parametrised.`. The `Score` output is a computed value (not a perturbed parameter), so `get_boundaries` now returns a `[0.0, init_val]` range for it instead of querying the perturbator, and its histogram plots correctly. Non-score parameters are unaffected.
- The `Score`-column histogram in the SOP GUI subsection ("Type of parameter to plot" → Plot) no longer draws the brown perturbation-boundary vertical lines; since a score is a computed output rather than a constrained/perturbed parameter it has no boundaries, so only the black init-value line is shown. Non-score parameters still draw their brown boundary lines as before.
- SOP parameter plotting in the analysis GUI no longer risks crashing from memory exhaustion, since it no longer redundantly rebuilds models and rescores once per selected parameter before plotting.

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

[1.0.4]: https://github.com/sandialabs/KiMecO/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/sandialabs/KiMecO/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/sandialabs/KiMecO/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/sandialabs/KiMecO/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/sandialabs/KiMecO/releases/tag/v1.0.0
[Unreleased]: https://github.com/sandialabs/KiMecO/compare/v1.0.4...HEAD
