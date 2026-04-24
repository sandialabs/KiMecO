"""Advanced section for miscellaneous settings."""
from dash import html


def create_advanced_section() -> html.Div:
    """Create advanced settings tab."""
    return html.Div([
        html.H5("Advanced Settings", className="fw-bold"),
        html.Small(
            "Configure advanced parameters",
            className="text-muted"
        ),
        html.Div(id="advanced-params-container"),
    ], className="card p-3 mt-3", id="advanced-card")
