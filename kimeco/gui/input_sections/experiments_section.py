"""Experiments section for building experiment configurations."""
import os
from string import Formatter
from typing import Any, cast
import cantera.with_units as ctu

from dash import (
    dcc,
    html,
    Input,
    Output,
    State,
    ALL,
    callback,
    callback_context,
)

from kimeco.gui.input_sections.file_browser import FileBrowserDropdown
from kimeco.experiments.t_profile import TimeProfile
from kimeco.default_settings import default_settings


INIT_MODE_OPTIONS = [
    {"label": "Ratio", "value": "ratio"},
    {"label": "Concentration", "value": "concentration"},
]


def _build_pressure_unit_options() -> list[dict[str, str]]:
    """Return pressure units recognized by Cantera's unit registry."""
    try:
        ureg = ctu.cantera_units_registry
        units = sorted(
            str(unit)
            for unit in ureg.get_compatible_units(ureg.parse_units("Pa"))  # type: ignore[arg-type]
            if str(unit) != "sound_pressure_level"
        )
    except Exception:
        units = [default_settings["pres_unit"]]
    return [{"label": unit, "value": unit} for unit in units]


PRESSURE_UNIT_OPTIONS = _build_pressure_unit_options()
DEFAULT_PRESSURE_UNIT = (
    default_settings["pres_unit"]
    if any(opt["value"] == default_settings["pres_unit"]
           for opt in PRESSURE_UNIT_OPTIONS)
    else PRESSURE_UNIT_OPTIONS[0]["value"]
)

_EXP_BROWSER = FileBrowserDropdown(root_dir=os.getcwd())
_REQUIRED_CANTERA_TPL_KEYS = TimeProfile.REQUIRED_TPL_KEYS


def _to_workspace_relative(path: str) -> str:
    """Convert an absolute path to a path relative to launch directory."""
    return _EXP_BROWSER.to_workspace_relative(path)


def _normalize_experiment_path(path: str) -> str:
    """Normalize GUI path input to ingestion-compatible relative style."""
    cleaned = (path or "").strip()
    if not cleaned:
        return ""
    if os.path.isabs(cleaned):
        return _to_workspace_relative(cleaned)
    return cleaned


def _validate_cantera_template_path(path: str) -> tuple[bool, str]:
    """Check that cantera template exists and has required keywords."""
    cleaned = (path or "").strip()
    if not cleaned:
        return False, "Select a Cantera template file."

    resolved_path = os.path.abspath(cleaned)
    if not os.path.isfile(resolved_path):
        return False, "Cantera template file not found."

    try:
        with open(resolved_path, mode="r") as handle:
            content = handle.read()
    except Exception as exc:
        return False, f"Cannot read template: {exc}"

    if not content.strip():
        return False, "Cantera template file is empty."

    try:
        parsed_keys = {
            field_name
            for _, field_name, _, _ in Formatter().parse(content)
            if field_name
        }
    except ValueError as exc:
        return False, f"Invalid template format: {exc}"
    missing = sorted(_REQUIRED_CANTERA_TPL_KEYS - parsed_keys)
    unknown = sorted(parsed_keys - _REQUIRED_CANTERA_TPL_KEYS)

    if missing:
        return (
            False,
            "Missing template keywords: " + ", ".join(missing),
        )
    if unknown:
        return (
            False,
            "Unsupported template keywords: " + ", ".join(unknown),
        )

    return True, "Cantera template keywords are valid."


def _make_empty_experiment(exp_id: int) -> dict:
    """Create an empty experiment data dict."""
    return {
        "id": exp_id,
        "temp": None,
        "pres": None,
        "weight": 1.0,
        "pres_unit": DEFAULT_PRESSURE_UNIT,
        "cantera_tpl": "",
        "data_file": "",
        "error_file": "",
        "init_mode": "ratio",
        "init_value": "",
        "w_species": {},
    }


def _experiment_file_browser(idx: int, field: str) -> html.Div:
    """Render one reusable file browser instance for an experiment field."""
    return _EXP_BROWSER.render_controls(
        dropdown_id={
            "type": "exp-file-browser-dropdown",
            "index": idx,
            "field": field,
        },
        refresh_id={
            "type": "exp-file-browser-refresh",
            "index": idx,
            "field": field,
        },
        path_id={
            "type": "exp-file-browser-path",
            "index": idx,
            "field": field,
        },
        cwd_store_id={
            "type": "exp-file-browser-cwd",
            "index": idx,
            "field": field,
        },
        selected_store_id={
            "type": "exp-file-browser-selected",
            "index": idx,
            "field": field,
        },
    )


def _build_w_species_rows(w_species: dict) -> list:
    """Build w_species weight rows from dict."""
    if not w_species:
        return []
    rows = []
    for species_name, weight in w_species.items():
        rows.append(html.Div([
            html.Div([
                dcc.Input(
                    type="text",
                    placeholder="Species name",
                    value=species_name,
                    className="form-control form-control-sm",
                    readOnly=True,
                ),
            ], className="col-md-6"),
            html.Div([
                dcc.Input(
                    type="number",
                    min=0,
                    step=0.1,
                    placeholder="Weight",
                    value=weight,
                    className="form-control form-control-sm",
                    readOnly=True,
                ),
            ], className="col-md-6"),
        ], className="row g-2 mb-2"))
    return rows


def _experiment_form(exp: dict, idx: int) -> html.Div:
    """Render a single experiment form card."""
    return html.Div([
        html.H6(f"Experiment {exp['id']}", className="fw-bold"),
        html.Div([
            html.Div([
                html.Label("Temperature (K)", className="form-label"),
                dcc.Input(
                    id={"type": "exp-temp", "index": idx},
                    type="number",
                    placeholder="e.g. 1000",
                    value=exp.get("temp"),
                    className="form-control form-control-sm",
                ),
            ], className="col-md-3"),
            html.Div([
                html.Label("Pressure", className="form-label"),
                dcc.Input(
                    id={"type": "exp-pres", "index": idx},
                    type="number",
                    placeholder="e.g. 760",
                    value=exp.get("pres"),
                    className="form-control form-control-sm",
                ),
            ], className="col-md-2"),
            html.Div([
                html.Label("Experiment Weight", className="form-label"),
                dcc.Input(
                    id={"type": "exp-weight", "index": idx},
                    type="number",
                    min=0,
                    step=0.1,
                    value=exp.get("weight", 1.0),
                    className="form-control form-control-sm",
                ),
            ], className="col-md-2"),
            html.Div([
                html.Label("Pressure Unit", className="form-label"),
                dcc.Dropdown(
                    id={"type": "exp-pres-unit", "index": idx},
                    options=cast(Any, PRESSURE_UNIT_OPTIONS),
                    value=exp.get("pres_unit", DEFAULT_PRESSURE_UNIT),
                    clearable=False,
                ),
            ], className="col-md-3"),
            html.Div([
                html.Label("Initial composition mode", className="form-label"),
                dcc.Dropdown(
                    id={"type": "exp-init-mode", "index": idx},
                    options=cast(Any, INIT_MODE_OPTIONS),
                    value=exp.get("init_mode", "ratio"),
                    clearable=False,
                ),
            ], className="col-md-2"),
        ], className="row g-2 mb-2"),
        html.Div([
            html.Div([
                html.Label(
                    "Init. Value (species:value, ...)",
                    className="form-label"
                ),
                dcc.Input(
                    id={"type": "exp-init-value", "index": idx},
                    type="text",
                    placeholder="H2:0.01, CO:0.005",
                    value=exp.get("init_value", ""),
                    className="form-control form-control-sm",
                ),
            ], className="col-md-4"),
            html.Div([
                html.Label("Cantera Template", className="form-label"),
                dcc.Input(
                    id={"type": "exp-cantera-tpl", "index": idx},
                    type="text",
                    placeholder="Select template with browser below",
                    value=exp.get("cantera_tpl", ""),
                    className="form-control form-control-sm",
                    readOnly=True,
                ),
                _experiment_file_browser(idx, "cantera_tpl"),
                html.Button(
                    "Check reactor template",
                    id={"type": "exp-check-cantera", "index": idx},
                    className="btn btn-outline-secondary btn-sm mt-2",
                ),
                html.Small(
                    id={"type": "exp-cantera-status", "index": idx},
                    className="d-block mt-1",
                    style={"display": "none"},
                ),
            ], className="col-md-4"),
            html.Div([
                html.Label("Data File", className="form-label"),
                dcc.Input(
                    id={"type": "exp-data-file", "index": idx},
                    type="text",
                    placeholder="Select data file with browser below",
                    value=exp.get("data_file", ""),
                    className="form-control form-control-sm",
                    readOnly=True,
                ),
                _experiment_file_browser(idx, "data_file"),
            ], className="col-md-4"),
        ], className="row g-2 mb-2"),
        html.Div([
            html.Div([
                html.Label("Error File", className="form-label"),
                dcc.Input(
                    id={"type": "exp-error-file", "index": idx},
                    type="text",
                    placeholder="Select error file with browser below",
                    value=exp.get("error_file", ""),
                    className="form-control form-control-sm",
                    readOnly=True,
                ),
                _experiment_file_browser(idx, "error_file"),
            ], className="col-md-4"),
        ], className="row g-2"),
        # Species weights (w_species)
        html.Div([
            html.Label(
                "Species Weights (w_species) - Optional",
                className="form-label fw-semibold mt-3"
            ),
            html.Small(
                "Set relative weights for species in scoring function. "
                "Leave empty to weight all species equally.",
                className="text-muted d-block mb-2"
            ),
            html.Div(
                id={"type": "exp-w-species-rows", "index": idx},
                children=_build_w_species_rows(
                    exp.get("w_species", {})
                ),
            ),
            html.Div([
                html.Div([
                    dcc.Input(
                        id={"type": "exp-w-species-name", "index": idx},
                        type="text",
                        placeholder="Species name",
                        className="form-control form-control-sm",
                    ),
                ], className="col-md-5"),
                html.Div([
                    dcc.Input(
                        id={"type": "exp-w-species-value", "index": idx},
                        type="number",
                        min=0,
                        step=0.1,
                        placeholder="Weight",
                        value=1.0,
                        className="form-control form-control-sm",
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Button(
                        "+ Add Species",
                        id={"type": "exp-w-species-add", "index": idx},
                        className="btn btn-outline-primary btn-sm w-100",
                    ),
                ], className="col-md-3"),
            ], className="row g-2 mt-2"),
        ], className="mt-3"),
    ], className="card p-3 mb-2 bg-light")


def _render_table(experiments: list) -> list:
    """Render all experiment form cards."""
    if not experiments:
        return [html.Small("No experiments added", className="text-muted")]
    return [_experiment_form(exp, idx) for idx, exp in enumerate(experiments)]


def create_experiments_section() -> html.Div:
    """Create experiments tab section with one empty form on init."""
    initial_exp = _make_empty_experiment(1)
    return html.Div([
            html.H5("Experiments", className="fw-bold"),
            html.Small(
                "Configure experimental conditions",
                className="text-muted"
            ),
            html.Div(
                _render_table([initial_exp]),
                id="experiments-table"
            ),
            html.Button(
                "Add Experiment",
                id="add-experiment-button",
                className="btn btn-primary btn-sm",
                disabled=True,
                style={"marginTop": "10px"}
            ),
            dcc.Store(id="experiments-store", data=[initial_exp]),
        ], className="card p-3 mt-3", id="experiments-card")


@callback(
    Output({"type": "exp-file-browser-cwd", "index": ALL, "field": ALL},
           "data"),
    Output(
        {"type": "exp-file-browser-selected", "index": ALL, "field": ALL},
        "data",
    ),
    Output(
        {"type": "exp-file-browser-dropdown", "index": ALL, "field": ALL},
        "options",
    ),
    Output(
        {"type": "exp-file-browser-path", "index": ALL, "field": ALL},
        "children",
    ),
    Output(
        {"type": "exp-file-browser-dropdown", "index": ALL, "field": ALL},
        "value",
    ),
    Input(
        {"type": "exp-file-browser-dropdown", "index": ALL, "field": ALL},
        "value",
    ),
    Input(
        {"type": "exp-file-browser-refresh", "index": ALL, "field": ALL},
        "n_clicks",
    ),
    State({"type": "exp-file-browser-cwd", "index": ALL, "field": ALL},
          "data"),
    State(
        {"type": "exp-file-browser-selected", "index": ALL, "field": ALL},
        "data",
    ),
    State(
        {"type": "exp-file-browser-dropdown", "index": ALL, "field": ALL},
        "options",
    ),
    State(
        {"type": "exp-file-browser-path", "index": ALL, "field": ALL},
        "children",
    ),
    State(
        {"type": "exp-file-browser-dropdown", "index": ALL, "field": ALL},
        "value",
    ),
    State(
        {"type": "exp-file-browser-dropdown", "index": ALL, "field": ALL},
        "id",
    ),
    prevent_initial_call=True,
)
def update_experiment_file_browser_states(
    selected_values,
    _refresh_clicks,
    cwd_values,
    selected_files,
    dropdown_options,
    path_children,
    current_dropdown_values,
    browser_ids,
):
    """Update one experiment file-browser instance per interaction."""
    count = len(browser_ids or [])
    initial_dir = _EXP_BROWSER.initial_dir()
    initial_options = _EXP_BROWSER.build_options(initial_dir)
    initial_path = _EXP_BROWSER.path_label(initial_dir)

    cwd_out = list(cwd_values or [])
    selected_out = list(selected_files or [])
    options_out = list(dropdown_options or [])
    path_out = list(path_children or [])
    value_out = list(current_dropdown_values or [])

    while len(cwd_out) < count:
        cwd_out.append(initial_dir)
    while len(selected_out) < count:
        selected_out.append(None)
    while len(options_out) < count:
        options_out.append(initial_options)
    while len(path_out) < count:
        path_out.append(initial_path)
    while len(value_out) < count:
        value_out.append(None)

    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict):
        return cwd_out, selected_out, options_out, path_out, value_out

    target_pos = None
    for pos, browser_id in enumerate(browser_ids or []):
        if (
            isinstance(browser_id, dict)
            and browser_id.get("index") == triggered.get("index")
            and browser_id.get("field") == triggered.get("field")
        ):
            target_pos = pos
            break
    if target_pos is None:
        return cwd_out, selected_out, options_out, path_out, value_out

    selected_value = None
    if selected_values and target_pos < len(selected_values):
        selected_value = selected_values[target_pos]

    next_cwd, selected_file = _EXP_BROWSER.resolve_selection(
        selected_value,
        cwd_out[target_pos],
    )
    cwd_out[target_pos] = next_cwd
    selected_out[target_pos] = selected_file if selected_file else None
    options_out[target_pos] = _EXP_BROWSER.build_options(next_cwd)
    path_out[target_pos] = _EXP_BROWSER.path_label(next_cwd)
    value_out[target_pos] = None
    return cwd_out, selected_out, options_out, path_out, value_out


@callback(
    Output({"type": "exp-cantera-tpl", "index": ALL}, "value"),
    Output({"type": "exp-data-file", "index": ALL}, "value"),
    Output({"type": "exp-error-file", "index": ALL}, "value"),
    Input(
        {"type": "exp-file-browser-selected", "index": ALL, "field": ALL},
        "data",
    ),
    State(
        {"type": "exp-file-browser-selected", "index": ALL, "field": ALL},
        "id",
    ),
    State({"type": "exp-cantera-tpl", "index": ALL}, "value"),
    State({"type": "exp-data-file", "index": ALL}, "value"),
    State({"type": "exp-error-file", "index": ALL}, "value"),
    prevent_initial_call=True,
)
def apply_selected_file_to_experiment_field(
    selected_files,
    selected_ids,
    cantera_values,
    data_values,
    error_values,
):
    """Apply selected browser file to its experiment row and field."""
    cantera_out = list(cantera_values or [])
    data_out = list(data_values or [])
    error_out = list(error_values or [])

    # Apply every non-None selected file to its corresponding text field.
    # Iterating all stores (rather than relying on triggered_id dict equality)
    # avoids Dash version-specific quirks with pattern-matched ID comparison.
    for selected_id, selected_file in zip(
        selected_ids or [], selected_files or []
    ):
        if not selected_file or not os.path.isfile(selected_file):
            continue
        if not isinstance(selected_id, dict):
            continue
        target_index = selected_id.get("index")
        target_field = selected_id.get("field")
        if target_index is None:
            continue
        rel_path = _to_workspace_relative(selected_file)
        if target_field == "cantera_tpl" and target_index < len(cantera_out):
            cantera_out[target_index] = rel_path
        elif target_field == "data_file" and target_index < len(data_out):
            data_out[target_index] = rel_path
        elif target_field == "error_file" and target_index < len(error_out):
            error_out[target_index] = rel_path

    return cantera_out, data_out, error_out


@callback(
    Output({"type": "exp-cantera-status", "index": ALL}, "children"),
    Output({"type": "exp-cantera-status", "index": ALL}, "style"),
    Input({"type": "exp-check-cantera", "index": ALL}, "n_clicks"),
    State({"type": "exp-cantera-tpl", "index": ALL}, "value"),
    State({"type": "exp-cantera-status", "index": ALL}, "children"),
    State({"type": "exp-cantera-status", "index": ALL}, "style"),
    prevent_initial_call=True,
)
def validate_cantera_templates(
    _check_clicks: list,
    tpl_paths: list,
    current_messages: list,
    current_styles: list,
) -> tuple[list, list]:
    """Validate one reactor template when its check button is pressed."""
    tpl_count = len(tpl_paths or [])
    messages = list(current_messages or [""] * tpl_count)
    styles = list(current_styles or [{"display": "none"}] * tpl_count)

    while len(messages) < tpl_count:
        messages.append("")
    while len(styles) < tpl_count:
        styles.append({"display": "none"})

    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict):
        return messages, styles

    idx = triggered.get("index")
    if idx is None or idx >= tpl_count:
        return messages, styles

    cleaned = str((tpl_paths[idx] if idx < tpl_count else "") or "").strip()
    if not cleaned:
        messages[idx] = "Select a reactor template file first."
        styles[idx] = {"display": "block", "color": "red"}
        return messages, styles

    is_valid, msg = _validate_cantera_template_path(cleaned)
    messages[idx] = msg
    styles[idx] = {
        "display": "block",
        "color": "green" if is_valid else "red",
        "fontWeight": "bold" if is_valid else "normal",
    }
    return messages, styles


@callback(
    Output("add-experiment-button", "disabled"),
    Output("experiment-count-store", "data"),
    [
        Input({"type": "exp-temp", "index": ALL}, "value"),
        Input({"type": "exp-pres", "index": ALL}, "value"),
        Input({"type": "exp-pres-unit", "index": ALL}, "value"),
        Input({"type": "exp-cantera-tpl", "index": ALL}, "value"),
        Input({"type": "exp-data-file", "index": ALL}, "value"),
        Input({"type": "exp-error-file", "index": ALL}, "value"),
        Input({"type": "exp-init-value", "index": ALL}, "value"),
    ],
    prevent_initial_call=True,
)
def validate_experiment_forms(
    temps: list,
    press: list,
    press_units: list,
    tpls: list,
    data_files: list,
    error_files: list,
    init_values: list,
) -> tuple[bool, int]:
    """Enable Add button only when all experiment forms are complete."""
    if not temps:
        return True, 0
    valid_count = 0
    all_valid = True
    valid_pres_units = {opt["value"] for opt in PRESSURE_UNIT_OPTIONS}
    for fields in zip(
        temps, press, press_units, tpls, data_files, error_files, init_values
    ):
        row_valid = all(
            f is not None and str(f).strip() != "" for f in fields
        )
        if row_valid and str(fields[2]) not in valid_pres_units:
            row_valid = False
        if row_valid:
            cantera_ok, _ = _validate_cantera_template_path(str(fields[3]))
            row_valid = cantera_ok
        if row_valid:
            valid_count += 1
        else:
            all_valid = False
    return not all_valid, valid_count


@callback(
    Output("experiments-store", "data"),
    Output("experiments-table", "children"),
    Input("add-experiment-button", "n_clicks"),
    Input({"type": "exp-w-species-add", "index": ALL}, "n_clicks"),
    [
        State("experiments-store", "data"),
        State({"type": "exp-temp", "index": ALL}, "value"),
        State({"type": "exp-pres", "index": ALL}, "value"),
        State({"type": "exp-weight", "index": ALL}, "value"),
        State({"type": "exp-pres-unit", "index": ALL}, "value"),
        State({"type": "exp-init-mode", "index": ALL}, "value"),
        State({"type": "exp-cantera-tpl", "index": ALL}, "value"),
        State({"type": "exp-data-file", "index": ALL}, "value"),
        State({"type": "exp-error-file", "index": ALL}, "value"),
        State({"type": "exp-init-value", "index": ALL}, "value"),
        State({"type": "exp-w-species-name", "index": ALL}, "value"),
        State({"type": "exp-w-species-value", "index": ALL}, "value"),
    ],
    prevent_initial_call=True,
)
def add_experiment(
    n_clicks: int,
    _add_species_clicks: list,
    experiments: list,
    temps: list,
    press: list,
    weights: list,
    press_units: list,
    init_modes: list,
    tpls: list,
    data_files: list,
    error_files: list,
    init_values: list,
    w_species_names: list,
    w_species_values: list,
) -> tuple[list, list]:
    """Save form values, then append experiment or add one species weight."""
    if experiments is None:
        experiments = []

    # Persist current field values into the store entries
    saved = []
    for i, exp in enumerate(experiments):
        saved.append({
            **exp,
            "temp": temps[i] if i < len(temps) else None,
            "pres": press[i] if i < len(press) else None,
            "weight": (
                weights[i] if i < len(weights) else exp.get("weight", 1.0)
            ) or 1.0,
            "pres_unit": (
                press_units[i] if i < len(press_units)
                else DEFAULT_PRESSURE_UNIT
            ) or DEFAULT_PRESSURE_UNIT,
            "init_mode": (
                init_modes[i] if i < len(init_modes) else "ratio"
            ) or "ratio",
            "cantera_tpl": _normalize_experiment_path(
                tpls[i] if i < len(tpls) else ""
            ),
            "data_file": _normalize_experiment_path(
                data_files[i] if i < len(data_files) else ""
            ),
            "error_file": _normalize_experiment_path(
                error_files[i] if i < len(error_files) else ""
            ),
            "init_value": (
                init_values[i] if i < len(init_values) else ""
            ) or "",
        })

    triggered = callback_context.triggered_id
    if isinstance(triggered, dict) and triggered.get("type") == "exp-w-species-add":
        exp_idx = triggered.get("index")
        if isinstance(exp_idx, int) and 0 <= exp_idx < len(saved):
            add_click = (
                _add_species_clicks[exp_idx]
                if exp_idx < len(_add_species_clicks or [])
                else None
            )
            raw_species_name = (
                w_species_names[exp_idx]
                if exp_idx < len(w_species_names)
                else ""
            )
            species_name = str(raw_species_name or "").strip()
            if add_click and species_name:
                raw_weight = (
                    w_species_values[exp_idx]
                    if exp_idx < len(w_species_values)
                    else 1.0
                )
                try:
                    parsed_weight = float(raw_weight)
                except (TypeError, ValueError):
                    parsed_weight = 1.0
                if parsed_weight >= 0:
                    existing = dict(saved[exp_idx].get("w_species") or {})
                    existing[species_name] = parsed_weight
                    saved[exp_idx]["w_species"] = existing
        return saved, _render_table(saved)

    # Add Experiment button path
    saved.append(_make_empty_experiment(len(saved) + 1))

    return saved, _render_table(saved)
