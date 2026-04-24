"""Optimizer section for optimization settings."""
from dash import html


def create_optimizer_section() -> html.Div:
    """Create optimizer settings tab."""
    return html.Div([
        html.H5("Optimizer Settings", className="fw-bold"),
        html.Small(
            "Configure optimization parameters",
            className="text-muted"
        ),
        html.Div(id="optimizer-params-container"),
    ], className="card p-3 mt-3", id="optimizer-card")
