"""Experiments section for building experiment configurations."""
from dash import dcc, html, Input, Output, State, callback


def create_experiments_section() -> html.Div:
    """Create experiments tab section."""
    return html.Div([
            html.H5("Experiments", className="fw-bold"),
            html.Small(
                "Configure experimental conditions",
                className="text-muted"
            ),
            html.Div(id="experiments-table"),
            html.Button(
                "Add Experiment",
                id="add-experiment-button",
                className="btn btn-primary btn-sm",
                style={"marginTop": "10px"}
            ),
            dcc.Store(id="experiments-store", data=[]),
        ], className="card p-3 mt-3", id="experiments-card")


@callback(
    [
        Output("experiments-store", "data"),
        Output("experiments-table", "children"),
        Output("experiment-count-store", "data"),
    ],
    Input("add-experiment-button", "n_clicks"),
    State("experiments-store", "data"),
    prevent_initial_call=True
)
def add_experiment(
    n_clicks: int,
    experiments: list,
) -> tuple[list, html.Div, int]:
    """Add a placeholder validated experiment entry and update count."""
    if experiments is None:
        experiments = []

    if n_clicks:
        experiment_id = len(experiments) + 1
        experiments = [
            *experiments,
            {
                "id": experiment_id,
                "name": f"Experiment {experiment_id}",
                "validated": True,
            },
        ]

    rows = [
        html.Div(
            f"✓ {exp['name']}",
            style={"marginBottom": "6px", "color": "green"},
        )
        for exp in experiments
    ]
    table = html.Div(rows if rows else [
        html.Small("No experiments added", className="text-muted")
    ])
    return experiments, table, len(experiments)
