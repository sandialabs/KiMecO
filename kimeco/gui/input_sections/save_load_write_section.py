"""Save/Load/Write section for configuration management."""
from dash import dcc, html


def create_save_load_write_section() -> html.Div:
    """Create save/load/write section."""
    return html.Div([
            html.H5("Save & Write Configuration", className="fw-bold"),
            html.Div([
                html.Button(
                    "Save Config",
                    id="save-config-button",
                    className="btn btn-info btn-sm",
                    style={"width": "24%", "marginTop": "10px",
                           "marginRight": "1%"}
                ),
                html.Button(
                    "Load Config",
                    id="load-config-button",
                    className="btn btn-info btn-sm",
                    style={"width": "24%", "marginTop": "10px",
                           "marginRight": "1%"}
                ),
                dcc.Input(
                    id="output-filename-input",
                    type="text",
                    placeholder="input.json",
                    className="form-control",
                    style={"marginTop": "10px", "width": "24%",
                           "display": "inline-block", "marginRight": "1%"}
                ),
                html.Button(
                    "Write JSON",
                    id="write-json-button",
                    className="btn btn-success btn-sm",
                    style={"marginTop": "10px", "width": "24%",
                           "verticalAlign": "top"}
                ),
            ]),
            html.Div(
                id="write-status-message",
                style={
                    "marginTop": "15px",
                    "padding": "10px",
                    "borderRadius": "5px",
                    "display": "none"
                }
            ),
            dcc.Download(id="config-download"),
        ], className="card p-3 mt-3")
