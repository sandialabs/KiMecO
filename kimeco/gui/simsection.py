from typing import Any, cast

from dash import Input, Output, State, callback, dcc, html
from dash.exceptions import PreventUpdate
import numpy as np
from numpy.typing import NDArray
import plotly.graph_objects as go
from kimeco.database.sim_db import SIM_DB
from kimeco.gui.section import Section


class SIMSection(Section):
    def __init__(self, gapp) -> None:
        super().__init__(gapp)
        self.species: list[str] = self.sim_db.sv_species
        self.pp_species: list[str] = []
        self.pp_tables: list[str] = []
        if self.pp_sim_db is not None:
            self.pp_species = self.pp_sim_db.sv_species
            self.pp_tables = sorted(self.pp_sim_db.tables.keys())

    @property
    def layout(self) -> html.Div:
        return html.Div(
            id='sim',
            style={'display': 'block'},
            children=[
                html.H4('Simulation source'),
                dcc.RadioItems(
                    options=cast(Any, (
                        [{'label': 'Optimization', 'value': 'REG'}]
                        + ([{'label': 'Postprocessing', 'value': 'PP'}]
                           if self.pp_sim_db is not None else [])
                    )),
                    value='REG',
                    inline=True,
                    id='sim_source',
                ),
                html.Div(
                    id='pp_sim_tables_container',
                    style={'display': 'none'},
                    children=[
                        html.H4('Postprocessing tables'),
                        dcc.Dropdown(
                            options=self.pp_tables,
                            multi=True,
                            id='pp_sim_tables',
                        ),
                    ],
                ),
                html.H4('Species to visualize'),
                dcc.Dropdown(
                    options=[sp for sp in self.species],
                    multi=True,
                    id='selected species',
                ),
                html.H4(f'Pressure ({self.settings["pres_unit"]}):'),
                dcc.Dropdown(
                    options=[p for p in self.settings['rc_pres']],
                    multi=True,
                    id='sim_P',
                ),
                html.H4('Temperature (K):'),
                dcc.Dropdown(
                    options=[t for t in self.settings['rc_temp']],
                    multi=True,
                    id='sim_T',
                ),
                html.Div(
                    id='show_sim_plot_button',
                    style={'display': 'none'},
                    children=[
                        html.Button(
                            id='sim_plot_button',
                            children='Plot',
                        )
                    ],
                ),
                html.Div(className='row', id='sim_plot'),
            ],
        )

    def register_callbacks(self):
        @callback(
            Output('selected species', 'options'),
            Output('sim_P', 'options'),
            Output('sim_T', 'options'),
            Output('pp_sim_tables_container', 'style'),
            Output('pp_sim_tables', 'options'),
            Input('sim_source', 'value'),
        )
        def update_sim_source(source: str):
            if source == 'PP':
                return (
                    [sp for sp in self.pp_species],
                    [p for p in self.settings.get('pp_pres', [])],
                    [t for t in self.settings.get('pp_temp', [])],
                    {'display': 'block'},
                    self.pp_tables,
                )

            return (
                [sp for sp in self.species],
                [p for p in self.settings['rc_pres']],
                [t for t in self.settings['rc_temp']],
                {'display': 'none'},
                self.pp_tables,
            )

        @callback(
            Output('show_sim_plot_button', 'style'),
            Input('sim_source', 'value'),
            Input('selected species', 'value'),
            Input('sim_P', 'value'),
            Input('sim_T', 'value'),
            Input('pp_sim_tables', 'value'),
        )
        def show_sim_plot_button(source: str,
                                 specs: list[str],
                                 pres: list | float,
                                 temp: list | float,
                                 pp_tables: list[str]):
            if specs is None or pres is None or temp is None:
                raise PreventUpdate
            if source == 'PP' and not pp_tables:
                raise PreventUpdate
            return {'display': 'block'}

        @callback(
            Output('sim_plot', 'style'),
            Output('sim_plot', 'children'),
            Input('show_sim_plot_button', 'n_clicks'),
            State('sim_source', 'value'),
            State('selected species', 'value'),
            State('sim_P', 'value'),
            State('sim_T', 'value'),
            State('pp_sim_tables', 'value'),
            State('gen range slider', 'value'),
            prevent_initial_call=True,
            running=[
                (Output('sim_plot_button', 'disabled'), True, False),
                (Output('sim_plot_button', 'children'), 'Updating', 'Plot'),
            ],
        )
        def update_sim_figure(clic,
                              source: str,
                              specs: list[str],
                              pres: list | float,
                              temp: list | float,
                              pp_tables: list[str],
                              selected_gen: list[int]):
            if clic is None or specs is None or pres is None or temp is None:
                raise PreventUpdate

            if not isinstance(specs, (list, tuple, np.ndarray)):
                specs = [specs]
            if not isinstance(pres, (list, tuple, np.ndarray)):
                pres = [pres]
            if not isinstance(temp, (list, tuple, np.ndarray)):
                temp = [temp]

            sim_plot_children = []
            for p in pres:
                p_idx = self._get_pressure_index(source=source, pressure=p)
                for t in temp:
                    if source == 'PP':
                        t_idx = self.settings.get('pp_temp', []).index(t)
                        all_table_sims = self.get_pp_condition_profiles(
                            tables=pp_tables or [],
                            p_idx=p_idx,
                            t_idx=t_idx,
                        )
                        for table_name in pp_tables or []:
                            table_results: dict[str, dict[int, dict[int, NDArray]]] = {}
                            if table_name in all_table_sims:
                                table_results[table_name] = (
                                    all_table_sims[table_name]
                                )
                            for sp in specs:
                                sim_plot_children.extend(
                                    self.make_figure(
                                        gen_name=table_name,
                                        TPGenSP=table_results,
                                        sp=sp,
                                        pres=p,
                                        temp=t,
                                        sim_db=self.pp_sim_db,
                                        show_exp_profile=False,
                                    )
                                )
                    else:
                        t_idx = self.settings['rc_temp'].index(t)
                        all_gen_sims = self.get_regular_condition_profiles(
                            selected_gen=selected_gen,
                            p_idx=p_idx,
                            t_idx=t_idx,
                        )
                        for table_results, gen_i in zip(
                                all_gen_sims, selected_gen):
                            for sp in specs:
                                sim_plot_children.extend(
                                    self.make_figure(
                                        gen_name=f'G{gen_i:04d}',
                                        TPGenSP=table_results,
                                        sp=sp,
                                        pres=p,
                                        temp=t,
                                        sim_db=self.sim_db,
                                        show_exp_profile=True,
                                    )
                                )

            return {'display': 'block'}, sim_plot_children

    def _get_pressure_index(self,
                            source: str,
                            pressure: float) -> int:
        if source == 'PP':
            return self.settings.get('pp_pres', []).index(pressure)
        return self.settings['rc_pres'].index(pressure)

    def get_regular_condition_profiles(
            self,
            selected_gen: list[int],
            p_idx: int,
            t_idx: int) -> list[dict[str, dict[int, dict[int, NDArray]]]]:
        all_gen_sims: list[dict[str, dict[int, dict[int, NDArray]]]] = []
        models_per_gen: dict[int, list] = {}
        for gen_i in selected_gen:
            gens = self.gapp.goats.generations
            if isinstance(gens, dict):
                tokens = gens.get(gen_i, [])
            else:
                try:
                    tokens = gens[gen_i]
                except Exception:
                    tokens = []
            models_per_gen[gen_i] = tokens
            exp_indices = [
                idx for idx, exp in enumerate(self.settings['experiments'])
                if (
                    exp.P == self.settings['rc_pres'][p_idx]
                    and exp.T == self.settings['rc_temp'][t_idx]
                )
            ]
            for (mdl_gen, mdl_id) in tokens:
                for exp_idx in exp_indices:
                    self.sim_db.prepare_batch_select(
                        table=f'G{mdl_gen:04d}',
                        mdl_id=mdl_id,
                        experiment_id=exp_idx,
                    )

        all_results = self.sim_db.batch_select()
        for gen_i in selected_gen:
            tables = {f'G{tkn[0]:04d}' for tkn in models_per_gen[gen_i]}
            table_results: dict[str, dict[int, dict[int, NDArray]]] = {}
            for tbl in tables:
                if tbl in all_results:
                    table_results[tbl] = all_results[tbl]
            all_gen_sims.append(table_results)
        return all_gen_sims

    def get_pp_condition_profiles(
            self,
            tables: list[str],
            p_idx: int,
            t_idx: int) -> dict[str, dict[int, dict[int, NDArray]]]:
        if self.pp_sim_db is None:
            return {}

        sim_idx = p_idx * len(self.settings['pp_temp']) + t_idx
        for table_name in tables:
            table_rows = self.pp_sim_db.get_table(table=table_name)
            mdl_ids = sorted(
                {
                    int(row[0]) for row in table_rows
                    if int(row[1]) == sim_idx
                }
            )
            for mdl_id in mdl_ids:
                self.pp_sim_db.prepare_batch_select(
                    table=table_name,
                    mdl_id=mdl_id,
                    experiment_id=sim_idx,
                )
        all_results = self.pp_sim_db.batch_select()
        return all_results

    def make_figure(self,
                    gen_name: str,
                    TPGenSP: dict[str, dict[int, dict[int, NDArray]]],
                    sp: str,
                    pres: float,
                    temp: float,
                    sim_db: SIM_DB | None,
                    show_exp_profile: bool):
        if sim_db is None:
            return []

        fig = go.Figure()
        nel = 0
        if sp not in sim_db.sv_species:
            return [fig]
        sp_idx = sim_db.sv_species.index(sp) + 2
        traces: list[go.Scatter] = []
        for origin, model_dict in TPGenSP.items():
            name = f'Origin: {origin}'
            for exp_dict in model_dict.values():
                for arr in exp_dict.values():
                    nel += 1
                    traces.append(
                        go.Scatter(
                            x=arr[:, 1],
                            y=arr[:, sp_idx].T,
                            mode='lines',
                            name=name,
                            showlegend=False,
                            opacity=0.25,
                            line=dict(color='#1E90FF'),
                        )
                    )
        fig.add_traces(traces)

        if show_exp_profile:
            tidx = self.settings['rc_temp'].index(temp)
            pidx = self.settings['rc_pres'].index(pres)
            exp_indices = [
                idx for idx, exp in enumerate(self.settings['experiments'])
                if (
                    exp.P == self.settings['rc_pres'][pidx]
                    and exp.T == self.settings['rc_temp'][tidx]
                )
            ]
            if len(exp_indices) == 0:
                exp_indices = [0]
            eidx = exp_indices[0]
            exp_p = self.settings['experiments'][eidx].data
            exp_species = self.settings['experiments'][eidx].species
            if sp not in exp_species:
                return [fig]
            exp_sp_idx = exp_species.index(sp) + 1
            fig.add_trace(
                go.Scatter(
                    x=exp_p[0],
                    y=exp_p[exp_sp_idx],
                    error_y={
                        'array': self.settings['experiments'][eidx].error[
                            exp_sp_idx
                        ]
                    },
                    mode='lines',
                    name='Exp. profile',
                    line=dict(color='black'),
                )
            )

        fig.update_layout(
            xaxis=dict(
                title='time (s)',
                showline=True,
                showgrid=True,
                showticklabels=True,
                linecolor='rgb(0, 0, 0)',
                linewidth=2,
                ticks='inside',
                tickformat='.2e',
                tickfont=dict(
                    family='Arial',
                    size=12,
                    color='rgb(0, 0, 0)',
                ),
            ),
            yaxis=dict(
                title='Density (molecules/cm</sub>3</sup>)',
                showline=True,
                showgrid=True,
                showticklabels=True,
                linecolor='rgb(0, 0, 0)',
                linewidth=2,
                ticks='inside',
                tickformat='.2e',
                tickfont=dict(
                    family='Arial',
                    size=12,
                    color='rgb(0, 0, 0)',
                ),
            ),
            plot_bgcolor='white',
            hovermode='closest',
        )
        return [
            html.H3(children=[
                f'Concentration profiles of {sp}',
                f' in generations {gen_name}',
            ]),
            html.H4(f'T (K): {temp}'),
            html.H4(f"P ({self.settings['pres_unit']}): {pres}"),
            html.H5(f'Number of models: {nel}'),
            dcc.Graph(figure=fig),
        ]
