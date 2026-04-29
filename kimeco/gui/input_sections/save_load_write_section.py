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
)

from kimeco.default_settings import default_settings


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


def create_save_load_write_section() -> html.Div:
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
            html.Div(
                id="write-status-message",
                style={
                    "marginTop": "15px",
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
            dcc.Download(id="config-download"),
        ], className="card p-3 mt-3")


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
