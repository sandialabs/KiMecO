"""Sensitivity Analysis settings with parameter selection."""

from typing import Any, Tuple
from dash import dcc, html, Input, Output, State, callback, ALL
from dash import callback_context

from kimeco.default_settings import default_settings


def create_sensitivity_section() -> html.Div:
    """Create sensitivity analysis tab with General and On-the-fly sections."""
    return html.Div([
        html.H5("Sensitivity Analysis Settings", className="fw-bold"),
        html.Small(
            "Configure parameter selection and on-the-fly sensitivity "
            "analysis",
            className="text-muted d-block mb-3"
        ),

        # General Settings Section
        html.Div([
            html.H6("General Settings", className="fw-semibold mt-3"),
            html.Div([
                html.Div([
                    html.Label(
                        "Derivative Step Size", className="form-label"
                    ),
                    dcc.Input(
                        id="sensitivity-sensi-d-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings["sensi_d"],
                        className="form-control",
                    ),
                    html.Small(
                        "Multiply the parameters' uncertainty to"
                        " compute the step size for the sensitivity analysis.",
                        className="form-text text-muted"
                    ),
                ], className="col-md-6"),
                html.Div([
                    html.Label(
                        "Cumulative Sensitivity Threshold",
                        className="form-label"
                    ),
                    dcc.Input(
                        id="sensitivity-cumul-sensi-input",
                        type="number",
                        min=0,
                        max=1,
                        step=0.01,
                        value=default_settings["cumul_sensi"],
                        className="form-control",
                    ),
                    html.Small(
                        "Cumulated contribution (%, 0-1) to select"
                        " the active parameters.",
                        className="form-text text-muted"
                    ),
                ], className="col-md-6"),
            ], className="row g-2"),
            html.Div([
                html.Label(
                    "Parameters to Perturb (active_p)",
                    className="form-label fw-semibold mt-3"
                ),
                html.Small(
                    "Directly select the active parameters"
                    "and bypass the sensitivity analysis. Leave empty to not bypass.",
                    className="text-muted d-block mb-2"
                ),
                dcc.Dropdown(
                    id="sensitivity-active-p-dropdown",
                    options=[],
                    value=[],
                    multi=True,
                    clearable=True,
                    placeholder="System's parameters",
                    disabled=True,
                    className="mt-1",
                ),
            ], className="mt-2"),
        ], className="border rounded p-3 mt-3"),

        # On-the-Fly Sensitivity Analysis Section
        html.Div([
            html.H6(
                "On-the-Fly Sensitivity Analysis",
                className="fw-semibold mt-3"
            ),
            html.Div([
                html.Div([
                    html.Label("Start at generation:", className="form-label"),
                    dcc.Input(
                        id="sensitivity-sa-start-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["SA_start"],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("End at generation:", className="form-label"),
                    dcc.Input(
                        id="sensitivity-sa-end-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["SA_end"],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("Frequency:", className="form-label"),
                    dcc.Input(
                        id="sensitivity-sa-freq-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["SA_freq"],
                        className="form-control",
                    ),
                ], className="col-md-3"),
            ], className="row g-2"),

            # SA_restart dynamic rows
            html.Div([
                html.Label(
                    "Sensitivity Restart (SA_restart)",
                    className="form-label fw-semibold mt-3"
                ),
                html.Small(
                    "Add parameters to be perturbed starting at a "
                    "specific generation. Each row: generation + "
                    "parameter(s).",
                    className="text-muted d-block mb-2"
                ),
                html.Div(
                    id="sensitivity-sa-restart-rows-container",
                    children=[],
                    className="mt-2"
                ),
                html.Button(
                    "Add Row",
                    id="sensitivity-sa-restart-add-row-button",
                    className="btn btn-outline-primary btn-sm mt-2",
                ),
            ], className="mt-3"),
        ], className="border rounded p-3 mt-3"),

        # Stores for config state and options
        dcc.Store(
            id="sensitivity-sop-parameter-options-store",
            data=[]
        ),
        dcc.Store(
            id="sensitivity-config-store",
            data={}
        ),
        dcc.Store(
            id="sensitivity-valid-store",
            data=False
        ),
        dcc.Store(
            id="sensitivity-sa-restart-store",
            data=[]
        ),
        html.Div(
            id="sensitivity-validation-message",
            className="mt-3",
            style={"display": "none"}
        ),
    ], className="card p-3 mt-3", id="sensitivity-card")


@callback(
    Output("sensitivity-sa-restart-rows-container", "children"),
    Output("sensitivity-sa-restart-store", "data"),
    Input("sensitivity-sa-restart-add-row-button", "n_clicks"),
    Input({"type": "sensitivity-sa-restart-remove", "index": ALL}, "n_clicks"),
    State("sensitivity-sa-restart-rows-container", "children"),
    State("sensitivity-sa-restart-store", "data"),
    State("sensitivity-sop-parameter-options-store", "data"),
    prevent_initial_call=True,
)
def manage_sa_restart_rows(
    add_clicks: int,
    _remove_clicks,
    current_rows_html: list,
    current_store: list,
    param_options: list,
) -> Tuple[list, list]:
    """Manage SA_restart rows - add, remove, and update store."""
    if current_rows_html is None:
        current_rows_html = []
    if current_store is None:
        current_store = []

    triggered = callback_context.triggered_id

    # Add row
    if triggered == "sensitivity-sa-restart-add-row-button":
        row_idx = len(current_store)
        current_store.append({
            "generation": None,
            "parameters": []
        })
        current_rows_html.append(_build_sa_restart_row(row_idx, param_options))

    # Remove row
    elif (isinstance(triggered, dict) and
          triggered.get("type") == "sensitivity-sa-restart-remove"):
        row_idx = triggered.get("index")
        if row_idx is not None and row_idx < len(current_store):
            current_store.pop(row_idx)
            # Rebuild all rows with correct indices
            current_rows_html = [
                _build_sa_restart_row(idx, param_options)
                for idx in range(len(current_store))
            ]

    return current_rows_html, current_store


def _build_sa_restart_row(row_idx: int, param_options: list) -> html.Div:
    """Build a single SA_restart row with generation selector."""
    return html.Div([
        html.Div([
            html.Div([
                html.Label(
                    f"Row {row_idx + 1} - Generation",
                    className="form-label form-label-sm"
                ),
                dcc.Input(
                    id={"type": "sensitivity-sa-restart-gen",
                        "index": row_idx},
                    type="number",
                    min=1,
                    step=1,
                    placeholder="e.g. 5",
                    className="form-control form-control-sm",
                ),
            ], className="col-md-2"),
            html.Div([
                html.Label(
                    "Parameters to add",
                    className="form-label form-label-sm"
                ),
                dcc.Dropdown(
                    id={"type": "sensitivity-sa-restart-params",
                        "index": row_idx},
                    options=param_options,
                    value=[],
                    multi=True,
                    clearable=True,
                    placeholder="Select parameters...",
                    className="mt-0",
                ),
            ], className="col-md-9"),
            html.Div([
                html.Button(
                    "✕",
                    id={"type": "sensitivity-sa-restart-remove",
                        "index": row_idx},
                    className="btn btn-danger btn-sm mt-4",
                    style={"width": "100%"}
                ),
            ], className="col-md-1"),
        ], className="row g-2"),
    ], className="border rounded p-2 mb-2",
       style={"backgroundColor": "#f8f9fa"})


@callback(
    Output("sensitivity-active-p-dropdown", "options"),
    Output("sensitivity-active-p-dropdown", "disabled"),
    Input("sensitivity-sop-parameter-options-store", "data"),
    prevent_initial_call=True,
)
def update_parameter_options(param_options: list) -> Tuple[list, bool]:
    """Update parameter dropdown options when SOP parameters are available."""
    if not param_options:
        return [], True

    options = [{"label": param, "value": param} for param in param_options]
    return options, False


@callback(
    Output("sensitivity-config-store", "data"),
    Output("sensitivity-valid-store", "data"),
    Output("sensitivity-validation-message", "children"),
    Output("sensitivity-validation-message", "style"),
    Input("sensitivity-sensi-d-input", "value"),
    Input("sensitivity-cumul-sensi-input", "value"),
    Input("sensitivity-active-p-dropdown", "value"),
    Input("sensitivity-sa-start-input", "value"),
    Input("sensitivity-sa-end-input", "value"),
    Input("sensitivity-sa-freq-input", "value"),
    Input("sensitivity-sa-restart-store", "data"),
    prevent_initial_call=True,
)
def update_sensitivity_config(
    sensi_d: float,
    cumul_sensi: float,
    active_p: list,
    sa_start: int,
    sa_end: int,
    sa_freq: int,
    sa_restart: list,
) -> Tuple[dict, bool, Any, dict]:
    """Validate and emit sensitivity configuration."""
    if sensi_d is None or cumul_sensi is None:
        return {}, False, "", {"display": "none"}

    # Build SA_restart dict from store
    sa_restart_dict = {}
    try:
        for row in sa_restart:
            gen = row.get("generation")
            params = row.get("parameters", [])
            if gen is not None and params:
                if gen in sa_restart_dict:
                    sa_restart_dict[gen].extend(params)
                else:
                    sa_restart_dict[gen] = params
    except Exception:
        pass

    config = {
        "sensi_d": (float(sensi_d) if sensi_d is not None
                    else default_settings["sensi_d"]),
        "cumul_sensi": (float(cumul_sensi) if cumul_sensi is not None
                        else default_settings["cumul_sensi"]),
        "active_p": active_p if active_p else [],
        "SA_start": (int(sa_start) if sa_start is not None
                     else default_settings["SA_start"]),
        "SA_end": (int(sa_end) if sa_end is not None
                   else default_settings["SA_end"]),
        "SA_freq": (int(sa_freq) if sa_freq is not None
                    else default_settings["SA_freq"]),
        "SA_restart": sa_restart_dict,
    }

    # Validation
    warnings = []
    if config["SA_start"] >= config["SA_end"]:
        warnings.append("SA_start must be < SA_end")
    if config["SA_freq"] < 1:
        warnings.append("SA_freq must be >= 1")
    if config["sensi_d"] <= 0:
        warnings.append("Derivative step size must be > 0")
    if config["cumul_sensi"] <= 0 or config["cumul_sensi"] > 1:
        warnings.append("Cumulative sensitivity must be between 0 and 1")

    if warnings:
        msg = html.Div([
            html.Div(
                "⚠ Sensitivity settings warnings:",
                style={"color": "orange", "fontWeight": "bold"}
            ),
            html.Ul([html.Li(w) for w in warnings]),
        ])
        return config, True, msg, {
            "display": "block",
            "padding": "10px",
            "backgroundColor": "#fff3cd",
            "borderRadius": "5px",
            "marginTop": "10px"
        }

    return config, True, "", {"display": "none"}
