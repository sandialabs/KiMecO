import os
from typing import Any, cast

import pandas as pd
from dash import html, dcc, dash_table, Output, Input, State
from dash.exceptions import PreventUpdate
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from kimeco.gui.section import Section


class DBSection(Section):
    """GUI section to browse the SQLite databases stored in the run folder.

    The user can pick one of the ``.db`` files available in the working
    directory, list its tables, display a selected table as a dataframe and
    copy the whole table to the clipboard (tab separated) so that it can be
    pasted directly into a spreadsheet such as Excel.
    """

    @property
    def workdir(self) -> str:
        return self.settings['workdir']

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------
    def list_databases(self) -> list[str]:
        """Return the sorted list of ``.db`` files in the run folder."""
        try:
            files: list[str] = os.listdir(self.workdir)
        except OSError:
            return []
        return sorted(f for f in files if f.endswith('.db'))

    def _engine(self, db_file: str) -> Engine:
        db_path: str = os.path.join(self.workdir, db_file)
        return create_engine(f'sqlite:///{db_path}')

    def list_tables(self, db_file: str) -> list[str]:
        """Return the user tables contained in ``db_file``."""
        engine: Engine = self._engine(db_file)
        query = text(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name")
        try:
            with engine.connect() as conn:
                rows = conn.execute(query).fetchall()
        finally:
            engine.dispose()
        return [row[0] for row in rows]

    def query_table(self, db_file: str, table: str) -> pd.DataFrame:
        """Return the full content of ``table`` as a dataframe.

        The table name is validated against the tables actually present in
        the database to avoid any SQL injection through the identifier.
        """
        if table not in self.list_tables(db_file):
            return pd.DataFrame()
        engine: Engine = self._engine(db_file)
        try:
            with engine.connect() as conn:
                df: pd.DataFrame = pd.read_sql_query(
                    text(f'SELECT * FROM "{table}"'), conn)
        finally:
            engine.dispose()
        return df

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    @property
    def layout(self) -> html.Div:
        databases: list[str] = self.list_databases()
        return html.Div(
            id='db',
            style={'display': 'block'},
            children=[
                html.H3('Select a database from the run folder:'),
                dcc.Dropdown(
                    id='db_selection',
                    options=cast(Any, [
                        {'label': db, 'value': db} for db in databases]),
                    placeholder='Select a database',
                    style={'maxWidth': '500px'}),
                html.Div(
                    className='row',
                    id='db_tables_row',
                    style={'display': 'none'},
                    children=[
                        html.H3('Select a table:'),
                        dcc.Dropdown(
                            id='db_table_selection',
                            placeholder='Select a table',
                            style={'maxWidth': '500px'})
                    ]),
                html.Div(
                    className='row',
                    id='db_copy_row',
                    style={'display': 'none',
                           'alignItems': 'center',
                           'paddingTop': '10px'},
                    children=[
                        html.Span('Copy table to clipboard '
                                  '(paste into Excel):'),
                        dcc.Clipboard(
                            id='db_clipboard',
                            title='Copy table to clipboard',
                            style={
                                'display': 'inline-block',
                                'fontSize': 22,
                                'verticalAlign': 'middle',
                                'paddingLeft': '10px',
                                'cursor': 'pointer'})
                    ]),
                dcc.Store(id='db_table_tsv'),
                dcc.Loading(
                    html.Div(id='db_table_container',
                             style={'paddingTop': '15px'}))
            ])

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def register_callbacks(self) -> None:
        # Populate the table dropdown when a database is selected.
        @self.app.callback(
            Output('db_tables_row', 'style'),
            Output('db_table_selection', 'options'),
            Output('db_table_selection', 'value'),
            Input('db_selection', 'value'),
        )
        def show_tables(db_file: str | None
                        ) -> tuple[dict[str, str],
                                   list[dict[str, str]],
                                   None]:
            if not db_file:
                return {'display': 'none'}, [], None
            options: list[dict[str, str]] = [
                {'label': t, 'value': t}
                for t in self.list_tables(db_file)]
            return {'display': 'block'}, options, None

        # Display the selected table as a dataframe.
        @self.app.callback(
            Output('db_table_container', 'children'),
            Output('db_copy_row', 'style'),
            Output('db_table_tsv', 'data'),
            Input('db_table_selection', 'value'),
            State('db_selection', 'value'),
        )
        def show_table(table: str | None,
                       db_file: str | None
                       ) -> tuple[Any, dict[str, str], str | None]:
            hidden: dict[str, str] = {'display': 'none'}
            visible: dict[str, str] = {'display': 'flex',
                                       'alignItems': 'center',
                                       'paddingTop': '10px'}
            if not table or not db_file:
                return None, hidden, None
            try:
                df: pd.DataFrame = self.query_table(db_file, table)
            except Exception as exc:  # pragma: no cover - defensive
                return (html.P(f'Could not read table "{table}": {exc}'),
                        hidden, None)
            if df.empty:
                return (html.P('No data in this table.'), hidden, None)

            columns: list[dict[str, str]] = [
                {'name': str(col), 'id': str(col)} for col in df.columns]
            data = df.to_dict('records')
            tsv: str = df.to_csv(sep='\t', index=False)
            table_component = dash_table.DataTable(
                id='db_data_table',
                columns=cast(Any, columns),
                data=cast(Any, data),
                page_size=20,
                page_action='native',
                sort_action='native',
                filter_action='native',
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'center', 'minWidth': '80px'},
                style_header={'backgroundColor': 'lightgrey',
                              'fontWeight': 'bold'},
            )
            return table_component, visible, tsv

        # Copy the current table to the clipboard on demand. Setting the
        # clipboard content from the click triggers the copy to the system
        # clipboard (tab separated, ready to paste into a spreadsheet).
        @self.app.callback(
            Output('db_clipboard', 'content'),
            Input('db_clipboard', 'n_clicks'),
            State('db_table_tsv', 'data'),
            prevent_initial_call=True,
        )
        def copy_table(n_clicks: int | None,
                       tsv: str | None) -> str:
            if not n_clicks or tsv is None:
                raise PreventUpdate
            return tsv
