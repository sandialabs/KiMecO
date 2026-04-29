"""Resources section for SLURM, CPU and memory job settings."""
from typing import Any

from dash import Input, Output, State, callback, dcc, html

from kimeco.default_settings import default_settings


def _int_or_default(value: Any, key: str) -> int:
    try:
        if value is None:
            raise TypeError
        return int(value)
    except (TypeError, ValueError):
        return int(default_settings[key])


def _str_or_default(value: Any, key: str) -> str:
    if value is None:
        return str(default_settings[key])
    return str(value)


def _row(*cols) -> html.Div:
    return html.Div(list(cols), className="row g-2 mb-3")


def _col(label: str, help_text: str, *controls) -> html.Div:
    return html.Div([
        html.Label(label, className="form-label fw-semibold"),
        *controls,
        html.Small(help_text, className="form-text text-muted"),
    ], className="col-md-3")


def create_resources_section() -> html.Div:
    """Create the Resources tab for SLURM/CPU/memory settings."""
    ds = default_settings
    return html.Div([
        html.H5("Resources", className="fw-bold"),
        html.Small(
            "Configure SLURM, CPU and memory settings for each job type.",
            className="text-muted d-block mb-3",
        ),

        # ── SLURM ──────────────────────────────────────────────────────────
        html.H6("SLURM", className="fw-semibold mt-2"),
        _row(
            html.Div([
                html.Label(
                    "Excluded nodes",
                    className="form-label fw-semibold"
                ),
                dcc.Input(
                    id="res-exclude-nodes",
                    type="text",
                    value=ds["exclude_nodes"],
                    placeholder="e.g. node01,node02",
                    debounce=True,
                    className="form-control form-control-sm",
                ),
                html.Small(
                    "Passed to #SBATCH --exclude. Leave blank to disable.",
                    className="form-text text-muted",
                ),
            ], className="col-md-6"),
        ),

        html.Hr(),

        # ── Per-job resources ───────────────────────────────────────────────
        html.H6("Per-job resources", className="fw-semibold"),
        html.Div([
            html.Div([
                html.Div("", className="col-md-3"),
                html.Div(
                    html.Strong("CPUs"),
                    className="col-md-3 text-center"
                ),
                html.Div(
                    html.Strong("Memory (MB)"),
                    className="col-md-3 text-center"
                ),
            ], className="row g-2 mb-1"),

            # Kinetics row
            html.Div([
                html.Div(
                    html.Span(
                        "Master equation (kinetics)",
                        className="form-text fw-semibold"
                    ),
                    className="col-md-3 d-flex align-items-center"
                ),
                html.Div([
                    dcc.Input(
                        id="res-cpu-kin",
                        type="number",
                        min=1,
                        step=1,
                        value=ds["cpu_kin"],
                        className="form-control form-control-sm text-center",
                    ),
                ], className="col-md-3"),
                html.Div([
                    dcc.Input(
                        id="res-mem-kin",
                        type="number",
                        min=1,
                        step=100,
                        value=ds["mem_kin"],
                        className="form-control form-control-sm text-center",
                    ),
                ], className="col-md-3"),
            ], className="row g-2 mb-2"),

            # Simulation row
            html.Div([
                html.Div(
                    html.Span(
                        "Simulation (Cantera)",
                        className="form-text fw-semibold"
                    ),
                    className="col-md-3 d-flex align-items-center"
                ),
                html.Div([
                    dcc.Input(
                        id="res-cpu-sim",
                        type="number",
                        min=1,
                        step=1,
                        value=ds["cpu_sim"],
                        className="form-control form-control-sm text-center",
                    ),
                ], className="col-md-3"),
                html.Div([
                    dcc.Input(
                        id="res-mem-sim",
                        type="number",
                        min=1,
                        step=100,
                        value=ds["mem_sim"],
                        className="form-control form-control-sm text-center",
                    ),
                ], className="col-md-3"),
            ], className="row g-2 mb-2"),
        ]),

        html.Hr(),

        # ── Global generation limits ────────────────────────────────────────
        html.H6("Global limits", className="fw-semibold"),
        _row(
            _col(
                "Max total CPUs",
                "Total CPU budget; submission stalls when exceeded.",
                dcc.Input(
                    id="res-max-cpu",
                    type="number", min=1, step=1,
                    value=ds["max_cpu"],
                    className="form-control form-control-sm",
                ),
            ),
            _col(
                "Max memory (MB)",
                "Total memory budget; submission stalls when exceeded.",
                dcc.Input(
                    id="res-max-mem",
                    type="number", min=1, step=1000,
                    value=ds["max_mem"],
                    className="form-control form-control-sm",
                ),
            ),
            _col(
                "Max jobs for this KiMecO instance",
                "",
                dcc.Input(
                    id="res-max-jobs",
                    type="number", min=1, step=1,
                    value=ds["max_jobs"],
                    className="form-control form-control-sm",
                ),
            ),
            _col(
                "Max jobs for user on the cluster",
                "",
                dcc.Input(
                    id="res-max-user-jobs",
                    type="number", min=1, step=1,
                    value=ds["max_user_jobs"],
                    className="form-control form-control-sm",
                ),
            ),
        ),

        html.Div(id="resources-validation-message", className="mt-2"),
        dcc.Store(id="resources-config-store", data=_default_config()),
        dcc.Store(id="resources-valid-store", data=True),
    ], className="card p-3 mt-3", id="resources-card")


def _default_config() -> dict:
    ds = default_settings
    return {
        "cpu_kin": ds["cpu_kin"],
        "mem_kin": ds["mem_kin"],
        "cpu_sim": ds["cpu_sim"],
        "mem_sim": ds["mem_sim"],
        "max_cpu": ds["max_cpu"],
        "max_mem": ds["max_mem"],
        "max_jobs": ds["max_jobs"],
        "max_user_jobs": ds["max_user_jobs"],
        "exclude_nodes": ds["exclude_nodes"],
    }


@callback(
    Output("resources-config-store", "data"),
    Output("resources-valid-store", "data"),
    Output("resources-validation-message", "children"),
    Input("res-cpu-kin", "value"),
    Input("res-mem-kin", "value"),
    Input("res-cpu-sim", "value"),
    Input("res-mem-sim", "value"),
    Input("res-max-cpu", "value"),
    Input("res-max-mem", "value"),
    Input("res-max-jobs", "value"),
    Input("res-max-user-jobs", "value"),
    Input("res-exclude-nodes", "value"),
    State("resources-config-store", "data"),
)
def update_resources_config(
    cpu_kin: Any,
    mem_kin: Any,
    cpu_sim: Any,
    mem_sim: Any,
    max_cpu: Any,
    max_mem: Any,
    max_jobs: Any,
    max_user_jobs: Any,
    exclude_nodes: Any,
    _prev: dict,
) -> tuple[dict, bool, Any]:
    """Validate resource settings and emit a config store update."""
    config = {
        "cpu_kin": _int_or_default(cpu_kin, "cpu_kin"),
        "mem_kin": _int_or_default(mem_kin, "mem_kin"),
        "cpu_sim": _int_or_default(cpu_sim, "cpu_sim"),
        "mem_sim": _int_or_default(mem_sim, "mem_sim"),
        "max_cpu": _int_or_default(max_cpu, "max_cpu"),
        "max_mem": _int_or_default(max_mem, "max_mem"),
        "max_jobs": _int_or_default(max_jobs, "max_jobs"),
        "max_user_jobs": _int_or_default(max_user_jobs, "max_user_jobs"),
        "exclude_nodes": _str_or_default(exclude_nodes, "exclude_nodes"),
    }

    warnings: list[str] = []
    if config["cpu_kin"] > config["max_cpu"]:
        warnings.append(
            f"cpu_kin ({config['cpu_kin']}) > max_cpu ({config['max_cpu']})"
        )
    if config["cpu_sim"] > config["max_cpu"]:
        warnings.append(
            f"cpu_sim ({config['cpu_sim']}) > max_cpu ({config['max_cpu']})"
        )
    if config["mem_kin"] > config["max_mem"]:
        warnings.append(
            f"mem_kin ({config['mem_kin']}) > max_mem ({config['max_mem']})"
        )
    if config["mem_sim"] > config["max_mem"]:
        warnings.append(
            f"mem_sim ({config['mem_sim']}) > max_mem ({config['max_mem']})"
        )

    if warnings:
        msg = html.Div([
            html.Div(
                "⚠ Resource warnings:",
                style={"color": "orange", "fontWeight": "bold"}
            ),
            html.Ul([html.Li(w) for w in warnings]),
        ])
        return config, True, msg

    return config, True, ""
