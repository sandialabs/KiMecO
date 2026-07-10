import os
from typing import Any, cast

import pandas as pd
from dash import html, dcc, dash_table, Output, Input, State
from dash.exceptions import PreventUpdate
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine

from kimeco.database.sim_db import SIM_DB
from kimeco.gui.section import Section
from kimeco.gui.sim_plot import build_profile_figure


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
    # SIM database helpers
    # ------------------------------------------------------------------
    def _sim_dbs(self) -> list[SIM_DB]:
        """Return the live ``SIM_DB`` objects known to the app."""
        return [db for db in (self.sim_db, self.pp_sim_db) if db is not None]

    def _sim_db_for_file(self, db_file: str) -> SIM_DB | None:
        """Return the ``SIM_DB`` object backing ``db_file`` if any.

        Detection relies on the database class rather than the schema: only
        ``SIM_DB`` instances store the feather result blobs.
        """
        for db in self._sim_dbs():
            if f'{db.name}.db' == db_file:
                return db
        return None

    def _is_regular_sim(self, db_file: str) -> bool:
        """True when ``db_file`` is the optimization SIM db (not PP)."""
        return (self.sim_db is not None
                and f'{self.sim_db.name}.db' == db_file)

    def _experiment_label(self, db_file: str, experiment_id: int) -> str:
        """Build the descriptor shown instead of the result blob."""
        experiments = self.settings.get('experiments', [])
        if self._is_regular_sim(db_file) and 0 <= experiment_id < len(
                experiments):
            return f'{experiments[experiment_id].exp_type} ' \
                   f'#{experiment_id}'
        return f'Simulation #{experiment_id}'

    def sim_descriptor_frame(self,
                             db_file: str,
                             sim_db: SIM_DB,
                             table: str) -> pd.DataFrame:
        """Return the blob-free view of a SIM table.

        The heavy ``result`` blob is never loaded; only ``mdl_id`` and
        ``experiment_id`` are queried and a human-readable ``experiment``
        descriptor column is added.
        """
        if table not in sim_db.tables:
            if not sim_db.table_exists(table):
                return pd.DataFrame()
            sim_db.load_table(table)
        query = select(
            sim_db.tables[table].c.mdl_id,
            sim_db.tables[table].c.experiment_id,
        )
        with sim_db.eng.begin() as conn:
            rows = conn.execute(query).fetchall()
        df = pd.DataFrame(
            [(int(r.mdl_id), int(r.experiment_id)) for r in rows],
            columns=['mdl_id', 'experiment_id'])
        df['experiment'] = [
            self._experiment_label(db_file, exp_id)
            for exp_id in df['experiment_id']
        ]
        return df

    def _model_score(self,
                     db_file: str,
                     table: str,
                     mdl_id: int,
                     experiment_id: int) -> float | None:
        """Return the model's score for the given experiment, if available."""
        if not self._is_regular_sim(db_file):
            return None
        experiments = self.settings.get('experiments', [])
        if not (0 <= experiment_id < len(experiments)):
            return None
        col = f'{experiments[experiment_id].name}__score'
        if col not in self.sop_db.columns:
            return None
        try:
            if table not in self.sop_db.tables:
                if not self.sop_db.table_exists(table):
                    return None
                self.sop_db.load_table(table)
            row = self.sop_db.get_sop_row(table=table, id=int(mdl_id))
        except (IndexError, KeyError):
            return None
        col_idx = self.sop_db.columns.index(col) + 1
        if col_idx >= len(row):
            return None
        return float(row[col_idx])

    def export_results(self,
                       db_file: str,
                       table: str,
                       pairs: list[tuple[int, int]] | None) -> tuple[int, str]:
        """Dump one CSV per result into ``{db_name}_{table}`` in the run dir.

        Each CSV is named ``{table}_{mdl_id}_{exp_id}.csv`` and holds the
        decoded feather content (``time`` + species columns). When ``pairs``
        is ``None`` every row of the table is exported.

        Returns the number of files written and the folder path.
        """
        sim_db = self._sim_db_for_file(db_file)
        if sim_db is None:
            raise ValueError(f'{db_file} is not a SIM database.')

        db_name = db_file[:-3] if db_file.endswith('.db') else db_file
        folder = os.path.join(self.workdir, f'{db_name}_{table}')
        os.makedirs(folder, exist_ok=True)

        if pairs is None:
            results = sim_db.get_all_results(table)
        else:
            results = []
            for mdl_id, exp_id in pairs:
                decoded_species = sim_db.get_single_result(
                    table=table, mdl_id=mdl_id, experiment_id=exp_id)
                if decoded_species is None:
                    continue
                decoded, species = decoded_species
                results.append((mdl_id, exp_id, decoded, species))

        count = 0
        for mdl_id, exp_id, decoded, species in results:
            frame = pd.DataFrame(
                decoded[:, 1:], columns=['time'] + list(species))
            fname = f'{table}_{mdl_id}_{exp_id}.csv'
            frame.to_csv(os.path.join(folder, fname), index=False)
            count += 1
        return count, folder

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
                dcc.Store(id='db_sim_row'),
                dcc.Loading(
                    html.Div(id='db_table_container',
                             style={'paddingTop': '15px'})),
                html.Div(
                    id='db_export_row',
                    style={'display': 'none'},
                    children=[
                        html.Button(
                            'Export selection',
                            id='db_export_sel',
                            disabled=True,
                            style={'marginRight': '10px'}),
                        html.Button(
                            'Export all',
                            id='db_export_all'),
                        html.Span(
                            id='db_export_status',
                            style={'paddingLeft': '15px'}),
                    ]),
                html.Div(
                    id='db_sim_plot_area',
                    style={'display': 'none'},
                    children=[
                        html.H3('Selected model vs. experimental data'),
                        html.P('Click a row in the table above to plot its '
                               'simulated profile against the experimental '
                               'data it models.'),
                        html.Div(
                            className='row',
                            style={'display': 'flex',
                                   'alignItems': 'flex-start'},
                            children=[
                                dcc.Loading(
                                    html.Div(
                                        id='db_sim_graph',
                                        style={'flex': '1',
                                               'minWidth': '0'})),
                                html.Div(
                                    style={'width': '200px',
                                           'paddingLeft': '15px'},
                                    children=[
                                        html.H5('Species'),
                                        dcc.Checklist(
                                            id='db_sim_species',
                                            options=[],
                                            value=[],
                                            style={'maxHeight': '400px',
                                                   'overflowY': 'auto'}),
                                    ]),
                            ]),
                        html.Div(
                            id='db_sim_legend',
                            style={'paddingTop': '10px',
                                   'fontWeight': 'bold'}),
                    ]),
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
            Output('db_sim_plot_area', 'style'),
            Output('db_sim_row', 'data'),
            Output('db_sim_species', 'options'),
            Output('db_sim_species', 'value'),
            Output('db_sim_graph', 'children'),
            Output('db_sim_legend', 'children'),
            Output('db_export_row', 'style'),
            Output('db_export_status', 'children'),
            Input('db_table_selection', 'value'),
            State('db_selection', 'value'),
        )
        def show_table(table: str | None,
                       db_file: str | None
                       ) -> tuple[Any, ...]:
            hidden: dict[str, str] = {'display': 'none'}
            visible: dict[str, str] = {'display': 'flex',
                                       'alignItems': 'center',
                                       'paddingTop': '10px'}
            export_visible: dict[str, str] = {'display': 'flex',
                                              'alignItems': 'center',
                                              'paddingTop': '10px'}
            # Reset the per-row plot whenever the table changes.
            reset = (hidden, None, [], [], None, '')
            if not table or not db_file:
                return (None, hidden, None) + reset + (hidden, '')

            sim_db = self._sim_db_for_file(db_file)
            try:
                if sim_db is not None:
                    df = self.sim_descriptor_frame(db_file, sim_db, table)
                else:
                    df = self.query_table(db_file, table)
            except Exception as exc:  # pragma: no cover - defensive
                return ((html.P(f'Could not read table "{table}": {exc}'),
                         hidden, None) + reset + (hidden, ''))
            if df.empty:
                return ((html.P('No data in this table.'), hidden, None)
                        + reset + (hidden, ''))

            columns: list[dict[str, str]] = [
                {'name': str(col), 'id': str(col)} for col in df.columns]
            data = df.to_dict('records')
            tsv: str = df.to_csv(sep='\t', index=False)
            is_sim = sim_db is not None
            table_component = dash_table.DataTable(
                id='db_data_table',
                columns=cast(Any, columns),
                data=cast(Any, data),
                row_selectable=cast(Any, 'multi' if is_sim else False),
                selected_rows=[],
                page_size=20,
                page_action='native',
                sort_action='native',
                filter_action='native',
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'center', 'minWidth': '80px'},
                style_header={'backgroundColor': 'lightgrey',
                              'fontWeight': 'bold'},
            )
            plot_area = {'display': 'block'} if is_sim else hidden
            export_row = export_visible if is_sim else hidden
            return (table_component, visible, tsv,
                    plot_area, None, [], [], None, '',
                    export_row, '')

        # When a SIM table row is clicked, decode its result on demand and
        # prime the species selector for plotting.
        @self.app.callback(
            Output('db_sim_species', 'options', allow_duplicate=True),
            Output('db_sim_species', 'value', allow_duplicate=True),
            Output('db_sim_row', 'data', allow_duplicate=True),
            Input('db_data_table', 'active_cell'),
            State('db_selection', 'value'),
            State('db_table_selection', 'value'),
            State('db_data_table', 'derived_viewport_data'),
            prevent_initial_call=True,
        )
        def on_sim_row_click(active_cell: dict[str, Any] | None,
                             db_file: str | None,
                             table: str | None,
                             viewport: list[dict[str, Any]] | None
                             ) -> tuple[Any, ...]:
            sim_db = (self._sim_db_for_file(db_file)
                      if db_file else None)
            if (active_cell is None or sim_db is None or not table
                    or not viewport):
                raise PreventUpdate
            row_idx = active_cell.get('row')
            if row_idx is None or row_idx >= len(viewport):
                raise PreventUpdate
            row = viewport[row_idx]
            mdl_id = int(row['mdl_id'])
            experiment_id = int(row['experiment_id'])
            result = sim_db.get_single_result(
                table=table, mdl_id=mdl_id, experiment_id=experiment_id)
            if result is None:
                raise PreventUpdate
            _, species = result
            store = {'db_file': db_file, 'table': table,
                     'mdl_id': mdl_id, 'experiment_id': experiment_id}
            return species, species, store

        # Build the profile figure and legend for the selected row.
        @self.app.callback(
            Output('db_sim_graph', 'children', allow_duplicate=True),
            Output('db_sim_legend', 'children', allow_duplicate=True),
            Input('db_sim_row', 'data'),
            Input('db_sim_species', 'value'),
            prevent_initial_call=True,
        )
        def update_sim_plot(store: dict[str, Any] | None,
                            selected_species: list[str] | None
                            ) -> tuple[Any, Any]:
            if not store:
                return None, ''
            sim_db = self._sim_db_for_file(store['db_file'])
            if sim_db is None:
                raise PreventUpdate
            result = sim_db.get_single_result(
                table=store['table'],
                mdl_id=store['mdl_id'],
                experiment_id=store['experiment_id'])
            if result is None:
                return html.P('Result not found.'), ''
            decoded, species = result

            exp = None
            experiments = self.settings.get('experiments', [])
            if (self._is_regular_sim(store['db_file'])
                    and 0 <= store['experiment_id'] < len(experiments)):
                exp = experiments[store['experiment_id']]

            fig = build_profile_figure(
                decoded=decoded,
                species=species,
                selected_species=selected_species or [],
                exp=exp)

            score = self._model_score(
                db_file=store['db_file'],
                table=store['table'],
                mdl_id=store['mdl_id'],
                experiment_id=store['experiment_id'])
            score_txt = (f'{score:.4g}'
                         if isinstance(score, (int, float)) else 'N/A')
            legend = html.Div([
                html.Span(f'Model ID: {store["mdl_id"]}',
                          style={'paddingRight': '25px'}),
                html.Span(f'Score: {score_txt}'),
            ])
            return dcc.Graph(figure=fig), legend

        # Enable the "Export selection" button only when rows are selected.
        @self.app.callback(
            Output('db_export_sel', 'disabled'),
            Input('db_data_table', 'selected_rows'),
        )
        def toggle_export_selection(selected_rows: list[int] | None) -> bool:
            return not selected_rows

        # Export the currently selected rows to CSV files.
        @self.app.callback(
            Output('db_export_status', 'children', allow_duplicate=True),
            Input('db_export_sel', 'n_clicks'),
            State('db_data_table', 'selected_rows'),
            State('db_data_table', 'data'),
            State('db_selection', 'value'),
            State('db_table_selection', 'value'),
            prevent_initial_call=True,
        )
        def export_selection(n_clicks: int | None,
                             selected_rows: list[int] | None,
                             data: list[dict[str, Any]] | None,
                             db_file: str | None,
                             table: str | None) -> str:
            if not n_clicks or not selected_rows or not data \
                    or not db_file or not table:
                raise PreventUpdate
            pairs = [
                (int(data[i]['mdl_id']), int(data[i]['experiment_id']))
                for i in selected_rows if i < len(data)
            ]
            try:
                count, folder = self.export_results(
                    db_file=db_file, table=table, pairs=pairs)
            except Exception as exc:  # pragma: no cover - defensive
                return f'Export failed: {exc}'
            return f'Exported {count} file(s) to {folder}'

        # Export every row of the selected table to CSV files.
        @self.app.callback(
            Output('db_export_status', 'children', allow_duplicate=True),
            Input('db_export_all', 'n_clicks'),
            State('db_selection', 'value'),
            State('db_table_selection', 'value'),
            prevent_initial_call=True,
        )
        def export_all(n_clicks: int | None,
                       db_file: str | None,
                       table: str | None) -> str:
            if not n_clicks or not db_file or not table:
                raise PreventUpdate
            try:
                count, folder = self.export_results(
                    db_file=db_file, table=table, pairs=None)
            except Exception as exc:  # pragma: no cover - defensive
                return f'Export failed: {exc}'
            return f'Exported {count} file(s) to {folder}'

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
