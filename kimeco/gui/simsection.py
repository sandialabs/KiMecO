from dash import html, dcc, callback, Output, Input, State
import plotly.graph_objects as go
from kimeco.gui.section import Section
from dash.exceptions import PreventUpdate
import cantera.with_units as ctu
from numpy.typing import NDArray
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity


class SIMSection(Section):
    def __init__(self, gapp) -> None:
        super().__init__(gapp)
        self.species: list[str] = self.sim_db.sv_species

    @property
    def layout(self) -> html.Div:
        return html.Div(
            id='sim',
            style={'display': 'none'},
            children=[
                html.H4('Species to visualize'),
                dcc.Dropdown(options=[
                    sp for sp in self.species],
                    multi=True,
                    id='selected species'),
                html.H4(f'Pressure ({self.settings["pres_unit"]}):'),
                dcc.Dropdown(options=[
                    p for p in self.settings['rc_pres']],
                    multi=True,
                    id='sim_P'),
                html.H4('Temperature (K):'),
                dcc.Dropdown(options=[
                    t for t in self.settings['rc_temp']],
                    multi=True,
                    id='sim_T'),
                # Plot BUTTON
                html.Div(
                    id='show_sim_plot_button',
                    style={'display': 'none'},
                    children=[
                        html.Button(id='sim_plot_button',
                                    children='Plot',
                                    )]),
                html.Div(
                    className='row',
                    id='sim_plot')])

    def register_callbacks(self):
        @callback(
            Output('show_sim_plot_button', 'style'),
            Input('selected species', 'value'),
            Input('sim_P', 'value'),
            Input('sim_T', 'value'),
        )
        def show_sim_plot_button(specs: list[str],
                                 pres: float,
                                 temp: float):
            if specs is None or pres is None or temp is None:
                raise PreventUpdate
            else:
                return {'display': 'block'}

        @callback(
            Output('sim_plot', 'style'),
            Output('sim_plot', 'children'),
            Input('show_sim_plot_button', 'n_clicks'),
            State('selected species', 'value'),
            State('sim_P', 'value'),
            State('sim_T', 'value'),
            State('gen range slider', 'value'),
            prevent_initial_call=True,
            running=[
                (Output("sim_plot_button", "disabled"), True, False),
                (Output("sim_plot_button", "children"), 'Updating', 'Plot')]
        )
        def update_sim_figure(clic,
                              specs: list[str],
                              pres: float,
                              temp: float,
                              selected_gen: list[int]
                              ):
            if clic is None:
                raise PreventUpdate

            sim_plot_children = []
            for p in pres:
                p_idx = self.settings['rc_pres'].index(p)
                for t in temp:
                    t_idx = self.settings['rc_temp'].index(t)
                    all_gen_sims: list[dict[dict[NDArray]]] = []
                    for gen_i in selected_gen:
                        for origin in self.gapp.goats[gen_i].split():
                            gen_id = int(origin.split('_')[0])
                            el_id = int(origin.split('_')[1])
                            sim_id = int(
                                el_id *
                                len(self.settings['rc_pres']) *
                                len(self.settings['rc_temp']) +
                                p_idx * len(self.settings['rc_temp']) +
                                t_idx)
                            self.sim_db.prepare_batch_select(
                                table=f'G{gen_id:04d}',
                                sim_id=sim_id
                            )
                        all_gen_sims.append(self.sim_db.batch_select())
                    # Create a figure and associated text for each combination
                    # in the user selection
                    for TPGenSP, gen_i in zip(all_gen_sims, selected_gen):
                        for sp in specs:
                            sim_plot_children.extend(
                                self.make_figure(
                                    gen_name=f"G{gen_i:04d}",
                                    TPGenSP=TPGenSP,
                                    sp=sp,
                                    pres=p,
                                    temp=t))
            return {'display': 'block'}, sim_plot_children

    def make_figure(self,
                    gen_name: str,
                    TPGenSP: dict,
                    sp: str,
                    pres: float,
                    temp: float):
        fig = go.Figure()
        # has_legend: dict[str, bool] = {}
        nel = 0
        sp_idx: int = self.sim_db.columns.index(sp) - 2
        traces: list[go.Scatter] = []
        # for idx, (origin, sim_dict) in enumerate(TPGenSP.items()):
        for origin, sim_dict in TPGenSP.items():
            # if origin not in has_legend:
            #     has_legend[origin] = False
            name: str = f'Origin: {origin}'
            for arr in sim_dict.values():
                nel += 1
                traces.append(go.Scatter(
                    x=arr[:, 1],
                    y=arr[:, sp_idx].T,
                    mode='lines',
                    name=name,
                    showlegend=False,
                    opacity=0.25,
                    line=dict(color='#1E90FF')
                    ))
        # Add all traces to the figure at once
        fig.add_traces(traces)

        # Add experimental profiles
        tidx: int = self.settings['rc_temp'].index(temp)
        pidx: int = self.settings['rc_pres'].index(pres)
        eidx: int = pidx * len(self.settings['rc_temp']) + tidx
        exp_p = self.settings['exp_profiles'][eidx]
        fig.add_trace(go.Scatter(
                        x=exp_p[0],
                        y=exp_p[sp_idx-1],
                        error_y={
                            'array': self.settings['exp_errors'][eidx][sp_idx-1]
                            },
                        mode='lines',
                        name='Exp. profile',
                        line=dict(color='black')
                        ))
        # Overlay both histograms
        fig.update_layout(xaxis=dict(
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
                                color='rgb(0, 0, 0)')
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
                                color='rgb(0, 0, 0)'),
                        ),
                        plot_bgcolor='white',
                        hovermode='closest'
                        )
        figure_block = [
            html.H3(children=[
                f'Concentration profiles of {sp}',
                f' in generations {gen_name}']),
            html.H4(f'T (K): {temp}'),
            html.H4(f"P ({self.settings['pres_unit']}): {pres}"),
            html.H5(f'Number of elements: {nel}'),
            dcc.Graph(figure=fig)
            ]
        return figure_block
