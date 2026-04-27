"""Mechanism section for ct_yaml file selection and KiMec validation."""

from typing import Any, Optional
import os
from dash import (
    dcc,
    html,
    Input,
    Output,
    State,
    callback,
    no_update,
)

from kimeco.default_settings import default_settings
from kimeco.kinmec import KiMec
from kimeco.gui.input_sections.file_browser import FileBrowserDropdown


_KINMEC_CACHE: dict[str, KiMec] = {}
_BROWSER = FileBrowserDropdown(root_dir=os.getcwd())


def get_loaded_kinmec(ct_yaml_path: str) -> Optional[KiMec]:
    """Return a previously validated KiMec for the provided mechanism path."""
    if not ct_yaml_path:
        return None
    return _KINMEC_CACHE.get(ct_yaml_path.strip())


def create_mechanism_section() -> html.Div:
    """Create the mechanism tab section for ct_yaml file selection."""
    return html.Div([
            html.H5("Mechanism File (ct_yaml)", className="fw-bold"),
            html.Small(
                "Select the Cantera YAML mechanism file",
                className="text-muted"
            ),
            html.Div([
                dcc.Input(
                    id="mechanism-ct-yaml-input",
                    type="text",
                    placeholder="Path to ct_yaml file",
                    className="form-control",
                    style={
                        "marginTop": "10px",
                        "display": "inline-block",
                        "width": "100%",
                    }
                ),
            ], style={"marginTop": "10px"}),
            html.Div([
                html.H6("Browse Local Cluster Files", className="mt-3"),
                html.Small(
                    "Starts from the directory where kmo_start was launched",
                    className="text-muted"
                ),
                _BROWSER.render_controls(
                    dropdown_id="mechanism-browser-dropdown",
                    refresh_id="mechanism-browser-refresh",
                    path_id="mechanism-browser-path",
                    cwd_store_id="mechanism-browser-cwd",
                    selected_store_id=None,
                ),
            ], className="mt-2 p-2 border rounded"),
            html.Div(
                id="mechanism-error-message",
                style={
                    "marginTop": "10px",
                    "color": "red",
                    "display": "none"
                }
            ),
            html.Div(
                id="mechanism-success-message",
                style={
                    "marginTop": "10px",
                    "color": "green",
                    "display": "none"
                }
            ),
            dcc.Store(id="mechanism-info-store", data={}),
        ], className="card p-3 mt-3")


@callback(
    [
        Output("mechanism-error-message", "children"),
        Output("mechanism-error-message", "style"),
        Output("mechanism-success-message", "children"),
        Output("mechanism-success-message", "style"),
        Output("mechanism-info-store", "data"),
        Output("mechanism-valid-store", "data")
    ],
    Input("mechanism-ct-yaml-input", "value"),
    prevent_initial_call=True
)
def validate_mechanism(
    ct_yaml_path: str
) -> tuple[
    str,
    dict[str, Any],
    Any,
    dict[str, Any],
    dict[str, Any],
    bool,
]:
    """Instantiate KiMec, cache it, and expose mechanism summary metrics."""
    hidden_error = {
        "marginTop": "10px",
        "color": "red",
        "display": "none"
    }
    hidden_success = {
        "marginTop": "10px",
        "color": "green",
        "display": "none"
    }

    if not ct_yaml_path or not ct_yaml_path.strip():
        return (
            "",
            hidden_error,
            "",
            hidden_success,
            {},
            False,
        )

    try:
        normalized_path = ct_yaml_path.strip()
        settings = {**default_settings}
        settings["postprocess"] = False
        # KiMec only needs mechanism and settings for mechanism parsing.
        mech = KiMec(file=normalized_path, settings=settings)
        _KINMEC_CACHE[normalized_path] = mech

        n_species = len(mech.species)
        n_reactions = len(mech.reactions)
        n_phases = getattr(mech.mech, "n_phases", 1)

        success = html.Div([
            html.Div(
                "✓ Mechanism loaded successfully",
                style={"fontWeight": "bold"}
            ),
            html.Small(
                f"Species: {n_species} | Reactions: {n_reactions} | "
                f"Phases: {n_phases}"
            )
        ])
        success_style = {
            "marginTop": "10px",
            "padding": "10px",
            "backgroundColor": "#d4edda",
            "borderRadius": "5px",
            "display": "block",
        }
        info = {
            "ct_yaml": normalized_path,
            "species_count": n_species,
            "reaction_count": n_reactions,
            "phase_count": n_phases,
        }
        return ("", hidden_error, success, success_style, info, True)
    except Exception as exc:
        error_style = {
            "marginTop": "10px",
            "padding": "10px",
            "backgroundColor": "#f8d7da",
            "borderRadius": "5px",
            "display": "block",
        }
        # Remove stale cache entry for an invalid mechanism path.
        _KINMEC_CACHE.pop(ct_yaml_path.strip(), None)
        return (
            f"❌ Mechanism validation error: {exc}",
            error_style,
            "",
            hidden_success,
            {},
            False,
        )


@callback(
    Output("mechanism-browser-cwd", "data"),
    Output("mechanism-ct-yaml-input", "value"),
    Output("mechanism-browser-dropdown", "options"),
    Output("mechanism-browser-path", "children"),
    Output("mechanism-browser-dropdown", "value"),
    Input("mechanism-browser-dropdown", "value"),
    Input("mechanism-browser-refresh", "n_clicks"),
    State("mechanism-browser-cwd", "data"),
)
def update_browser_state(selected_value, _refresh, cwd):
    """Own dropdown navigation, refresh, and file selection state."""
    current_dir, selected_file = _BROWSER.resolve_selection(
        selected_value,
        cwd,
    )
    options = _BROWSER.build_options(current_dir)
    path_label = _BROWSER.path_label(current_dir)
    if selected_file is not None:
        return (
            no_update,
            selected_file,
            options,
            path_label,
            None,
        )

    return (
        current_dir,
        no_update,
        options,
        path_label,
        None,
    )
