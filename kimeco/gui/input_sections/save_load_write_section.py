"""Save/Load/Write section for configuration management."""
from __future__ import annotations

import copy
import json
import os
from typing import Any

from dash import (
    ALL,
    Input,
    Output,
    State,
    callback,
    callback_context,
    dcc,
    html,
    no_update,
)

from kimeco.default_settings import default_settings
from kimeco.gui.input_sections.experiments_section import (
    _make_empty_experiment,
    _render_table,
)
from kimeco.gui.input_sections.file_browser import FileBrowserDropdown


_LOAD_BROWSER = FileBrowserDropdown(root_dir=os.getcwd())


_BASE_STATUS_STYLE = {
    "marginTop": "15px",
    "padding": "10px",
    "borderRadius": "5px",
    "display": "block",
}


def _status_style(success: bool) -> dict[str, str]:
    """Return status style for success (green) or error (red)."""
    return {
        **_BASE_STATUS_STYLE,
        "backgroundColor": "#d4edda" if success else "#f8d7da",
        "color": "#155724" if success else "#721c24",
    }


def _hidden_style() -> dict[str, str]:
    """Return hidden status style."""
    return {
        "marginTop": "15px",
        "padding": "10px",
        "borderRadius": "5px",
        "display": "none",
    }


def _parse_initial_values(raw_value: str) -> dict[str, Any]:
    """Parse "species:value" pairs into a dictionary."""
    result: dict[str, Any] = {}
    cleaned = (raw_value or "").strip()
    if not cleaned:
        return result

    for chunk in cleaned.split(","):
        token = chunk.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(
                f"Invalid initial composition token '{token}'. "
                "Use format species:value."
            )
        species, value = token.split(":", 1)
        species_clean = species.strip()
        value_clean = value.strip()
        if not species_clean:
            raise ValueError("Initial composition contains an empty species.")
        if not value_clean:
            raise ValueError(
                f"Initial composition for '{species_clean}' is empty."
            )
        if value_clean.casefold() == "base":
            result[species_clean] = "base"
        else:
            result[species_clean] = float(value_clean)
    return result


def _build_experiments_payload(
    experiments_store: list[dict[str, Any]],
) -> list:
    """Transform GUI experiment entries into runtime JSON schema."""
    experiments: list[dict[str, Any]] = []
    for idx, exp in enumerate(experiments_store or []):
        if not isinstance(exp, dict):
            continue

        required_values = [
            exp.get("temp"),
            exp.get("pres"),
            (exp.get("cantera_tpl") or "").strip(),
            (exp.get("data_file") or "").strip(),
            (exp.get("error_file") or "").strip(),
            (exp.get("init_value") or "").strip(),
        ]
        # Skip fully empty placeholder rows.
        if all(v in (None, "") for v in required_values):
            continue

        if any(v in (None, "") for v in required_values):
            raise ValueError(
                f"Experiment {idx + 1} is incomplete. "
                "Fill all required fields before writing JSON."
            )

        init_mode = (exp.get("init_mode") or "ratio").strip().casefold()
        init_values = _parse_initial_values(str(exp.get("init_value") or ""))
        if not init_values:
            raise ValueError(
                f"Experiment {idx + 1} initial composition is empty."
            )

        experiment_entry: dict[str, Any] = {
            "temp": float(exp["temp"]),
            "pres": float(exp["pres"]),
            "weight": float(exp.get("weight", 1.0) or 1.0),
            "pres_unit": (exp.get("pres_unit")
                          or default_settings["pres_unit"]),
            "cantera_tpl": (exp.get("cantera_tpl") or "").strip(),
            "scoring_func": exp.get("scoring_func")
            or default_settings["scoring_func"],
            "data_file": (exp.get("data_file") or "").strip(),
            "error_file": (exp.get("error_file") or "").strip(),
        }

        if exp.get("w_species"):
            experiment_entry["w_species"] = exp["w_species"]

        if init_mode == "concentration":
            experiment_entry["initial_concentration"] = init_values
        else:
            experiment_entry["initial_ratio"] = init_values

        experiments.append(experiment_entry)

    if not experiments:
        raise ValueError("No complete experiment found to write in JSON.")

    return experiments


def _build_payload(
    ct_yaml: str,
    mess_inputs: list,
    force_new_molecules: list,
    experiments_store: list[dict[str, Any]],
    sensitivity_config: dict,
    optimizer_config: dict,
    perturbation_config: dict,
    resources_config: dict,
) -> dict[str, Any]:
    """Build a JSON payload compatible with KMO input expectations."""
    payload: dict[str, Any] = copy.deepcopy(default_settings)
    payload.update(sensitivity_config or {})
    payload.update(optimizer_config or {})
    payload.update(perturbation_config or {})
    payload.update(resources_config or {})
    payload.pop("optimizer_scheme", None)

    payload["ct_yaml"] = (ct_yaml or "").strip()
    payload["mess_inputs"] = list(mess_inputs or [])
    payload["force_new_molecules"] = bool(
        force_new_molecules and "enabled" in force_new_molecules
    )
    payload["experiments"] = _build_experiments_payload(experiments_store)

    if not payload["ct_yaml"]:
        raise ValueError("ct_yaml is empty. Validate mechanism in tab 1.")
    if not payload["mess_inputs"]:
        raise ValueError("No MESS input file selected in tab 2.")

    return payload


def _value_at(values: list[Any], index: int, default: Any) -> Any:
    """Safely read a list item for index-based Dash pattern state."""
    if index < len(values or []):
        value = values[index]
        return default if value is None else value
    return default


def _merge_live_experiments(
    experiments_store: list[dict[str, Any]],
    temps: list[Any],
    press: list[Any],
    weights: list[Any],
    press_units: list[Any],
    scoring_funcs: list[Any],
    init_modes: list[Any],
    tpls: list[Any],
    data_files: list[Any],
    error_files: list[Any],
    init_values: list[Any],
) -> list[dict[str, Any]]:
    """Overlay current form values onto experiments store before writing."""
    experiments = list(experiments_store or [])
    for i, exp in enumerate(experiments):
        if not isinstance(exp, dict):
            continue
        exp["temp"] = _value_at(temps, i, exp.get("temp"))
        exp["pres"] = _value_at(press, i, exp.get("pres"))
        exp["weight"] = _value_at(weights, i, exp.get("weight", 1.0))
        exp["pres_unit"] = _value_at(
            press_units,
            i,
            exp.get("pres_unit", default_settings["pres_unit"]),
        )
        exp["scoring_func"] = _value_at(
            scoring_funcs,
            i,
            exp.get("scoring_func", default_settings["scoring_func"]),
        )
        exp["init_mode"] = _value_at(init_modes, i, exp.get("init_mode"))
        exp["cantera_tpl"] = _value_at(tpls, i, exp.get("cantera_tpl", ""))
        exp["data_file"] = _value_at(data_files, i, exp.get("data_file", ""))
        exp["error_file"] = _value_at(
            error_files,
            i,
            exp.get("error_file", ""),
        )
        exp["init_value"] = _value_at(
            init_values,
            i,
            exp.get("init_value", ""),
        )
    return experiments


def _resolve_output_path(filename: str) -> str:
    """Resolve output filename to absolute path in current workspace."""
    cleaned = (filename or "").strip()
    if not cleaned:
        raise ValueError("Provide an output filename before writing JSON.")
    if os.path.isdir(cleaned):
        raise ValueError("Output filename points to a directory.")
    return os.path.abspath(cleaned)


def _resolve_load_path(filename: str) -> str:
    """Resolve and validate a JSON config path for loading."""
    cleaned = (filename or "").strip()
    if not cleaned:
        raise ValueError("Provide a JSON filename before loading config.")
    path = os.path.abspath(cleaned)
    if not os.path.isfile(path):
        raise ValueError("Config file does not exist.")
    if not path.casefold().endswith(".json"):
        raise ValueError("Config file must have .json extension.")
    return path


def _format_initial_values(values: dict[str, Any]) -> str:
    """Format initial composition dict to GUI string."""
    if not isinstance(values, dict):
        return ""
    parts: list[str] = []
    for species, value in values.items():
        parts.append(f"{species}:{value}")
    return ", ".join(parts)


def _experiments_from_payload(raw_experiments: Any) -> list[dict[str, Any]]:
    """Convert runtime JSON experiments list to GUI experiments store."""
    experiments: list[dict[str, Any]] = []
    for idx, exp in enumerate(raw_experiments or []):
        if not isinstance(exp, dict):
            continue

        initial_ratio = exp.get("initial_ratio")
        initial_conc = exp.get("initial_concentration")
        init_mode = "concentration" if isinstance(initial_conc, dict) else "ratio"
        init_dict = initial_conc if init_mode == "concentration" else initial_ratio

        experiments.append({
            "id": idx + 1,
            "temp": exp.get("temp"),
            "pres": exp.get("pres"),
            "weight": exp.get("weight", 1.0),
            "pres_unit": exp.get("pres_unit", default_settings["pres_unit"]),
            "cantera_tpl": exp.get("cantera_tpl", ""),
            "scoring_func": exp.get("scoring_func", default_settings["scoring_func"]),
            "data_file": exp.get("data_file", ""),
            "error_file": exp.get("error_file", ""),
            "init_mode": init_mode,
            "init_value": _format_initial_values(init_dict if isinstance(init_dict, dict) else {}),
            "w_species": exp.get("w_species", {}) if isinstance(exp.get("w_species", {}), dict) else {},
        })

    if not experiments:
        return [_make_empty_experiment(1)]
    return experiments


def _infer_optimizer_scheme(payload: dict[str, Any]) -> str:
    """Infer optimizer scheme selector value from runtime optimizer keys."""
    optimizer = str(payload.get("optimizer", "ga"))
    ga_type = str(payload.get("ga_type", "exp"))
    nms_start = str(payload.get("NMS_start", "") or "")

    if optimizer == "nelder-mead":
        return "scheme-nelder-mead"
    if optimizer == "ga" and ga_type == "tournament":
        return "scheme-tournament-ga"
    if optimizer == "ga" and ga_type == "exp" and nms_start == "G0001":
        return "scheme-swarm-nm"
    if optimizer == "ga" and ga_type == "exp" and nms_start == "GT-1":
        return "scheme-swarm-nm-goat"
    return "scheme-expmc-ga"


def _cfg_with_aliases(
    data: dict[str, Any],
    defaults: dict[str, Any],
    primary_key: str,
    *aliases: str,
) -> Any:
    """Read config value with backward-compatible key aliases."""
    for key in (primary_key, *aliases):
        if key in data:
            return data[key]
    for key in (primary_key, *aliases):
        if key in defaults:
            return defaults[key]
    return None


def create_save_load_write_section(initial_config_path: str = "") -> html.Div:
    """Create save/load/write section."""
    return html.Div([
            html.H5("Save & Write Configuration", className="fw-bold"),
            html.Div([
                html.Button(
                    "Save Config",
                    id="save-config-button",
                    className="btn btn-info btn-sm",
                    style={"width": "24%", "marginTop": "10px",
                           "marginRight": "1%"}
                ),
                html.Button(
                    "Load Config",
                    id="load-config-button",
                    className="btn btn-info btn-sm",
                    style={"width": "24%", "marginTop": "10px",
                           "marginRight": "1%"}
                ),
                dcc.Input(
                    id="output-filename-input",
                    type="text",
                    placeholder="input.json",
                    className="form-control",
                    style={"marginTop": "10px", "width": "24%",
                           "display": "inline-block", "marginRight": "1%"}
                ),
                html.Button(
                    "Write JSON",
                    id="write-json-button",
                    className="btn btn-success btn-sm",
                    style={"marginTop": "10px", "width": "24%",
                           "verticalAlign": "top"}
                ),
            ]),
            html.Div([
                html.H6("Browse Local Cluster Files", className="mt-3"),
                html.Small(
                    "Select a JSON config file from launch directory tree",
                    className="text-muted"
                ),
                _LOAD_BROWSER.render_controls(
                    dropdown_id="load-browser-dropdown",
                    refresh_id="load-browser-refresh",
                    path_id="load-browser-path",
                    cwd_store_id="load-browser-cwd",
                    selected_store_id="load-browser-selected-file",
                ),
            ], className="mt-2 p-2 border rounded"),
            html.Div(
                id="write-status-message",
                style={
                    "marginTop": "15px",
                    "padding": "10px",
                    "borderRadius": "5px",
                    "display": "none"
                }
            ),
            html.Div(
                id="load-status-message",
                style={
                    "marginTop": "10px",
                    "padding": "10px",
                    "borderRadius": "5px",
                    "display": "none"
                }
            ),
            dcc.ConfirmDialog(
                id="write-overwrite-confirm",
                message=(
                    "A file with this name already exists. "
                    "Do you want to overwrite it?"
                ),
                displayed=False,
            ),
            dcc.Store(id="write-overwrite-path-store", data=""),
            dcc.Store(
                id="autoload-config-path-store",
                data=(initial_config_path or ""),
            ),
            dcc.Download(id="config-download"),
        ], className="card p-3 mt-3")


@callback(
    Output("load-browser-cwd", "data"),
    Output("load-browser-selected-file", "data"),
    Output("load-browser-dropdown", "options"),
    Output("load-browser-path", "children"),
    Output("load-browser-dropdown", "value"),
    Input("load-browser-dropdown", "value"),
    Input("load-browser-refresh", "n_clicks"),
    State("load-browser-cwd", "data"),
)
def update_load_browser_state(selected_value, _refresh, cwd):
    """Own load-config browser navigation, refresh, and selection state."""
    current_dir, selected_file = _LOAD_BROWSER.resolve_selection(
        selected_value,
        cwd,
    )
    options = _LOAD_BROWSER.build_options(current_dir)
    path_label = _LOAD_BROWSER.path_label(current_dir)
    selected_payload = selected_file if selected_file is not None else None
    return (
        current_dir,
        selected_payload,
        options,
        path_label,
        None,
    )


@callback(
    Output("output-filename-input", "value", allow_duplicate=True),
    Input("load-browser-selected-file", "data"),
    State("output-filename-input", "value"),
    prevent_initial_call=True,
)
def apply_load_browser_selection_to_filename(
    selected_file: str,
    current_value: str,
) -> str:
    """Copy selected browser file into the shared filename input."""
    if not selected_file or not os.path.isfile(selected_file):
        return current_value
    return _LOAD_BROWSER.to_workspace_relative(selected_file)


@callback(
    Output("write-overwrite-confirm", "displayed"),
    Output("write-overwrite-path-store", "data"),
    Input("write-json-button", "n_clicks"),
    State("output-filename-input", "value"),
    prevent_initial_call=True,
)
def request_write_confirmation(
    n_clicks: int,
    output_filename: str,
) -> tuple[bool, str]:
    """Check output target and ask confirmation when file already exists."""
    if not n_clicks:
        return False, ""

    try:
        output_path = _resolve_output_path(output_filename)
    except ValueError:
        return False, ""

    if os.path.exists(output_path):
        return True, output_path

    return False, output_path


@callback(
    Output("write-status-message", "children"),
    Output("write-status-message", "style"),
    Input("write-json-button", "n_clicks"),
    Input("write-overwrite-confirm", "submit_n_clicks"),
    State("write-overwrite-path-store", "data"),
    State("output-filename-input", "value"),
    State("mechanism-ct-yaml-input", "value"),
    State("sop-mess-files-store", "data"),
    State("sop-force-new-molecules", "value"),
    State("experiments-store", "data"),
    State("sensitivity-config-store", "data"),
    State("optimizer-config-store", "data"),
    State("perturbation-config-store", "data"),
    State("resources-config-store", "data"),
    State({"type": "exp-temp", "index": ALL}, "value"),
    State({"type": "exp-pres", "index": ALL}, "value"),
    State({"type": "exp-weight", "index": ALL}, "value"),
    State({"type": "exp-pres-unit", "index": ALL}, "value"),
    State({"type": "exp-scoring-func", "index": ALL}, "value"),
    State({"type": "exp-init-mode", "index": ALL}, "value"),
    State({"type": "exp-cantera-tpl", "index": ALL}, "value"),
    State({"type": "exp-data-file", "index": ALL}, "value"),
    State({"type": "exp-error-file", "index": ALL}, "value"),
    State({"type": "exp-init-value", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def write_json_file(
    write_clicks: int,
    overwrite_submit_clicks: int,
    pending_output_path: str,
    output_filename: str,
    ct_yaml: str,
    mess_inputs: list,
    force_new_molecules: list,
    experiments_store: list[dict[str, Any]],
    sensitivity_config: dict,
    optimizer_config: dict,
    perturbation_config: dict,
    resources_config: dict,
    exp_temps: list[Any],
    exp_press: list[Any],
    exp_weights: list[Any],
    exp_press_units: list[Any],
    exp_scoring_funcs: list[Any],
    exp_init_modes: list[Any],
    exp_tpls: list[Any],
    exp_data_files: list[Any],
    exp_error_files: list[Any],
    exp_init_values: list[Any],
) -> tuple[Any, dict[str, str]]:
    """Write JSON on direct write or after overwrite confirmation."""
    triggered_id = callback_context.triggered_id
    if not write_clicks and not overwrite_submit_clicks:
        return "", _hidden_style()

    try:
        output_path = _resolve_output_path(output_filename)
        if triggered_id == "write-json-button" and os.path.exists(output_path):
            # Overwrite requires explicit confirmation in the dialog callback.
            return "", _hidden_style()

        if triggered_id == "write-overwrite-confirm":
            output_path = pending_output_path or output_path

        merged_experiments = _merge_live_experiments(
            experiments_store=experiments_store,
            temps=exp_temps,
            press=exp_press,
            weights=exp_weights,
            press_units=exp_press_units,
            scoring_funcs=exp_scoring_funcs,
            init_modes=exp_init_modes,
            tpls=exp_tpls,
            data_files=exp_data_files,
            error_files=exp_error_files,
            init_values=exp_init_values,
        )

        payload = _build_payload(
            ct_yaml=ct_yaml,
            mess_inputs=mess_inputs,
            force_new_molecules=force_new_molecules,
            experiments_store=merged_experiments,
            sensitivity_config=sensitivity_config,
            optimizer_config=optimizer_config,
            perturbation_config=perturbation_config,
            resources_config=resources_config,
        )

        with open(output_path, mode="w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

        return (
            f"✅ JSON written successfully to {output_path}",
            _status_style(success=True),
        )
    except Exception as exc:
        return (f"❌ Failed to write JSON: {exc}", _status_style(success=False))


@callback(
    Output("config-download", "data"),
    Input("save-config-button", "n_clicks"),
    State("mechanism-ct-yaml-input", "value"),
    State("sop-mess-files-store", "data"),
    State("sop-force-new-molecules", "value"),
    State("experiments-store", "data"),
    State("sensitivity-config-store", "data"),
    State("optimizer-config-store", "data"),
    State("perturbation-config-store", "data"),
    State("resources-config-store", "data"),
    State({"type": "exp-temp", "index": ALL}, "value"),
    State({"type": "exp-pres", "index": ALL}, "value"),
    State({"type": "exp-weight", "index": ALL}, "value"),
    State({"type": "exp-pres-unit", "index": ALL}, "value"),
    State({"type": "exp-scoring-func", "index": ALL}, "value"),
    State({"type": "exp-init-mode", "index": ALL}, "value"),
    State({"type": "exp-cantera-tpl", "index": ALL}, "value"),
    State({"type": "exp-data-file", "index": ALL}, "value"),
    State({"type": "exp-error-file", "index": ALL}, "value"),
    State({"type": "exp-init-value", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def save_config_download(
    n_clicks: int,
    ct_yaml: str,
    mess_inputs: list,
    force_new_molecules: list,
    experiments_store: list[dict[str, Any]],
    sensitivity_config: dict,
    optimizer_config: dict,
    perturbation_config: dict,
    resources_config: dict,
    exp_temps: list[Any],
    exp_press: list[Any],
    exp_weights: list[Any],
    exp_press_units: list[Any],
    exp_scoring_funcs: list[Any],
    exp_init_modes: list[Any],
    exp_tpls: list[Any],
    exp_data_files: list[Any],
    exp_error_files: list[Any],
    exp_init_values: list[Any],
):
    """Export the current GUI state as a downloadable JSON config."""
    if not n_clicks:
        return no_update

    merged_experiments = _merge_live_experiments(
        experiments_store=experiments_store,
        temps=exp_temps,
        press=exp_press,
        weights=exp_weights,
        press_units=exp_press_units,
        scoring_funcs=exp_scoring_funcs,
        init_modes=exp_init_modes,
        tpls=exp_tpls,
        data_files=exp_data_files,
        error_files=exp_error_files,
        init_values=exp_init_values,
    )

    payload = _build_payload(
        ct_yaml=ct_yaml,
        mess_inputs=mess_inputs,
        force_new_molecules=force_new_molecules,
        experiments_store=merged_experiments,
        sensitivity_config=sensitivity_config,
        optimizer_config=optimizer_config,
        perturbation_config=perturbation_config,
        resources_config=resources_config,
    )

    return dcc.send_string(
        json.dumps(payload, indent=2),
        filename="kimeco_config.json",
    )


@callback(
    Output("load-status-message", "children"),
    Output("load-status-message", "style"),
    Output("mechanism-ct-yaml-input", "value", allow_duplicate=True),
    Output("sop-mess-files-store", "data", allow_duplicate=True),
    Output("sop-force-new-molecules", "value"),
    Output("experiments-store", "data", allow_duplicate=True),
    Output("experiments-table", "children", allow_duplicate=True),
    Output("experiment-count-store", "data", allow_duplicate=True),
    Output("sensitivity-sensi-d-input", "value"),
    Output("sensitivity-cumul-sensi-input", "value"),
    Output("sensitivity-active-p-dropdown", "value"),
    Output("sensitivity-sa-start-input", "value"),
    Output("sensitivity-sa-end-input", "value"),
    Output("sensitivity-sa-freq-input", "value"),
    Output("sensitivity-sa-restart-store", "data", allow_duplicate=True),
    Output("optimizer-scheme-dropdown", "value"),
    Output("optimizer-max-gen-input", "value", allow_duplicate=True),
    Output("optimizer-n-mdl-input", "value"),
    Output("optimizer-goat-length-input", "value"),
    Output("optimizer-max-score-input", "value"),
    Output("optimizer-score-conv-input", "value"),
    Output("optimizer-param-conv-input", "value"),
    Output("optimizer-nm-fatol-input", "value"),
    Output("optimizer-nm-xatol-input", "value"),
    Output("optimizer-nm-maxiter-input", "value"),
    Output("optimizer-nm-maxfev-input", "value"),
    Output("optimizer-nm-dstep-input", "value"),
    Output("optimizer-nm-adaptive-input", "value"),
    Output("perturbation-pert-dropdown", "value"),
    Output("perturbation-max-std-input", "value"),
    Output("perturbation-std-we-input", "value"),
    Output("perturbation-std-be-input", "value"),
    Output("perturbation-std-bfc-input", "value"),
    Output("perturbation-std-hrs-input", "value"),
    Output("perturbation-std-if-input", "value"),
    Output("perturbation-std-etf-input", "value"),
    Output("perturbation-std-etp-input", "value"),
    Output("perturbation-std-epsi-input", "value"),
    Output("perturbation-std-sigma-input", "value"),
    Output("perturbation-std-sfc-input", "value"),
    Output("perturbation-std-mrc-input", "value"),
    Output("perturbation-specific-std-store", "data", allow_duplicate=True),
    Output("perturbation-distrib-we-dropdown", "value"),
    Output("perturbation-distrib-be-dropdown", "value"),
    Output("perturbation-distrib-freq-dropdown", "value"),
    Output("perturbation-distrib-bfc-dropdown", "value"),
    Output("perturbation-distrib-hrs-dropdown", "value"),
    Output("perturbation-distrib-if-dropdown", "value"),
    Output("perturbation-distrib-etf-dropdown", "value"),
    Output("perturbation-distrib-etp-dropdown", "value"),
    Output("perturbation-distrib-epsi-dropdown", "value"),
    Output("perturbation-distrib-sigma-dropdown", "value"),
    Output("perturbation-distrib-sfc-dropdown", "value"),
    Output("perturbation-distrib-mrc-dropdown", "value"),
    Output("perturbation-conv-we-input", "value"),
    Output("perturbation-conv-be-input", "value"),
    Output("perturbation-conv-etp-input", "value"),
    Output("res-cpu-kin", "value"),
    Output("res-mem-kin", "value"),
    Output("res-cpu-sim", "value"),
    Output("res-mem-sim", "value"),
    Output("res-max-cpu", "value"),
    Output("res-max-mem", "value"),
    Output("res-max-jobs", "value"),
    Output("res-max-user-jobs", "value"),
    Output("res-exclude-nodes", "value"),
    Input("load-config-button", "n_clicks"),
    Input("autoload-config-path-store", "data"),
    State("output-filename-input", "value"),
    prevent_initial_call="initial_duplicate",
)
def load_config_to_gui(n_clicks: int, autoload_path: str, config_path: str):
    """Load JSON config from disk and update GUI controls/stores."""
    triggered_id = callback_context.triggered_id
    if not n_clicks and triggered_id != "autoload-config-path-store":
        return (no_update,) * 66

    try:
        requested_path = autoload_path if triggered_id == "autoload-config-path-store" else config_path
        file_path = _resolve_load_path(requested_path)

        with open(file_path, mode="r", encoding="utf-8") as handle:
            loaded_raw = json.load(handle)
        if not isinstance(loaded_raw, dict):
            raise ValueError("Loaded JSON root must be an object.")

        loaded = copy.deepcopy(default_settings)
        loaded.update(loaded_raw)

        experiments = _experiments_from_payload(loaded.get("experiments", []))
        experiment_count = len([
            exp for exp in experiments
            if any(
                val not in (None, "")
                for val in (
                    exp.get("temp"),
                    exp.get("pres"),
                    exp.get("cantera_tpl"),
                    exp.get("data_file"),
                    exp.get("error_file"),
                    exp.get("init_value"),
                )
            )
        ])

        sa_restart_store = []
        for gen, params in (loaded.get("SA_restart", {}) or {}).items():
            try:
                generation = int(gen)
            except (TypeError, ValueError):
                continue
            sa_restart_store.append({
                "generation": generation,
                "parameters": params if isinstance(params, list) else [],
            })

        return (
            f"Loaded configuration from {file_path}",
            _status_style(success=True),
            loaded.get("ct_yaml", ""),
            loaded.get("mess_inputs", []),
            ["enabled"] if loaded.get("force_new_molecules", False) else [],
            experiments,
            _render_table(experiments),
            experiment_count,
            loaded.get("sensi_d", default_settings["sensi_d"]),
            loaded.get("cumul_sensi", default_settings["cumul_sensi"]),
            loaded.get("active_p", default_settings["active_p"]),
            loaded.get("SA_start", default_settings["SA_start"]),
            loaded.get("SA_end", default_settings["SA_end"]),
            loaded.get("SA_freq", default_settings["SA_freq"]),
            sa_restart_store,
            _infer_optimizer_scheme(loaded),
            loaded.get("max_gen", default_settings["max_gen"]),
            loaded.get("n_mdl", default_settings["n_mdl"]),
            loaded.get("goat_length", default_settings["goat_length"]),
            loaded.get("max_score", default_settings["max_score"]),
            loaded.get("score_conv", default_settings["score_conv"]),
            loaded.get("param_conv", default_settings["param_conv"]),
            loaded.get("nm_fatol", default_settings["nm_fatol"]),
            loaded.get("nm_xatol", default_settings["nm_xatol"]),
            loaded.get("nm_maxiter", default_settings["nm_maxiter"]),
            loaded.get("nm_maxfev", default_settings["nm_maxfev"]),
            loaded.get("nm_dstep", default_settings["nm_dstep"]),
            ["on"] if loaded.get("nm_adaptive", default_settings["nm_adaptive"]) else [],
            loaded.get("pert", default_settings["pert"]),
            loaded.get("max_std", default_settings["max_std"]),
            loaded.get("std_we", default_settings["std_we"]),
            loaded.get("std_be", default_settings["std_be"]),
            loaded.get("std_bfc", default_settings["std_bfc"]),
            loaded.get("std_hrs", default_settings["std_hrs"]),
            loaded.get("std_if", default_settings["std_if"]),
            _cfg_with_aliases(loaded, default_settings, "std_fact", "std_etf"),
            _cfg_with_aliases(loaded, default_settings, "std_pow", "std_etp"),
            _cfg_with_aliases(loaded, default_settings, "std_epsilon", "std_epsi"),
            _cfg_with_aliases(loaded, default_settings, "std_sigma", "std_sig"),
            loaded.get("std_sfc", default_settings["std_sfc"]),
            loaded.get("std_mrc", default_settings["std_mrc"]),
            [
                {"parameter": parameter, "std": std}
                for parameter, std in (
                    loaded.get("specific_std", default_settings["specific_std"])
                    or {}
                ).items()
            ],
            loaded.get("distrib_we", default_settings["distrib_we"]),
            loaded.get("distrib_be", default_settings["distrib_be"]),
            _cfg_with_aliases(loaded, default_settings, "distrib_freq", "distrib_ifc"),
            loaded.get("distrib_bfc", default_settings["distrib_bfc"]),
            loaded.get("distrib_hrs", default_settings["distrib_hrs"]),
            loaded.get("distrib_if", default_settings["distrib_if"]),
            _cfg_with_aliases(loaded, default_settings, "distrib_fact", "distrib_etf"),
            _cfg_with_aliases(loaded, default_settings, "distrib_pow", "distrib_etp"),
            _cfg_with_aliases(loaded, default_settings, "distrib_epsilon", "distrib_epsi"),
            _cfg_with_aliases(loaded, default_settings, "distrib_sigma", "distrib_sig"),
            loaded.get("distrib_sfc", default_settings["distrib_sfc"]),
            loaded.get("distrib_mrc", default_settings["distrib_mrc"]),
            loaded.get("conv_we", default_settings["conv_we"]),
            loaded.get("conv_be", default_settings["conv_be"]),
            _cfg_with_aliases(loaded, default_settings, "conv_pow", "conv_etp"),
            loaded.get("cpu_kin", default_settings["cpu_kin"]),
            loaded.get("mem_kin", default_settings["mem_kin"]),
            loaded.get("cpu_sim", default_settings["cpu_sim"]),
            loaded.get("mem_sim", default_settings["mem_sim"]),
            loaded.get("max_cpu", default_settings["max_cpu"]),
            loaded.get("max_mem", default_settings["max_mem"]),
            loaded.get("max_jobs", default_settings["max_jobs"]),
            loaded.get("max_user_jobs", default_settings["max_user_jobs"]),
            loaded.get("exclude_nodes", default_settings["exclude_nodes"]),
        )
    except Exception as exc:
        return (
            f"Failed to load config: {exc}",
            _status_style(success=False),
            *([no_update] * 64),
        )
