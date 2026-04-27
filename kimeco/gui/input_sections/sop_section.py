"""SOP section for mess_inputs file selection and validation."""
from typing import Any, Tuple
import io
import os
import logging
from dash import (
    dcc,
    html,
    Input,
    Output,
    State,
    callback,
    callback_context,
)
from dash.dependencies import ALL

from kimeco.gui.input_sections.mechanism_section import get_loaded_kinmec
from kimeco.gui.input_sections.file_browser import FileBrowserDropdown


_SOP_BROWSER = FileBrowserDropdown(root_dir=os.getcwd())


def create_sop_section() -> html.Div:
    """Create the SOP tab section for mess_inputs selection and LOAD."""
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
                _SOP_BROWSER.render_controls(
                    dropdown_id="sop-browser-dropdown",
                    refresh_id="sop-browser-refresh",
                    path_id="sop-browser-path",
                    cwd_store_id="sop-browser-cwd",
                    selected_store_id="sop-browser-selected-file",
                ),
                dcc.Checklist(
                    id="sop-force-new-molecules",
                    options=[{
                        "label": "force_new_molecules",
                        "value": "enabled",
                    }],
                    value=[],
                    className="mt-2",
                    inputStyle={"marginRight": "6px"},
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
            html.Div(
                id="sop-validation-log",
                style={
                    "marginTop": "10px",
                    "display": "none"
                }
            ),
            dcc.Store(id="sop-mess-files-store", data=[]),
        ], className="card p-3 mt-3")


@callback(
    Output("sop-browser-cwd", "data"),
    Output("sop-browser-selected-file", "data"),
    Output("sop-browser-dropdown", "options"),
    Output("sop-browser-path", "children"),
    Output("sop-browser-dropdown", "value"),
    Input("sop-browser-dropdown", "value"),
    Input("sop-browser-refresh", "n_clicks"),
    State("sop-browser-cwd", "data"),
)
def update_sop_browser_state(selected_value, _refresh, cwd):
    """Own dropdown navigation, refresh, and file selection state."""
    current_dir, selected_file = _SOP_BROWSER.resolve_selection(
        selected_value,
        cwd,
    )
    options = _SOP_BROWSER.build_options(current_dir)
    path_label = _SOP_BROWSER.path_label(current_dir)
    selected_payload = selected_file if selected_file is not None else None

    return (
        current_dir,
        selected_payload,
        options,
        path_label,
        None,
    )


@callback(
    Output("sop-mess-files-store", "data"),
    Input("sop-browser-selected-file", "data"),
    Input({"type": "sop-remove-file", "index": ALL}, "n_clicks"),
    State("sop-mess-files-store", "data"),
    prevent_initial_call=True,
)
def update_mess_files_list(
    selected_entry: str,
    _remove_clicks,
    current_files: list,
) -> list:
    """Update the mess_inputs list on file selection/remove actions."""
    if current_files is None:
        current_files = []

    triggered_id = callback_context.triggered_id
    if triggered_id == "sop-browser-selected-file":
        if not selected_entry or not os.path.isfile(selected_entry):
            return current_files
        rel_path = _SOP_BROWSER.to_workspace_relative(selected_entry)
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
                    f"{filename}",
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
        Output("sop-valid-store", "data"),
        Output("sop-validation-log", "children"),
        Output("sop-validation-log", "style"),
    ],
    Input("sop-load-button", "n_clicks"),
    [
        State("mechanism-ct-yaml-input", "value"),
        State("sop-mess-files-store", "data"),
        State("sop-force-new-molecules", "value"),
    ],
    prevent_initial_call=True
)
def validate_sop(
    n_clicks,
    ct_yaml_path: str,
    mess_files: list,
    force_new_molecules: list,
) -> Tuple[Any, dict, bool, Any, dict]:
    """Validate SOP by attempting to load mechanism and MESS files."""
    log_style = {
        "marginTop": "10px",
        "padding": "10px",
        "backgroundColor": "#f8f9fa",
        "borderRadius": "5px",
        "display": "block",
    }

    def _log_pre(content: str) -> html.Pre:
        return html.Pre(
            content,
            style={
                "margin": "0",
                "whiteSpace": "pre-wrap",
                "fontFamily": "monospace",
                "maxHeight": "240px",
                "overflowY": "auto",
            }
        )

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
            False,
            _log_pre("Validation did not run: missing ct_yaml or MESS files."),
            log_style,
        )

    # Import here to keep initialization local and avoid heavy startup cost.
    log_stream = io.StringIO()
    gui_logger = logging.getLogger("kmo_start")
    stream_handler = logging.StreamHandler(log_stream)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(
        logging.Formatter("%(levelname)s: %(message)s")
    )
    previous_level = gui_logger.level
    gui_logger.addHandler(stream_handler)
    if gui_logger.level > logging.INFO:
        gui_logger.setLevel(logging.INFO)

    try:
        from kimeco.default_settings import default_settings
        from kimeco.readers.mess_input import MessInputReader

        # Try to build SOP (validates mechanism + MESS compatibility)
        force_new_molecules_bool = bool(
            force_new_molecules and "enabled" in force_new_molecules
        )
        temp_input = {
            "mess_inputs": mess_files,
            "ct_yaml": ct_yaml_path,
            "force_new_molecules": force_new_molecules_bool,
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

        # Try to read MESS inputs
        mr = MessInputReader(
            settings=full_input,
            mechanism_species=[
                sp.name if hasattr(sp, "name") else str(sp)
                for sp in mech.species
            ],
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
            log_content = log_stream.getvalue().strip() or (
                "SOP validation completed without parser log messages."
            )
            return (
                success_msg,
                {
                    "marginTop": "15px",
                    "padding": "10px",
                    "backgroundColor": "#d4edda",
                    "borderRadius": "5px",
                    "display": "block"
                },
                True,
                _log_pre(log_content),
                log_style,
            )
        except Exception as e:
            error_msg = html.Div([
                html.Div(
                    f"❌ Error loading SOP: {str(e)}",
                    style={"color": "red", "fontWeight": "bold"}
                )
            ])
            log_content = log_stream.getvalue().strip() or (
                "No parser log messages were emitted before failure."
            )
            return (
                error_msg,
                {
                    "marginTop": "15px",
                    "padding": "10px",
                    "backgroundColor": "#f8d7da",
                    "borderRadius": "5px",
                    "display": "block"
                },
                False,
                _log_pre(log_content),
                log_style,
            )

    except Exception as e:
        error_msg = html.Div([
            html.Div(
                f"❌ Validation error: {str(e)}",
                style={"color": "red", "fontWeight": "bold"}
            )
        ])
        log_content = log_stream.getvalue().strip() or str(e)
        return (
            error_msg,
            {
                "marginTop": "15px",
                "padding": "10px",
                "backgroundColor": "#f8d7da",
                "borderRadius": "5px",
                "display": "block"
            },
            False,
            _log_pre(log_content),
            log_style,
        )
    finally:
        gui_logger.removeHandler(stream_handler)
        gui_logger.setLevel(previous_level)
