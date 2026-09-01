# Additional Global Keywords

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
