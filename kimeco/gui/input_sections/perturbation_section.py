"""Theoretical uncertainties (perturbation) section."""

from typing import Any, Tuple
from dash import ALL, State, callback_context, dcc, html, Input, Output, callback

from kimeco.default_settings import default_settings
from kimeco.enums import Distrib, Ptype, Pclass


def create_perturbation_section() -> html.Div:
    """Create theoretical uncertainties (perturbation) tab."""
    return html.Div([
        html.H5("Theoretical Uncertainties", className="fw-bold"),
        html.Small(
            "Configure parameter perturbation ranges and distributions",
            className="text-muted d-block mb-3"
        ),

        # Global Perturbation Settings
        html.Div([
            html.H6("Global Settings", className="fw-semibold"),
            html.Div([
                html.Div([
                    html.Label("Max Std Multiplier", className="form-label"),
                    dcc.Input(
                        id="perturbation-max-std-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["max_std"],
                        className="form-control",
                    ),
                    html.Small(
                        "Boundary multiplier for max deviation",
                        className="form-text text-muted"
                    ),
                ], className="col-md-4"),
                # html.Div([
                #     html.Label("Frequency Mode", className="form-label"),
                #     dcc.Dropdown(
                #         id="perturbation-freq-mode-dropdown",
                #         options=[
                #             {
                #                 "label": "Batch",
                #                 "value": FreqMode.BATCH.value,
                #             },
                #         ],
                #         value=FreqMode.BATCH.value,
                #         clearable=False,
                #     ),
                # ], className="col-md-4"),
            ], className="row g-2"),
        ], className="border rounded p-3 mt-3"),

        html.Div([
            html.H6("Scoring Balance", className="fw-semibold mt-3"),
            html.Small(
                "Raw theory and experiment weights are normalized at runtime "
                "so their sum is 1.",
                className="text-muted d-block mb-2"
            ),
            html.Div([
                html.Div([
                    html.Label("Theory Weight", className="form-label"),
                    dcc.Input(
                        id="perturbation-weight-theory-input",
                        type="number",
                        min=0,
                        step=0.1,
                        value=default_settings["weight_theory"],
                        className="form-control",
                    ),
                ], className="col-md-6"),
                html.Div([
                    html.Label("Experiment Weight", className="form-label"),
                    dcc.Input(
                        id="perturbation-weight-experiments-input",
                        type="number",
                        min=0,
                        step=0.1,
                        value=default_settings["weight_experiments"],
                        className="form-control",
                    ),
                ], className="col-md-6"),
            ], className="row g-2"),
        ], className="border rounded p-3 mt-3"),

        # Uncertainty Standards (std_*)
        html.Div([
            html.H6("Standard Deviations (σ)", className="fw-semibold mt-3"),
            html.Div([
                html.Div([
                    html.Label("Well Energy (kcal/mol)",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-we-input",
                        type="number",
                        min=0,
                        step=0.1,
                        value=default_settings[
                            f"std_{Ptype.WE.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("Barrier Energy (kcal/mol)",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-be-input",
                        type="number",
                        min=0,
                        step=0.1,
                        value=default_settings[
                            f"std_{Ptype.BE.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                # html.Div([
                #     html.Label("Individual Frequencies",
                #                className="form-label"),
                #     dcc.Input(
                #         id="perturbation-std-freq-input",
                #         type="number",
                #         min=0,
                #         step=0.01,
                #         value=default_settings[
                #             f"std_{Ptype.IFC.value}"
                #         ],
                #         className="form-control",
                #     ),
                # ], className="col-md-3"),
                html.Div([
                    html.Label("Batch Frequencies",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-bfc-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings[
                            f"std_{Ptype.BFC.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
            ], className="row g-2 mb-2"),
            html.Div([
                html.Div([
                    html.Label("Hindered Rotors",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-hrs-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings[
                            f"std_{Ptype.HRS.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("Imaginary Frequency",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-if-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings[
                            f"std_{Ptype.IF.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("Energy Transfer Factor",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-etf-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings[
                            f"std_{Ptype.ETF.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("Energy Transfer Power",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-etp-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings[
                            f"std_{Ptype.ETP.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
            ], className="row g-2 mb-2"),
            html.Div([
                html.Div([
                    html.Label("LJ Epsilon",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-epsi-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings[
                            f"std_{Ptype.EPSI.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("LJ Sigma",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-sigma-input",
                        type="number",
                        min=0,
                        step=0.01,
                        value=default_settings[
                            f"std_{Ptype.SIG.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("Symmetry Factor",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-sfc-input",
                        type="number",
                        min=0,
                        step=0.1,
                        value=default_settings[
                            f"std_{Ptype.SFC.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
                html.Div([
                    html.Label("Multi-D Rotor",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-std-mrc-input",
                        type="number",
                        min=0,
                        step=0.1,
                        value=default_settings[
                            f"std_{Ptype.MRC.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-3"),
            ], className="row g-2"),
        ], className="border rounded p-3 mt-3"),

        # Distributions (distrib_*)
        html.Div([
            html.H6("Distributions", className="fw-semibold mt-3"),
            html.Div([
                html.Div([
                    html.Label("Well Energy",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-we-dropdown",
                        options=_distrib_options_for_additive(),
                        value=default_settings[
                            f"distrib_{Ptype.WE.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Barrier Energy",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-be-dropdown",
                        options=_distrib_options_for_additive(),
                        value=default_settings[
                            f"distrib_{Ptype.BE.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Ind. Frequencies",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-freq-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.IFC.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Batch Frequencies",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-bfc-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.BFC.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Hindered Rotors",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-hrs-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.HRS.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Imaginary Freq",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-if-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.IF.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
            ], className="row g-2 mb-2"),
            html.Div([
                html.Div([
                    html.Label("Energy Trans. Factor",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-etf-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.ETF.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Energy Trans. Power",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-etp-dropdown",
                        options=_distrib_options_for_additive(),
                        value=default_settings[
                            f"distrib_{Ptype.ETP.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("LJ Epsilon",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-epsi-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.EPSI.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("LJ Sigma",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-sigma-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.SIG.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Symmetry Factor",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-sfc-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.SFC.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
                html.Div([
                    html.Label("Multi-D Rotor",
                               className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-distrib-mrc-dropdown",
                        options=_distrib_options(),
                        value=default_settings[
                            f"distrib_{Ptype.MRC.value}"
                        ],
                        clearable=False,
                    ),
                ], className="col-md-2"),
            ], className="row g-2"),
        ], className="border rounded p-3 mt-3"),

        html.Div([
            html.H6(
                "Parameter Specific Uncertainty",
                className="fw-semibold mt-3"
            ),
            html.Small(
                "Override the default standard deviation for individual SOP "
                "parameters.",
                className="text-muted d-block mb-2"
            ),
            html.Div(
                id="perturbation-specific-std-rows-container",
                children=[],
                className="mt-2"
            ),
            html.Button(
                "Add a parameter uncertainty",
                id="perturbation-specific-std-add-button",
                className="btn btn-outline-primary btn-sm mt-2",
            ),
        ], className="border rounded p-3 mt-3"),

        # Convergence Thresholds
        html.Div([
            html.H6("Convergence Thresholds",
                    className="fw-semibold mt-3"),
            html.Div([
                html.Div([
                    html.Label("Well Energy", className="form-label"),
                    dcc.Input(
                        id="perturbation-conv-we-input",
                        type="number",
                        min=0,
                        max=1,
                        step=0.01,
                        value=default_settings[
                            f"conv_{Ptype.WE.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("Barrier Energy",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-conv-be-input",
                        type="number",
                        min=0,
                        max=1,
                        step=0.01,
                        value=default_settings[
                            f"conv_{Ptype.BE.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("Energy Transfer Power",
                               className="form-label"),
                    dcc.Input(
                        id="perturbation-conv-etp-input",
                        type="number",
                        min=0,
                        max=1,
                        step=0.01,
                        value=default_settings[
                            f"conv_{Ptype.ETP.value}"
                        ],
                        className="form-control",
                    ),
                ], className="col-md-4"),
            ], className="row g-2"),
        ], className="border rounded p-3 mt-3"),

        # Stores
        dcc.Store(id="perturbation-specific-std-store", data=[]),
        dcc.Store(id="perturbation-config-store", data={}),
        dcc.Store(id="perturbation-valid-store", data=False),
        html.Div(
            id="perturbation-validation-message",
            className="mt-3",
            style={"display": "none"}
        ),
    ], className="card p-3 mt-3", id="perturbation-card")


def _distrib_options() -> list:
    """Return all distribution options."""
    return [
        {"label": d.value, "value": d.value}
        for d in Distrib
    ]


def _distrib_options_for_additive() -> list:
    """Return allowed distributions for additive parameters."""
    allowed = [Distrib.UNIFORM, Distrib.NORMAL]
    return [
        {"label": d.value, "value": d.value}
        for d in allowed
    ]


def _build_specific_std_row(
    row_idx: int,
    param_options: list[Any],
    row_data: dict[str, Any],
) -> html.Div:
    """Build one specific standard deviation row."""
    return html.Div([
        html.Div([
            html.Div([
                html.Label("Parameter", className="form-label form-label-sm"),
                dcc.Dropdown(
                    id={"type": "perturbation-specific-std-param",
                        "index": row_idx},
                    options=param_options,
                    value=row_data.get("parameter"),
                    clearable=True,
                    placeholder="Select SOP parameter...",
                    className="mt-0",
                ),
            ], className="col-md-8"),
            html.Div([
                html.Label(
                    "Standard deviation",
                    className="form-label form-label-sm"
                ),
                dcc.Input(
                    id={"type": "perturbation-specific-std-value",
                        "index": row_idx},
                    type="number",
                    min=0,
                    step=0.01,
                    value=row_data.get("std"),
                    placeholder="e.g. 0.25",
                    className="form-control form-control-sm",
                ),
            ], className="col-md-3"),
            html.Div([
                html.Button(
                    "✕",
                    id={"type": "perturbation-specific-std-remove",
                        "index": row_idx},
                    className="btn btn-danger btn-sm mt-4",
                    style={"width": "100%"},
                ),
            ], className="col-md-1"),
        ], className="row g-2 align-items-end"),
    ], className="border rounded p-2 mb-2",
       style={"backgroundColor": "#f8f9fa"})


def _normalize_specific_std_store(data: Any) -> list[dict[str, Any]]:
    """Normalize stored specific standard deviation rows."""
    rows: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for parameter, std in data.items():
            rows.append({"parameter": parameter, "std": std})
        return rows
    if not isinstance(data, list):
        return rows
    for entry in data:
        if not isinstance(entry, dict):
            continue
        rows.append({
            "parameter": entry.get("parameter"),
            "std": entry.get("std"),
        })
    return rows


@callback(
    Output("perturbation-specific-std-store", "data"),
    Input("perturbation-specific-std-add-button", "n_clicks"),
    Input({"type": "perturbation-specific-std-remove", "index": ALL},
          "n_clicks"),
    Input({"type": "perturbation-specific-std-param", "index": ALL},
          "value"),
    Input({"type": "perturbation-specific-std-value", "index": ALL},
          "value"),
    State("perturbation-specific-std-store", "data"),
    prevent_initial_call=True,
)
def update_specific_std_store(
    add_clicks: int,
    _remove_clicks: list[int],
    selected_params: list[str],
    selected_stds: list[float],
    current_store: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Manage the per-parameter uncertainty rows state."""
    rows = _normalize_specific_std_store(current_store)
    triggered = callback_context.triggered_id

    if triggered == "perturbation-specific-std-add-button":
        rows.append({"parameter": None, "std": None})
        return rows

    if (isinstance(triggered, dict) and
            triggered.get("type") == "perturbation-specific-std-remove"):
        row_idx = triggered.get("index")
        if isinstance(row_idx, int) and 0 <= row_idx < len(rows):
            rows.pop(row_idx)
        return rows

    row_count = max(len(rows), len(selected_params or []), len(selected_stds or []))
    updated_rows: list[dict[str, Any]] = []
    for idx in range(row_count):
        existing = rows[idx] if idx < len(rows) else {}
        updated_rows.append({
            "parameter": (
                selected_params[idx]
                if idx < len(selected_params or [])
                else existing.get("parameter")
            ),
            "std": (
                selected_stds[idx]
                if idx < len(selected_stds or [])
                else existing.get("std")
            ),
        })
    return updated_rows


@callback(
    Output("perturbation-specific-std-rows-container", "children"),
    Input("perturbation-specific-std-store", "data"),
    Input("sensitivity-sop-parameter-options-store", "data"),
)
def render_specific_std_rows(
    specific_std_store: list[dict[str, Any]],
    param_names: list[str],
) -> list[html.Div]:
    """Render the specific standard deviation rows."""
    param_options = [
        {"label": param, "value": param}
        for param in (param_names or [])
    ]
    rows = _normalize_specific_std_store(specific_std_store)
    return [
        _build_specific_std_row(idx, param_options, row)
        for idx, row in enumerate(rows)
    ]


@callback(
    output=[
        Output("perturbation-distrib-we-dropdown", "options"),
        Output("perturbation-distrib-be-dropdown", "options"),
        Output("perturbation-distrib-etp-dropdown", "options"),
    ],
    inputs=[
        Input("perturbation-distrib-we-dropdown", "id"),
    ],
    prevent_initial_call=True,
)
def enforce_additive_distributions(_dummy) -> Tuple[list, list, list]:
    """Ensure additive-only parameters use allowed distributions."""
    options_additive = _distrib_options_for_additive()
    return (options_additive, options_additive, options_additive)


@callback(
    Output("perturbation-config-store", "data"),
    Output("perturbation-valid-store", "data"),
    Output("perturbation-validation-message", "children"),
    Output("perturbation-validation-message", "style"),
    Input("perturbation-pert-dropdown", "value"),
    Input("perturbation-max-std-input", "value"),
    Input("perturbation-weight-theory-input", "value"),
    Input("perturbation-weight-experiments-input", "value"),
    # Input("perturbation-freq-mode-dropdown", "value"),
    Input("perturbation-std-we-input", "value"),
    Input("perturbation-std-be-input", "value"),
    # Input("perturbation-std-freq-input", "value"),
    Input("perturbation-std-bfc-input", "value"),
    Input("perturbation-std-hrs-input", "value"),
    Input("perturbation-std-if-input", "value"),
    Input("perturbation-std-etf-input", "value"),
    Input("perturbation-std-etp-input", "value"),
    Input("perturbation-std-epsi-input", "value"),
    Input("perturbation-std-sigma-input", "value"),
    Input("perturbation-std-sfc-input", "value"),
    Input("perturbation-std-mrc-input", "value"),
    Input("perturbation-distrib-we-dropdown", "value"),
    Input("perturbation-distrib-be-dropdown", "value"),
    Input("perturbation-distrib-freq-dropdown", "value"),
    Input("perturbation-distrib-bfc-dropdown", "value"),
    Input("perturbation-distrib-hrs-dropdown", "value"),
    Input("perturbation-distrib-if-dropdown", "value"),
    Input("perturbation-distrib-etf-dropdown", "value"),
    Input("perturbation-distrib-etp-dropdown", "value"),
    Input("perturbation-distrib-epsi-dropdown", "value"),
    Input("perturbation-distrib-sigma-dropdown", "value"),
    Input("perturbation-distrib-sfc-dropdown", "value"),
    Input("perturbation-distrib-mrc-dropdown", "value"),
    Input("perturbation-conv-we-input", "value"),
    Input("perturbation-conv-be-input", "value"),
    Input("perturbation-conv-etp-input", "value"),
    Input("perturbation-specific-std-store", "data"),
    prevent_initial_call=True,
)
def update_perturbation_config(
    pert: str,
    max_std: int,
    weight_theory: float,
    weight_experiments: float,
    # freq_mode: str,
    std_we: float,
    std_be: float,
    # std_freq: float,
    std_bfc: float,
    std_hrs: float,
    std_if: float,
    std_etf: float,
    std_etp: float,
    std_epsi: float,
    std_sigma: float,
    std_sfc: float,
    std_mrc: float,
    distrib_we: str,
    distrib_be: str,
    distrib_freq: str,
    distrib_bfc: str,
    distrib_hrs: str,
    distrib_if: str,
    distrib_etf: str,
    distrib_etp: str,
    distrib_epsi: str,
    distrib_sigma: str,
    distrib_sfc: str,
    distrib_mrc: str,
    conv_we: float,
    conv_be: float,
    conv_etp: float,
    specific_std_rows: list[dict[str, Any]],
) -> Tuple[dict, bool, Any, dict]:
    """Validate and emit perturbation configuration."""
    warnings = []
    specific_std: dict[str, float] = {}
    for idx, row in enumerate(_normalize_specific_std_store(specific_std_rows),
                              start=1):
        parameter = str(row.get("parameter") or "").strip()
        std_value = row.get("std")
        if not parameter and std_value in (None, ""):
            continue
        if not parameter:
            warnings.append(f"Specific row {idx}: select a parameter")
            continue
        if std_value in (None, ""):
            warnings.append(
                f"Specific row {idx}: enter a standard deviation"
            )
            continue
        try:
            parsed_std = float(std_value)
        except (TypeError, ValueError):
            warnings.append(
                f"Specific row {idx}: standard deviation must be numeric"
            )
            continue
        if parsed_std <= 0:
            warnings.append(
                f"Specific row {idx}: standard deviation must be > 0"
            )
            continue
        if parameter in specific_std:
            warnings.append(
                f"Specific row {idx}: parameter {parameter} is duplicated"
            )
            continue
        specific_std[parameter] = parsed_std

    theory_weight_value = (
        default_settings["weight_theory"]
        if weight_theory is None else weight_theory
    )
    experiment_weight_value = (
        default_settings["weight_experiments"]
        if weight_experiments is None else weight_experiments
    )
    if theory_weight_value < 0:
        warnings.append("Theory weight must be >= 0")
    if experiment_weight_value < 0:
        warnings.append("Experiment weight must be >= 0")
    if theory_weight_value == 0 and experiment_weight_value == 0:
        warnings.append(
            "Theory and experiment weights are both zero; runtime scoring "
            "will fall back to an equal split"
        )

    config = {
        "max_std": max_std or default_settings["max_std"],
        "weight_theory": theory_weight_value,
        "weight_experiments": experiment_weight_value,
        "freq_mode": default_settings["freq_mode"],
        "specific_std": specific_std,
        f"std_{Ptype.WE.value}": std_we or
        default_settings[f"std_{Ptype.WE.value}"],
        f"std_{Ptype.BE.value}": std_be or
        default_settings[f"std_{Ptype.BE.value}"],
        f"std_{Ptype.IFC.value}":
        default_settings[f"std_{Ptype.IFC.value}"],
        f"std_{Ptype.BFC.value}": std_bfc or
        default_settings[f"std_{Ptype.BFC.value}"],
        f"std_{Ptype.HRS.value}": std_hrs or
        default_settings[f"std_{Ptype.HRS.value}"],
        f"std_{Ptype.IF.value}": std_if or
        default_settings[f"std_{Ptype.IF.value}"],
        f"std_{Ptype.ETF.value}": std_etf or
        default_settings[f"std_{Ptype.ETF.value}"],
        f"std_{Ptype.ETP.value}": std_etp or
        default_settings[f"std_{Ptype.ETP.value}"],
        f"std_{Ptype.EPSI.value}": std_epsi or
        default_settings[f"std_{Ptype.EPSI.value}"],
        f"std_{Ptype.SIG.value}": std_sigma or
        default_settings[f"std_{Ptype.SIG.value}"],
        f"std_{Ptype.SFC.value}": std_sfc or
        default_settings[f"std_{Ptype.SFC.value}"],
        f"std_{Ptype.MRC.value}": std_mrc or
        default_settings[f"std_{Ptype.MRC.value}"],
        f"distrib_{Ptype.WE.value}": distrib_we or
        default_settings[f"distrib_{Ptype.WE.value}"],
        f"distrib_{Ptype.BE.value}": distrib_be or
        default_settings[f"distrib_{Ptype.BE.value}"],
        f"distrib_{Ptype.IFC.value}": distrib_freq or
        default_settings[f"distrib_{Ptype.IFC.value}"],
        f"distrib_{Ptype.BFC.value}": distrib_bfc or
        default_settings[f"distrib_{Ptype.BFC.value}"],
        f"distrib_{Ptype.HRS.value}": distrib_hrs or
        default_settings[f"distrib_{Ptype.HRS.value}"],
        f"distrib_{Ptype.IF.value}": distrib_if or
        default_settings[f"distrib_{Ptype.IF.value}"],
        f"distrib_{Ptype.ETF.value}": distrib_etf or
        default_settings[f"distrib_{Ptype.ETF.value}"],
        f"distrib_{Ptype.ETP.value}": distrib_etp or
        default_settings[f"distrib_{Ptype.ETP.value}"],
        f"distrib_{Ptype.EPSI.value}": distrib_epsi or
        default_settings[f"distrib_{Ptype.EPSI.value}"],
        f"distrib_{Ptype.SIG.value}": distrib_sigma or
        default_settings[f"distrib_{Ptype.SIG.value}"],
        f"distrib_{Ptype.SFC.value}": distrib_sfc or
        default_settings[f"distrib_{Ptype.SFC.value}"],
        f"distrib_{Ptype.MRC.value}": distrib_mrc or
        default_settings[f"distrib_{Ptype.MRC.value}"],
        f"conv_{Ptype.WE.value}": conv_we or
        default_settings[f"conv_{Ptype.WE.value}"],
        f"conv_{Ptype.BE.value}": conv_be or
        default_settings[f"conv_{Ptype.BE.value}"],
        f"conv_{Ptype.ETP.value}": conv_etp or
        default_settings[f"conv_{Ptype.ETP.value}"],
    }

    # Validate additive distributions
    additive_ptypes = Pclass.ADDITIVE.value
    for ptype in additive_ptypes:
        distrib_key = f"distrib_{ptype}"
        if distrib_key in config:
            dist_val = config[distrib_key]
            if (dist_val == Distrib.LOGNORMAL.value or
                    dist_val == Distrib.LOGUNIFORM.value):
                warnings.append(
                    f"{distrib_key}: log distributions not "
                    f"allowed for additive type {ptype}"
                )

    if warnings:
        msg = html.Div([
            html.Div(
                "\u26a0 Perturbation validation warnings:",
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
