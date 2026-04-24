"""SOP section for mess_inputs file selection and validation."""
from typing import Tuple
import os
import logging
from dash import (
    ALL,
    dcc,
    html,
    Input,
    Output,
    State,
    callback,
    callback_context,
)
import dash

from kimeco.gui.input_sections.mechanism_section import get_loaded_kinmec


_SOP_BROWSER_ROOT = os.getcwd()


def _build_sop_browser_buttons(cwd: str) -> list:
    """Build clickable button entries for the SOP file browser."""
    current_dir = os.path.abspath(cwd or _SOP_BROWSER_ROOT)
    root_abs = os.path.abspath(_SOP_BROWSER_ROOT)
    try:
        entries = os.listdir(current_dir)
        dirs = sorted([
            n for n in entries
            if os.path.isdir(os.path.join(current_dir, n))
        ])
        files = sorted([
            n for n in entries
            if os.path.isfile(os.path.join(current_dir, n))
        ])
    except Exception:
        dirs, files = [], []

    buttons: list = []
    if current_dir != root_abs:
        buttons.append(html.Button(
            "[DIR] ..",
            id={"type": "sop-nav-btn", "index": "__PARENT__"},
            className=(
                "btn btn-sm btn-outline-secondary"
                " d-block w-100 text-start mb-1"
            ),
            style={"fontFamily": "monospace"},
            n_clicks=0,
        ))
    for name in dirs:
        full_path = os.path.join(current_dir, name)
        buttons.append(html.Button(
            f"[DIR] {name}",
            id={"type": "sop-nav-btn", "index": full_path},
            className=(
                "btn btn-sm btn-outline-primary"
                " d-block w-100 text-start mb-1"
            ),
            style={"fontFamily": "monospace"},
            n_clicks=0,
        ))
    for name in files:
        full_path = os.path.join(current_dir, name)
        buttons.append(html.Button(
            f"[FILE] {name}",
            id={"type": "sop-file-btn", "index": full_path},
            className=(
                "btn btn-sm btn-outline-success"
                " d-block w-100 text-start mb-1"
            ),
            style={"fontFamily": "monospace"},
            n_clicks=0,
        ))
    return buttons


def create_sop_section() -> html.Div:
    """Create the SOP tab section for mess_inputs selection and LOAD."""
    initial_buttons = _build_sop_browser_buttons(_SOP_BROWSER_ROOT)
    initial_dir = os.path.abspath(_SOP_BROWSER_ROOT)
    return html.Div([
            html.H5(
                "MESS Input Files",
                className="fw-bold"
            ),
            html.Small(
                "Select MESS input files with parameters",
                className="text-muted"
            ),
            html.Div(
                id="sop-mess-files-list",
                style={
                    "marginTop": "15px",
                    "padding": "10px",
                    "backgroundColor": "#f8f9fa",
                    "borderRadius": "5px",
                    "minHeight": "50px"
                }
            ),
            html.Div([
                html.H6("Browse Local Cluster Files", className="mt-1"),
                html.Small(
                    "Pick MESS files from launch directory tree",
                    className="text-muted"
                ),
                html.Div(
                    id="sop-browser-path",
                    className="mt-2",
                    children=html.Code(
                        f"Current directory: {initial_dir}"
                    ),
                ),
                html.Div([
                    html.Button(
                        "Add Selected File",
                        id="sop-browser-add-file",
                        className="btn btn-primary btn-sm",
                        style={"marginRight": "8px"}
                    ),
                    html.Button(
                        "Refresh",
                        id="sop-browser-refresh",
                        className="btn btn-outline-secondary btn-sm"
                    ),
                ], className="mt-2"),
                html.Div(
                    id="sop-browser-entries-container",
                    children=initial_buttons,
                    style={
                        "maxHeight": "200px",
                        "overflowY": "auto",
                        "border": "1px solid #dee2e6",
                        "borderRadius": "4px",
                        "padding": "4px",
                        "marginTop": "8px",
                    },
                ),
                dcc.Store(id="sop-browser-cwd", data=initial_dir),
                dcc.Store(
                    id="sop-browser-selected-file", data=None
                ),
                html.Button(
                    "Load & Validate SOP",
                    id="sop-load-button",
                    className="btn btn-success btn-sm w-100",
                    style={
                        "marginTop": "12px",
                        "width": "100%",
                    }
                ),
            ]),
            html.Div(
                id="sop-validation-message",
                style={
                    "marginTop": "15px",
                    "padding": "10px",
                    "borderRadius": "5px",
                    "display": "none"
                }
            ),
            dcc.Store(id="sop-mess-files-store", data=[]),
        ], className="card p-3 mt-3")


@callback(
    Output("sop-browser-entries-container", "children"),
    Output("sop-browser-path", "children"),
    Input("sop-browser-cwd", "data"),
    Input("sop-browser-refresh", "n_clicks"),
)
def render_sop_browser_entries(cwd, _refresh):
    """Render dir/file buttons for current SOP browser directory."""
    current_dir = os.path.abspath(cwd or _SOP_BROWSER_ROOT)
    path_label = html.Code(f"Current directory: {current_dir}")
    return _build_sop_browser_buttons(current_dir), path_label


@callback(
    Output("sop-browser-cwd", "data"),
    Input({"type": "sop-nav-btn", "index": ALL}, "n_clicks"),
    State("sop-browser-cwd", "data"),
    prevent_initial_call=True,
)
def navigate_on_sop_dir_click(n_clicks_list, cwd):
    """Navigate into a subdirectory when its button is clicked."""
    if not any(v for v in n_clicks_list if v):
        return dash.no_update
    triggered_id = callback_context.triggered_id
    if not isinstance(triggered_id, dict):
        return dash.no_update
    current_dir = os.path.abspath(cwd or _SOP_BROWSER_ROOT)
    root_abs = os.path.abspath(_SOP_BROWSER_ROOT)
    path = triggered_id["index"]
    if path == "__PARENT__":
        target = os.path.abspath(os.path.dirname(current_dir))
    else:
        target = os.path.abspath(path)
    if os.path.commonpath([root_abs, target]) == root_abs:
        return target
    return dash.no_update


@callback(
    Output("sop-browser-selected-file", "data"),
    Input({"type": "sop-file-btn", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_sop_file_on_click(n_clicks_list):
    """Store the path of the file whose button was clicked."""
    if not any(v for v in n_clicks_list if v):
        return dash.no_update
    triggered_id = callback_context.triggered_id
    if not isinstance(triggered_id, dict):
        return dash.no_update
    return triggered_id["index"]


@callback(
    Output("sop-mess-files-store", "data"),
    Input("sop-browser-add-file", "n_clicks"),
    Input({"type": "sop-remove-file", "index": dash.ALL}, "n_clicks"),
    State("sop-browser-selected-file", "data"),
    State("sop-mess-files-store", "data"),
    prevent_initial_call=True,
)
def update_mess_files_list(
    _add_clicks,
    _remove_clicks,
    selected_entry: str,
    current_files: list,
) -> list:
    """Update the mess_inputs list on add/remove actions."""
    if current_files is None:
        current_files = []

    triggered_id = callback_context.triggered_id
    if triggered_id == "sop-browser-add-file":
        if not selected_entry or not os.path.isfile(selected_entry):
            return current_files
        try:
            rel_path = os.path.relpath(selected_entry, os.getcwd())
        except ValueError:
            rel_path = selected_entry
        current_files.append(rel_path)
        return list(dict.fromkeys(current_files))

    if isinstance(triggered_id, dict) and (
        triggered_id.get("type") == "sop-remove-file"
    ):
        filename_to_remove = triggered_id.get("index")
        if not filename_to_remove:
            return current_files
        return [f for f in current_files if f != filename_to_remove]

    return current_files


@callback(
    Output("sop-mess-files-list", "children"),
    Input("sop-mess-files-store", "data")
)
def render_mess_files_list(current_files: list) -> html.Div:
    """Render the selected MESS files list from store state."""
    if current_files is None:
        current_files = []

    file_items = []
    for filename in current_files:
        file_items.append(
            html.Div([
                html.Small(
                    f"📄 {filename}",
                    className="text-muted",
                    style={"display": "inline-block", "width": "90%"}
                ),
                html.Button(
                    "✕",
                    id={"type": "sop-remove-file", "index": filename},
                    className="btn btn-danger btn-sm",
                    style={"float": "right"}
                )
            ], style={"marginBottom": "5px"})
        )

    if not file_items:
        file_items = [
            html.Small(
                "No files selected",
                className="text-muted"
            )
        ]

    return html.Div(file_items)


@callback(
    [
        Output("sop-validation-message", "children"),
        Output("sop-validation-message", "style"),
        Output("sop-valid-store", "data")
    ],
    Input("sop-load-button", "n_clicks"),
    [
        State("mechanism-ct-yaml-input", "value"),
        State("sop-mess-files-store", "data")
    ],
    prevent_initial_call=True
)
def validate_sop(
    n_clicks,
    ct_yaml_path: str,
    mess_files: list
) -> Tuple[str, dict, bool]:
    """Validate SOP by attempting to load mechanism and MESS files."""
    if n_clicks is None or not ct_yaml_path or not mess_files:
        error_msg = html.Div([
            html.Div(
                "❌ Error: Provide ct_yaml and MESS files",
                style={"color": "red", "fontWeight": "bold"}
            )
        ])
        return (
            error_msg,
            {
                "marginTop": "15px",
                "padding": "10px",
                "backgroundColor": "#f8d7da",
                "borderRadius": "5px",
                "display": "block"
            },
            False
        )

    # Import here to keep initialization local and avoid heavy startup cost.
    try:
        from kimeco.default_settings import default_settings
        from kimeco.readers.mess_input import MessInputReader

        # Try to build SOP (validates mechanism + MESS compatibility)
        temp_input = {
            "mess_inputs": mess_files,
            "ct_yaml": ct_yaml_path,
            "experiments": [
                {
                    "temp": 1000,
                    "pres": 1,
                    "cantera_tpl": "dummy.py",
                    "scoring_func": {"type": "dummy"},
                    "data_file": "dummy.csv",
                    "error_file": "dummy.csv",
                    "initial_ratio": {}
                }
            ]
        }

        # Merge with defaults
        full_input = {**default_settings}
        full_input.update(temp_input)

        mech = get_loaded_kinmec(ct_yaml_path)
        if mech is None:
            raise ValueError(
                "Mechanism is not loaded. Re-validate ct_yaml in tab 1 first."
            )

        full_input["postprocess"] = False
        full_input["init_loc"] = os.getcwd()
        gui_logger = logging.getLogger("kmo_start")

        # Try to read MESS inputs
        mr = MessInputReader(
            settings=full_input,
            mechanism_species=mech.species,
            klog=gui_logger,
            postprocess=False
        )

        try:
            sop, _ = mr.read()
            if mr._trigger_stop:
                raise ValueError(
                    "MESS/SOP parsing flagged consistency errors. "
                    "Check mechanism and MESS compatibility."
                )
            # Success!
            success_msg = html.Div([
                html.Div(
                    "✓ SOP validated!",
                    style={"color": "green", "fontWeight": "bold"}
                ),
                html.Small(
                    f"{len(sop.wells)} wells, "
                    f"{len(sop.bimolecular)} bimolecular",
                    style={"color": "#333", "marginTop": "5px"}
                )
            ])
            return (
                success_msg,
                {
                    "marginTop": "15px",
                    "padding": "10px",
                    "backgroundColor": "#d4edda",
                    "borderRadius": "5px",
                    "display": "block"
                },
                True
            )
        except Exception as e:
            error_msg = html.Div([
                html.Div(
                    f"❌ Error loading SOP: {str(e)}",
                    style={"color": "red", "fontWeight": "bold"}
                )
            ])
            return (
                error_msg,
                {
                    "marginTop": "15px",
                    "padding": "10px",
                    "backgroundColor": "#f8d7da",
                    "borderRadius": "5px",
                    "display": "block"
                },
                False
            )

    except Exception as e:
        error_msg = html.Div([
            html.Div(
                f"❌ Validation error: {str(e)}",
                style={"color": "red", "fontWeight": "bold"}
            )
        ])
        return (
            error_msg,
            {
                "marginTop": "15px",
                "padding": "10px",
                "backgroundColor": "#f8d7da",
                "borderRadius": "5px",
                "display": "block"
            },
            False
        )
