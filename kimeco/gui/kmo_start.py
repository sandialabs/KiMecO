"""
kmo_start - Graphical interface for creating KiMecO input files.

This is a Dash/Plotly web application that guides users through creating
valid JSON input files for KiMecO with a progressive validation workflow.
"""


import dash
from dash import html, dcc, Input, Output, callback

from kimeco.gui.input_sections.mechanism_section import (
    create_mechanism_section
)
from kimeco.gui.input_sections.sop_section import create_sop_section
from kimeco.gui.input_sections.experiments_section import (
    create_experiments_section
)
from kimeco.gui.input_sections.optimizer_section import (
    create_optimizer_section
)
from kimeco.gui.input_sections.rate_coeff_section import (
    create_rate_coeff_section
)
from kimeco.gui.input_sections.postprocessing_section import (
    create_postprocessing_section
)
from kimeco.gui.input_sections.perturbation_section import (
    create_perturbation_section
)
from kimeco.gui.input_sections.advanced_section import (
    create_advanced_section
)
from kimeco.gui.input_sections.save_load_write_section import (
    create_save_load_write_section
)


class KMOStartApp:
    """Dash application for creating KiMecO input files."""

    def __init__(self):
        """Initialize the KMO Start application."""
        self.app = dash.Dash(
            __name__,
            external_stylesheets=[
                "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/"
                "bootstrap.min.css"
            ]
        )
        self.setup_layout()
        self.setup_callbacks()

    def setup_layout(self) -> None:
        """Build the application layout."""
        self.app.layout = html.Div([
                html.Div([
                    html.H1(
                        "KiMecO Input Configuration",
                        className="mt-4 mb-4 text-primary"
                    ),
                    html.P(
                        "Create a JSON input file for KiMecO",
                        className="lead text-muted"
                    ),
                ]),

                # Tab structure with validation-based locking
                dcc.Tabs(
                    id="main-tabs",
                    value="mechanism-tab",
                    children=[
                        dcc.Tab(
                            label="1. Mechanism",
                            value="mechanism-tab",
                            children=[
                                html.Div(
                                    create_mechanism_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="2. SOP",
                            value="sop-tab",
                            children=[
                                html.Div(
                                    create_sop_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="3. Experiments",
                            value="experiments-tab",
                            disabled=True,
                            id="experiments-tab",
                            children=[
                                html.Div(
                                    create_experiments_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="4. Optimizer",
                            value="optimizer-tab",
                            disabled=True,
                            id="optimizer-tab",
                            children=[
                                html.Div(
                                    create_optimizer_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="5. Rate Coeff",
                            value="rate-coeff-tab",
                            disabled=True,
                            id="rate-coeff-tab",
                            children=[
                                html.Div(
                                    create_rate_coeff_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="6. Postprocessing",
                            value="postprocessing-tab",
                            disabled=True,
                            id="postprocessing-tab",
                            children=[
                                html.Div(
                                    create_postprocessing_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="7. Perturbation",
                            value="perturbation-tab",
                            disabled=True,
                            id="perturbation-tab",
                            children=[
                                html.Div(
                                    create_perturbation_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="8. Advanced",
                            value="advanced-tab",
                            disabled=True,
                            id="advanced-tab",
                            children=[
                                html.Div(
                                    create_advanced_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                        dcc.Tab(
                            label="9. Save & Write",
                            value="save-write-tab",
                            children=[
                                html.Div(
                                    create_save_load_write_section(),
                                    style={"marginTop": "20px"}
                                )
                            ]
                        ),
                    ]
                ),

                # State stores for validation tracking
                dcc.Store(
                    id="mechanism-valid-store",
                    data=False
                ),
                dcc.Store(
                    id="sop-valid-store",
                    data=False
                ),
                dcc.Store(
                    id="experiment-count-store",
                    data=0
                ),

                html.Div(style={"marginTop": "40px", "marginBottom": "20px"}),
            ]
        )

    def setup_callbacks(self) -> None:
        """Set up all Dash callbacks for validation and state management."""
        # Callback to enable/disable Experiments tab based on validation
        @callback(
            Output("experiments-tab", "disabled"),
            [
                Input("mechanism-valid-store", "data"),
                Input("sop-valid-store", "data")
            ],
            prevent_initial_call=True
        )
        def toggle_experiments_tab(mechanism_valid: bool,
                                   sop_valid: bool) -> bool:
            """Enable experiments tab only when mechanism and SOP valid."""
            return not (mechanism_valid and sop_valid)

        # Callback to enable/disable settings tabs based on experiments
        @callback(
            [
                Output("optimizer-tab", "disabled"),
                Output("rate-coeff-tab", "disabled"),
                Output("postprocessing-tab", "disabled"),
                Output("perturbation-tab", "disabled"),
                Output("advanced-tab", "disabled"),
            ],
            Input("experiment-count-store", "data"),
            prevent_initial_call=True
        )
        def toggle_settings_tabs(experiment_count: int) -> tuple:
            """Enable settings tabs only when ≥1 experiment valid."""
            disabled = experiment_count < 1
            return (disabled, disabled, disabled, disabled, disabled)

    def run(self, debug: bool = True, port: int = 8000) -> None:
        """Run the Dash application."""
        self.app.run(debug=debug, port=port)


def main() -> None:
    """Entry point for the kmo_start command."""
    app = KMOStartApp()
    app.run(debug=True, port=8000)


if __name__ == "__main__":
    main()
