"""Theoretical uncertainties (perturbation) section."""

from typing import Any, Tuple
from dash import dcc, html, Input, Output, callback

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
                    html.Label("Perturbator Type", className="form-label"),
                    dcc.Dropdown(
                        id="perturbation-pert-dropdown",
                        options=[{"label": "normal", "value": "normal"}],
                        value=default_settings["pert"],
                        clearable=False,
                    ),
                ], className="col-md-4"),
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
    prevent_initial_call=True,
)
def update_perturbation_config(
    pert: str,
    max_std: int,
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
) -> Tuple[dict, bool, Any, dict]:
    """Validate and emit perturbation configuration."""
    config = {
        "pert": pert or default_settings["pert"],
        "max_std": max_std or default_settings["max_std"],
        "freq_mode": default_settings["freq_mode"],
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
    warnings = []
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
