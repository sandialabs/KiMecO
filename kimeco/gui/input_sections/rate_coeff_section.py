"""Rate coefficient section for rate coefficient settings."""
from dash import html


def create_rate_coeff_section() -> html.Div:
    """Create rate coefficient settings tab."""
    return html.Div([
        html.H5("Rate Coefficient Settings", className="fw-bold"),
        html.Small(
            "Configure rate coefficient parameters",
            className="text-muted"
        ),
        html.Div(id="rate-coeff-params-container"),
    ], className="card p-3 mt-3", id="rate-coeff-card")
