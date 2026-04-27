"""Optimizer section for optimization settings."""

from __future__ import annotations

from typing import Any

from dash import Input, Output, callback, dcc, html

from kimeco.default_settings import default_settings


SCHEME_EXPMC_GA = "scheme-expmc-ga"
SCHEME_TOURNAMENT_GA = "scheme-tournament-ga"
SCHEME_NELDER_MEAD = "scheme-nelder-mead"
SCHEME_SWARM_NM = "scheme-swarm-nm"
SCHEME_SWARM_NM_GOAT = "scheme-swarm-nm-goat"


def _int_or_default(value: Any, key: str) -> int:
    """Convert GUI value to int and fallback to defaults on invalid input."""
    try:
        if value is None:
            raise TypeError
        return int(value)
    except (TypeError, ValueError):
        return int(default_settings[key])


def _float_or_default(value: Any, key: str) -> float:
    """Convert GUI value to float and fallback to defaults on invalid input."""
    try:
        if value is None:
            raise TypeError
        return float(value)
    except (TypeError, ValueError):
        return float(default_settings[key])


def _scheme_runtime(scheme: str,
                    max_gen: int) -> tuple[str, str, str, int]:
    """Map UI scheme to runtime optimizer fields."""
    if scheme == SCHEME_TOURNAMENT_GA:
        return "ga", "tournament", "", max_gen
    if scheme == SCHEME_NELDER_MEAD:
        return "nelder-mead", "tournament", "", max_gen
    if scheme == SCHEME_SWARM_NM:
        return "ga", "exp", "G0001", 1
    if scheme == SCHEME_SWARM_NM_GOAT:
        return "ga", "exp", "GT-1", max_gen
    return "ga", "exp", "", max_gen


def _validate_config(config: dict[str, Any]) -> tuple[bool, str]:
    """Validate optimizer numeric domains before emitting config."""
    if config["max_gen"] < 1:
        return False, "max_gen must be >= 1."
    if config["n_elem"] < 1:
        return False, "n_elem must be >= 1."
    if config["goat_length"] < 1:
        return False, "goat_length must be >= 1."
    if config["SA_freq"] < 1:
        return False, "SA_freq must be >= 1."
    if config["SA_start"] < 1:
        return False, "SA_start must be >= 1."
    if config["SA_end"] <= config["SA_start"]:
        return False, "SA_end must be > SA start."
    if config["max_score"] <= 0:
        return False, "max_score must be > 0."
    if config["score_conv"] <= 0:
        return False, "score_conv must be > 0."
    if config["param_conv"] <= 0:
        return False, "param_conv must be > 0."
    if config["nm_fatol"] <= 0 or config["nm_xatol"] <= 0:
        return False, "nm_fatol and nm_xatol must be > 0."
    if config["nm_maxiter"] < 0 or config["nm_maxfev"] < 0:
        return False, "nm_maxiter and nm_maxfev must be >= 0."
    if config["nm_dstep"] <= 0:
        return False, "nm_dstep must be > 0."
    if config["nm_final_fatol"] <= 0 or config["nm_final_xatol"] <= 0:
        return False, "nm_final_fatol and nm_final_xatol must be > 0."
    if config["nm_final_maxiter"] < 0 or config["nm_final_maxfev"] < 0:
        return False, "nm_final_maxiter and nm_final_maxfev must be >= 0."
    if config["optimizer"] not in {"ga", "nelder-mead"}:
        return False, "optimizer must be ga or nelder-mead."
    if config["optimizer"] == "ga" and config["ga_type"] not in {
        "exp", "tournament"
    }:
        return False, "ga_type must be exp or tournament for GA."
    return True, "Optimizer settings are valid."


def create_optimizer_section() -> html.Div:
    """Create optimizer settings tab."""
    return html.Div([
        html.H5("Optimizer Settings", className="fw-bold"),
        html.Small(
            "Select an optimization scheme and tune relevant settings.",
            className="text-muted"
        ),
        html.Div([
            html.Label("Optimization Scheme", className="fw-semibold mt-3"),
            dcc.Dropdown(
                id="optimizer-scheme-dropdown",
                options=[
                    {
                        "label": "ExpMC GA (Recommended)",
                        "value": SCHEME_EXPMC_GA
                    },
                    {
                        "label": "Tournament GA",
                        "value": SCHEME_TOURNAMENT_GA
                    },
                    {
                        "label": "Nelder Mead",
                        "value": SCHEME_NELDER_MEAD
                    },
                    {
                        "label": "Swarm of Nelder-Mead",
                        "value": SCHEME_SWARM_NM
                    },
                    {
                        "label": "Swarm of Nelder-Mead from best models",
                        "value": SCHEME_SWARM_NM_GOAT
                    },
                ],
                value=SCHEME_EXPMC_GA,
                clearable=False,
                className="mt-1"
            ),
        ]),
        html.Div(
            id="optimizer-runtime-summary",
            className="alert alert-info mt-3 mb-2",
            role="alert"
        ),
        html.Div(
            id="optimizer-validation-message",
            className="mt-2",
            style={"display": "none"}
        ),
        html.Div([
            html.H6("Runtime Mapping", className="fw-semibold"),
            html.Div([
                html.Small("Optimizer:", className="text-muted me-2"),
                html.Code(id="optimizer-derived-optimizer")
            ], className="mb-1"),
            html.Div([
                html.Small("GA Type:", className="text-muted me-2"),
                html.Code(id="optimizer-derived-ga-type")
            ], className="mb-1"),
            html.Div(id="optimizer-nms-start-row", children=[
                html.Small("NMS_start:", className="text-muted me-2"),
                dcc.Input(
                    id="optimizer-nms-start-input",
                    type="text",
                    value="",
                    debounce=True,
                    disabled=True,
                    className="form-control form-control-sm d-inline-block",
                    style={"width": "180px"}
                ),
            ]),
        ], className="border rounded p-2 mt-2"),
        html.Div(id="optimizer-ga-controls", children=[
            html.H6("Genetic Algorithm settings", className="fw-semibold mt-3"),
            html.Div([
                html.Div([
                    html.Label("# of models", className="form-label"),
                    dcc.Input(
                        id="optimizer-n-elem-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["n_elem"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("Max Generations", className="form-label"),
                    dcc.Input(
                        id="optimizer-max-gen-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["max_gen"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("Best models size", className="form-label"),
                    dcc.Input(
                        id="optimizer-goat-length-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["goat_length"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
            ], className="row g-2"),
            html.Div([
                html.Div([
                    html.Label("Max. Score in best models", className="form-label"),
                    dcc.Input(
                        id="optimizer-max-score-input",
                        type="number",
                        min=0,
                        step=1e-3,
                        value=default_settings["max_score"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("Avrg. Score in best models", className="form-label"),
                    dcc.Input(
                        id="optimizer-score-conv-input",
                        type="number",
                        min=0,
                        step=1e-4,
                        value=default_settings["score_conv"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("param_conv", className="form-label"),
                    dcc.Input(
                        id="optimizer-param-conv-input",
                        type="number",
                        min=0,
                        step=1e-4,
                        value=default_settings["param_conv"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
            ], className="row g-2 mt-1"),
        ], className="mt-2"),
        html.Div(id="optimizer-ga-sa-controls", children=[
            html.H6("On-the-fly Sensitivity analysis settings", className="fw-semibold mt-3"),
            html.Div([
                html.Div([
                    html.Label("Frequency", className="form-label"),
                    dcc.Input(
                        id="optimizer-sa-freq-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["SA_freq"],
                        className="form-control"
                    ),
                ], className="col-md-6"),
                html.Div([
                    html.Label("Start at generation:", className="form-label"),
                    dcc.Input(
                        id="optimizer-sa-start-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["SA_start"],
                        className="form-control"
                    ),
                ], className="col-md-6"),
                html.Div([
                    html.Label("End at generation:", className="form-label"),
                    dcc.Input(
                        id="optimizer-sa-end-input",
                        type="number",
                        min=1,
                        step=1,
                        value=default_settings["SA_end"],
                        className="form-control"
                    ),
                ], className="col-md-6"),
            ], className="row g-2")
        ], className="mt-2"),
        html.Div(id="optimizer-nm-controls", children=[
            html.H6("Nelder-Mead Controls", className="fw-semibold mt-3"),
            html.Div([
                html.Div([
                    html.Label("nm_fatol", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-fatol-input",
                        type="number",
                        min=0,
                        step=1e-4,
                        value=default_settings["nm_fatol"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("nm_xatol", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-xatol-input",
                        type="number",
                        min=0,
                        step=1e-4,
                        value=default_settings["nm_xatol"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("Simplex size", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-dstep-input",
                        type="number",
                        min=0,
                        step=1e-3,
                        value=default_settings["nm_dstep"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
            ], className="row g-2"),
            html.Div([
                html.Div([
                    html.Label("nm_maxiter", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-maxiter-input",
                        type="number",
                        min=0,
                        step=1,
                        value=default_settings["nm_maxiter"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("nm_maxfev", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-maxfev-input",
                        type="number",
                        min=0,
                        step=1,
                        value=default_settings["nm_maxfev"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("nm_adaptive", className="form-label"),
                    dcc.Checklist(
                        id="optimizer-nm-adaptive-input",
                        options=[{"label": "enabled", "value": "on"}],
                        value=["on"] if default_settings["nm_adaptive"]
                        else [],
                        className="mt-1"
                    ),
                ], className="col-md-4"),
            ], className="row g-2 mt-1"),
        ], className="mt-2"),
        html.Div(id="optimizer-nm-final-controls", children=[
            html.H6(
                "Swarm Nelder-Mead Refinement",
                className="fw-semibold mt-3"
            ),
            html.Small(
                "These controls apply to each NM instance in the swarm.",
                className="text-muted"
            ),
            html.Div([
                html.Div([
                    html.Label("nm_final_fatol", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-final-fatol-input",
                        type="number",
                        min=0,
                        step=1e-4,
                        value=default_settings["nm_final_fatol"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("nm_final_xatol", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-final-xatol-input",
                        type="number",
                        min=0,
                        step=1e-4,
                        value=default_settings["nm_final_xatol"],
                        className="form-control"
                    ),
                ], className="col-md-4"),
                html.Div([
                    html.Label("nm_final_adaptive", className="form-label"),
                    dcc.Checklist(
                        id="optimizer-nm-final-adaptive-input",
                        options=[{"label": "enabled", "value": "on"}],
                        value=["on"]
                        if default_settings["nm_final_adaptive"] else [],
                        className="mt-1"
                    ),
                ], className="col-md-4"),
            ], className="row g-2"),
            html.Div([
                html.Div([
                    html.Label("nm_final_maxiter", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-final-maxiter-input",
                        type="number",
                        min=0,
                        step=1,
                        value=default_settings["nm_final_maxiter"],
                        className="form-control"
                    ),
                ], className="col-md-6"),
                html.Div([
                    html.Label("nm_final_maxfev", className="form-label"),
                    dcc.Input(
                        id="optimizer-nm-final-maxfev-input",
                        type="number",
                        min=0,
                        step=1,
                        value=default_settings["nm_final_maxfev"],
                        className="form-control"
                    ),
                ], className="col-md-6"),
            ], className="row g-2 mt-1"),
        ], className="mt-2"),
        html.Div(id="optimizer-params-container"),
    ], className="card p-3 mt-3", id="optimizer-card")


@callback(
    Output("optimizer-ga-controls", "style"),
    Output("optimizer-ga-sa-controls", "style"),
    Output("optimizer-nm-controls", "style"),
    Output("optimizer-nm-final-controls", "style"),
    Output("optimizer-nms-start-row", "style"),
    Output("optimizer-max-gen-input", "value"),
    Output("optimizer-max-gen-input", "disabled"),
    Output("optimizer-nms-start-input", "value"),
    Output("optimizer-nms-start-input", "disabled"),
    Output("optimizer-derived-optimizer", "children"),
    Output("optimizer-derived-ga-type", "children"),
    Output("optimizer-runtime-summary", "children"),
    Output("optimizer-config-store", "data"),
    Output("optimizer-valid-store", "data"),
    Output("optimizer-validation-message", "children"),
    Output("optimizer-validation-message", "style"),
    Input("optimizer-scheme-dropdown", "value"),
    Input("optimizer-max-gen-input", "value"),
    Input("optimizer-n-elem-input", "value"),
    Input("optimizer-goat-length-input", "value"),
    Input("optimizer-max-score-input", "value"),
    Input("optimizer-score-conv-input", "value"),
    Input("optimizer-param-conv-input", "value"),
    Input("optimizer-sa-freq-input", "value"),
    Input("optimizer-sa-start-input", "value"),
    Input("optimizer-sa-end-input", "value"),
    Input("optimizer-nm-fatol-input", "value"),
    Input("optimizer-nm-xatol-input", "value"),
    Input("optimizer-nm-maxiter-input", "value"),
    Input("optimizer-nm-maxfev-input", "value"),
    Input("optimizer-nm-dstep-input", "value"),
    Input("optimizer-nm-adaptive-input", "value"),
    Input("optimizer-nm-final-fatol-input", "value"),
    Input("optimizer-nm-final-xatol-input", "value"),
    Input("optimizer-nm-final-maxiter-input", "value"),
    Input("optimizer-nm-final-maxfev-input", "value"),
    Input("optimizer-nm-final-adaptive-input", "value"),
)
def update_optimizer_scheme(
    scheme: str,
    max_gen_value: Any,
    n_elem_value: Any,
    goat_length_value: Any,
    max_score_value: Any,
    score_conv_value: Any,
    param_conv_value: Any,
    sa_freq_value: Any,
    sa_start_value: Any,
    sa_end_value: Any,
    nm_fatol_value: Any,
    nm_xatol_value: Any,
    nm_maxiter_value: Any,
    nm_maxfev_value: Any,
    nm_dstep_value: Any,
    nm_adaptive_value: list[str],
    nm_final_fatol_value: Any,
    nm_final_xatol_value: Any,
    nm_final_maxiter_value: Any,
    nm_final_maxfev_value: Any,
    nm_final_adaptive_value: list[str],
) -> tuple[Any, ...]:
    """Update visible controls and emit runtime-compatible optimizer config."""
    max_gen = _int_or_default(max_gen_value, "max_gen")
    optimizer, ga_type, nms_start, runtime_max_gen = _scheme_runtime(
        scheme=scheme,
        max_gen=max_gen
    )

    config = {
        "optimizer_scheme": scheme,
        "optimizer": optimizer,
        "ga_type": ga_type,
        "NMS_start": nms_start,
        "max_gen": runtime_max_gen,
        "n_elem": _int_or_default(n_elem_value, "n_elem"),
        "goat_length": _int_or_default(goat_length_value, "goat_length"),
        "max_score": _float_or_default(max_score_value, "max_score"),
        "score_conv": _float_or_default(score_conv_value, "score_conv"),
        "param_conv": _float_or_default(param_conv_value, "param_conv"),
        "SA_freq": _int_or_default(sa_freq_value, "SA_freq"),
        "SA_start": _int_or_default(sa_start_value, "SA_start"),
        "SA_end": _int_or_default(sa_end_value, "SA_end"),
        "nm_fatol": _float_or_default(nm_fatol_value, "nm_fatol"),
        "nm_xatol": _float_or_default(nm_xatol_value, "nm_xatol"),
        "nm_maxiter": _int_or_default(nm_maxiter_value, "nm_maxiter"),
        "nm_maxfev": _int_or_default(nm_maxfev_value, "nm_maxfev"),
        "nm_dstep": _float_or_default(nm_dstep_value, "nm_dstep"),
        "nm_adaptive": bool(nm_adaptive_value),
        "nm_final_fatol": _float_or_default(
            nm_final_fatol_value,
            "nm_final_fatol"
        ),
        "nm_final_xatol": _float_or_default(
            nm_final_xatol_value,
            "nm_final_xatol"
        ),
        "nm_final_maxiter": _int_or_default(
            nm_final_maxiter_value,
            "nm_final_maxiter"
        ),
        "nm_final_maxfev": _int_or_default(
            nm_final_maxfev_value,
            "nm_final_maxfev"
        ),
        "nm_final_adaptive": bool(nm_final_adaptive_value),
    }

    is_swarm = scheme in {SCHEME_SWARM_NM, SCHEME_SWARM_NM_GOAT}
    is_ga = scheme in {
        SCHEME_EXPMC_GA,
        SCHEME_TOURNAMENT_GA,
        SCHEME_SWARM_NM,
        SCHEME_SWARM_NM_GOAT,
    }
    is_nm = scheme == SCHEME_NELDER_MEAD

    visible = {"display": "block"}
    hidden = {"display": "none"}

    valid, validation_msg = _validate_config(config=config)
    validation_style = {
        "display": "block",
        "color": "green" if valid else "red",
        "fontWeight": "bold" if valid else "normal",
        "marginTop": "8px",
    }

    summary = (
        f"Runtime fields -> optimizer={optimizer}, "
        f"ga_type={ga_type}, max_gen={runtime_max_gen}, "
        f"NMS_start={nms_start or '<empty>'}"
    )

    return (
        visible if is_ga else hidden,
        visible if (is_ga and not is_swarm) else hidden,
        visible if is_nm else hidden,
        visible if is_swarm else hidden,
        visible if is_swarm else hidden,
        runtime_max_gen,
        is_swarm,
        nms_start,
        True,
        optimizer,
        ga_type,
        summary,
        config,
        valid,
        validation_msg,
        validation_style,
    )
