"""Perturbation section for perturbation settings."""
from dash import html


def create_perturbation_section() -> html.Div:
    """Create perturbation settings tab."""
    return html.Div([
        html.H5("Perturbation Settings", className="fw-bold"),
        html.Small(
            "Configure perturbation parameters",
            className="text-muted"
        ),
        html.Div(id="perturbation-params-container"),
    ], className="card p-3 mt-3", id="perturbation-card")
