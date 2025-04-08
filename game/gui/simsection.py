from dash import html, dcc, callback, Output, Input, State
import plotly.graph_objects as go
from game.gui.section import Section
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
            className='row', id='sim',
            style={'display': 'none'},
            children=[
                html.H4('Species to visualize'),
                dcc.Dropdown(options=[
                    sp for sp in self.species],
                    multi=True,
                    id='selected species'),
                html.H4('Pressure (Torr):'),
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
            #    any([sp is None for sp in specs]) or\
            #    any([p is None for p in pres]) or\
            #    any([t is None for t in temp]):
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

            all_gen_sims: list[dict[NDArray]] = []
            for gen_i in selected_gen:
                for origin in self.gapp.goats[gen_i].split():
                    gen_id = int(origin.split('_')[0])
                    el_id = int(origin.split('_')[1])
                    sim_id = int(el_id *
                                 len(self.settings['rc_pres']) *
                                 len(self.settings['rc_temp']))
                    self.sim_db.prepare_batch_select(
                        table=f'G{gen_id:04d}',
                        sim_id=sim_id
                    )
                all_gen_sims.append(self.sim_db.batch_select())
            # Create a figure and associated text for each combination
            # in the user selection
            sop_plot_children = []
            for p in pres:
                for t in temp:
                    for TPGenSP, gen_i in zip(all_gen_sims, selected_gen):
                        for sp_idx, sp in enumerate(specs):
                            sop_plot_children.extend(
                                self.make_figure(
                                    gen_name=f"G{gen_i:04d}",
                                    TPGenSP=TPGenSP,
                                    sp=sp,
                                    sp_idx=sp_idx,
                                    pres=p,
                                    temp=t))
            return {'display': 'block'}, sop_plot_children

    def make_figure(self,
                    gen_name: str,
                    TPGenSP: dict,
                    sp: str,
                    sp_idx: int,
                    pres: float,
                    temp: float):
        fig = go.Figure()
        has_legend: dict[str, bool] = {}
        for idx, (origin, arr) in enumerate(TPGenSP.items()):
            if origin not in has_legend:
                has_legend[origin] = False
            name = f'Origin: {origin}'
            specs_arr = arr[:, :, 2:]
            nel = specs_arr.shape[0]
            for elem in range(len(specs_arr)):
                if not has_legend[origin]:
                    fig.add_trace(go.Scatter(
                        x=arr[elem, :, 1],
                        y=specs_arr[elem, :, sp_idx].T,
                        mode='lines',
                        name=name,
                        opacity=0.25,
                        hoverinfo='name'
                        ))
                    has_legend[origin] = True
                else:
                    fig.add_trace(go.Scatter(
                        x=arr[elem, :, 1],
                        y=specs_arr[elem, :, sp_idx].T,
                        mode='lines',
                        name=name,
                        showlegend=False,
                        opacity=0.25,
                        hoverinfo='name'
                        ))
            fig.update_traces(
                marker=dict(
                    color=fig.layout['template']['layout']['colorway'][0]),
                selector=dict(name=name))

        # Add experimental profiles
        tidx: int = self.settings['rc_temp'].index(temp)
        pidx: int = self.settings['rc_pres'].index(pres)
        eidx: int = pidx * len(self.settings['rc_temp']) + tidx
        exp_p = self.settings['exp_profiles'][eidx]
        fig.add_trace(go.Scatter(
                        x=exp_p[0],
                        y=exp_p[sp_idx+1],
                        mode='lines',
                        name='Exp. profile',
                        line=dict(color='black'),
                        hoverinfo='name'
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
                        plot_bgcolor='white'
                        )
        figure_block = [
            html.H3(children=[
                f'Concentration profiles of {sp}',
                f' in generations {gen_name}']),
            html.H5(f'T (K): {temp}'),
            html.H5(f'P (Torr): {pres}'),
            html.H5(f'Number of elements: {nel}'),
            dcc.Graph(figure=fig)
            ]
        return figure_block
