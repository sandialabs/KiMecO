---
name: add-settings-keyword
description: "Add or change a KiMecO input/settings keyword end-to-end. Use when introducing a new input.json key, changing a keyword's default, type, or validation, renaming or removing a setting, or exposing a setting in the kmo_start launcher GUI. Walks the lockstep contract: default_settings.py, user_input.py, every consumer of settings['key'], the kmo_start control and config store, the save/load round-trip and its arity test, parameters_metadata.py, wiki/MANUAL/CHANGELOG, and tests."
---
# Add or change a settings keyword

## When to use

Any change to the set of `input.json` keys or to a key's default, type, allowed values, or GUI exposure. This is a cross-system contract: every layer below moves together.

## Prerequisites

- An approved spec and validated boundaries (pipeline lane). Decide with the user: default value and type, mandatory or optional, GUI tab (if any), and whether existing runs must keep working.
- Worked example to copy: `fix_theory_divider` (default, Sensitivity tab checkbox, save/load, scoring consumer, wiki + MANUAL).

## Steps

1. **Register the default** in `kimeco/default_settings.py`:
   - optional key → `default_settings[...]`, with a comment above it;
   - mandatory key → `mandatory_keys[...]` (only presence and `isinstance` are checked in `basic_checks`).
2. **Pick the default's Python type deliberately** — it drives validation. `KMOInput.set_default_values` cancels the run when `not isinstance(user_value, type(default))`, with one exception: an `int` is accepted where the default is a `float`. So a default of `1` rejects `1.5`, a default of `1.0` accepts `1` and `1.5`, a list default requires a JSON list, a dict default requires an object. `bool` passes for an `int` default (Python subclass).
3. **Add parsing in `kimeco/user_input.py` only if needed**: enum conversion (see `distrib_*`, `freq_mode`, `optimizer` in `set_default_values`, `restart` in `other_checks_to_modif`), cross-field checks (e.g. tournament GA needs even `n_mdl`), or environment guards in `full_run_settings` (`_check_automech`, `_check_partition`). Unknown keys are only info-logged by `check_unknown_kwords`, so a misspelt key is silently ignored.
4. **Update every consumer**:
   ```bash
   grep -rn "settings\['<key>'\]\|settings\[\"<key>\"\]\|settings.get('<key>'" kimeco/
   ```
   Remember the settings are re-parsed by `full_run_settings` in other processes too: simulation job scripts (`KiMecO(..., sim_job=True)` from the Cantera template), `kmoui` (`kimeco/gui/kimecoapp.py`), and `kmopp` (`kimeco/postprocessing/postprocess.py`). A guard that needs local resources runs there as well.
5. **Expose it in the `kmo_start` GUI** (if user-facing): add the control in `kimeco/gui/input_sections/<tab>_section.py` and write it into the tab's store in the section callback (`sensitivity-config-store`, `optimizer-config-store`, `perturbation-config-store`, or `resources-config-store`).
6. **Keep save/load in sync** in `kimeco/gui/input_sections/save_load_write_section.py`: `_build_user_settings` (start from `default_settings`, merge stores) and `load_config_to_gui`, whose `Output(...)` list and returned tuple are order-matched.
7. **Bump the arity test in lockstep**: `tests/unit/test_save_load_output_arity_ci.py` asserts `DECLARED == 69` (current value). Adding an `Output` changes it; coordinate with `ci-test`.
8. **Metadata**: add the key to `PARAMETER_DESCRIPTIONS` and `PARAMETER_CATEGORIES` in `kimeco/gui/parameters_metadata.py` (not imported by other modules at the moment — keep it consistent anyway).
9. **Docs** (via `version-control`): the matching wiki keyword page — `wiki/Mandatory-Keywords.md`, `Additional-Global-Keywords.md`, `Optimizer.md`, `Sensitivity-Analysis.md`, `Theoretical-Uncertainties.md`, `Resources.md`, or `Postprocessing.md` — the mirrored section of `MANUAL.md`, and a `CHANGELOG.md` `[Unreleased]` bullet.
10. **Tests** (designed by `ci-test`): default present after `set_default_values`; wrong type sets `cancel_run`; enum/cross-field validation; GUI save → load round-trip; arity.
11. Run `python -m pytest tests/unit/ -q` (see `run-tests`).

## Lockstep checklist

```text
[ ] default_settings.py (default_settings or mandatory_keys, with comment)
[ ] user_input.py (only if enum/cross-field/guard needed)
[ ] all consumers of the key in kimeco/
[ ] kmo_start control + config store callback
[ ] save_load_write_section.py: _build_user_settings + load_config_to_gui
[ ] tests/unit/test_save_load_output_arity_ci.py DECLARED (if an Output was added)
[ ] parameters_metadata.py descriptions/categories
[ ] wiki page + MANUAL.md + CHANGELOG [Unreleased]
[ ] unit tests designed by ci-test, suite green
```

## Key files

- `kimeco/default_settings.py`, `kimeco/user_input.py`, `kimeco/enums.py`
- `kimeco/gui/kmo_start.py`, `kimeco/gui/input_sections/*_section.py`, `kimeco/gui/input_sections/save_load_write_section.py`, `kimeco/gui/parameters_metadata.py`
- `tests/unit/test_save_load_output_arity_ci.py`, `tests/unit/test_user_input_automech_guard_ci.py`
- `wiki/*.md`, `MANUAL.md`, `CHANGELOG.md`

## Checks & pitfalls

- Renaming/removing a key breaks old `input.json` files silently (unknown keys are ignored): document it under `### Changed`/`### Removed` and consider accepting the old name.
- Changing a default changes numeric results of runs that relied on it; call it out in the changelog.
- The `kmo_start` Postprocessing tab (`postprocessing_section.py`) is a stub with no controls; do not wire `pp_*` keys into it without an explicit user decision.
- `q_name` in the Resources tab is a dropdown filled from `sinfo` (free text when `sinfo` is unavailable); follow that pattern for environment-dependent choices.
- Never use `--no-verify`; never relax the arity assertion instead of updating it.

## Lane

Always pipeline (Stages 1–7): it edits tracked source, GUI, tests, and docs.
