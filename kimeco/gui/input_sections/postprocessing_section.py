"""Postprocessing section for postprocessing settings."""
from dash import html


def create_postprocessing_section() -> html.Div:
    """Create postprocessing settings tab."""
    return html.Div([
        html.H5(
            "Postprocessing Settings",
            className="fw-bold"
        ),
        html.Small(
            "Configure postprocessing parameters",
            className="text-muted"
        ),
        html.Div(id="postprocessing-params-container"),
    ], className="card p-3 mt-3", id="postprocessing-card")
