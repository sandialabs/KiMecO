# 7) Outputs

KiMecO writes both text outputs and SQLite databases.

## 7.1 Text output files

| File | Location | Content |
|---|---|---|
| KiMecO.log | Run launch directory (where `kmo input.json` is started) | Main run log. Contains progress messages, validation and initialization status, timing information, warnings, and errors. Existing log files are rotated with a date suffix when a new run starts with the same log filename. |
| score_info.txt | `KMO_Project/` (or your configured `project_name`) | Per-generation score summary for GOAT tracking. First line is a header (`ITER`, `BEST SCORE`, `GOAT AVERAGE`), followed by one row per generation with the best score and mean GOAT score. |
| goats.txt | `KMO_Project/` | GOAT membership history by generation. Each line corresponds to one generation and stores model tokens as `gen_id_model_id` pairs (for example `3_42`), representing the selected best models used as the GOAT ensemble for that generation. |
| GA_rates.out | `KMO_Project/` | Rate-statistics report written at GA convergence. Contains the selected model count after `max_score` filtering, then pressure/temperature-resolved tables of reaction rates (organized by PES), with geometric-mean and geometric-standard-deviation summaries across eligible models. |


## 7.2 Databases (run state and results)

Three SQLite databases are created in `KMO_Project/` and together contain the accumulated data necessary for restart and analysis. The databases contain one table per generation/iteration with names such as `G0001` for the first generation of a GA, `NM0001` for the first Nelder-Mead simplex and `NMS0001` for the first Nelder-Mead Swarm simplexes.

| Database | File name | Content |
|---|---|---|
| SOP_DB | `KMO_DB_SOP.db` | Contains the set of parameters (SOPs) for all models. Each row corresponds to one model and stores the full SOP parameter vector used to build kinetics/simulations. The columns are dynamically built depending on the system's parameters. Also contains SOP metadata (`__sop_item_pes_ids`) that maps SOP items to PES IDs to enforce restart consistency. |
| KIN_DB | `KMO_DB_KIN.db` | Contain the rate coefficients. Rows store pressure (`P`), temperature (`T`), model kinetics id (`kin_id`) , `pes_id`, `from_name`, `to_name`, and rate coefficient `k`. Tables are organized per generation/iterations as described above.|
| SIM_DB | `KMO_DB_SIM.db` | Simulation outputs for each model and experiment pair. Rows are keyed by (`mdl_id`, `experiment_id`) and store a binary `result` blob (Feather-encoded profile data). Currently, the content of the decoded result includes time and species profiles used for scoring and postprocessing. However, in the future, it will depend on the specific experimental data provided for the scoring. |

The content of these databases is accessible from the **Databases** tab of the analysis GUI (`kmoui`): select one of the `.db` files in the run folder, pick a table to display it as a dataframe, and use the copy button to copy the table to the clipboard (tab separated) for pasting into a spreadsheet such as Excel.
