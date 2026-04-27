"""Shared file browser dropdown component and helpers for input sections."""

import os

from dash import dcc, html


class FileBrowserDropdown:
    """Build reusable browser controls and navigation helpers."""

    parent_value = "__PARENT__"

    def __init__(self, root_dir: str | None = None):
        self.root_dir = os.path.abspath(root_dir or os.getcwd())

    def initial_dir(self) -> str:
        """Return the browser starting directory."""
        return os.path.abspath(self.root_dir)

    def build_options(self, cwd: str | None) -> list[dict[str, str]]:
        """Build dropdown options for the given directory."""
        current_dir = os.path.abspath(cwd or self.root_dir)
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

        options: list[dict[str, str]] = [
            {"label": "[DIR] ..", "value": self.parent_value}
        ]
        for name in dirs:
            full_path = os.path.join(current_dir, name)
            options.append({"label": f"[DIR] {name}", "value": full_path})
        for name in files:
            full_path = os.path.join(current_dir, name)
            options.append({"label": f"[FILE] {name}", "value": full_path})
        return options

    def resolve_selection(
        self,
        selected_value: str | None,
        cwd: str | None,
    ) -> tuple[str, str | None]:
        """Resolve selected dropdown value to updated cwd and selected file."""
        current_dir = os.path.abspath(cwd or self.root_dir)

        if selected_value == self.parent_value:
            return os.path.abspath(os.path.dirname(current_dir)), None

        if not selected_value:
            return current_dir, None

        target = os.path.abspath(selected_value)
        if os.path.isdir(target):
            return target, None
        if os.path.isfile(target):
            return current_dir, target

        return current_dir, None

    def path_label(self, cwd: str | None) -> html.Code:
        """Render current directory label for the browser."""
        current_dir = os.path.abspath(cwd or self.root_dir)
        return html.Code(f"Current directory: {current_dir}")

    def to_workspace_relative(self, path: str) -> str:
        """Convert an absolute path to path relative to launch directory."""
        try:
            return os.path.relpath(path, os.getcwd())
        except ValueError:
            return path

    def render_controls(
        self,
        *,
        dropdown_id,
        refresh_id,
        path_id,
        cwd_store_id,
        selected_store_id=None,
        placeholder: str = "Select '..', a directory, or a file",
    ) -> html.Div:
        """Render reusable browser controls and associated stores."""
        initial_dir = self.initial_dir()
        children: list = [
            html.Div(
                id=path_id,
                className="mt-2",
                children=self.path_label(initial_dir),
            ),
            html.Div([
                html.Button(
                    "Refresh",
                    id=refresh_id,
                    className="btn btn-outline-secondary btn-sm",
                ),
            ], className="mt-2"),
            dcc.Dropdown(
                id=dropdown_id,
                options=self.build_options(initial_dir),
                placeholder=placeholder,
                clearable=False,
                value=None,
                style={"marginTop": "8px", "fontFamily": "monospace"},
            ),
            dcc.Store(id=cwd_store_id, data=initial_dir),
        ]

        if selected_store_id is not None:
            children.append(dcc.Store(id=selected_store_id, data=None))

        return html.Div(children)
