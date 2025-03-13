from dash import html, dcc, callback, Output, Input, State
import plotly.graph_objects as go
import numpy as np
from game.gui.section import Section
import cantera.with_units as ctu
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity


class SIMSection(Section):

    @property
    def _layout(self) -> html.Div:
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
                    id='sim_P'),
                html.H4('Temperature (K):'),
                dcc.Dropdown(options=[
                    t for t in self.settings['rc_temp']],
                    id='sim_T'),
                # Plot BUTTON
                html.Div(
                    id='show_sim_plot_button',
                    style={'display': 'none'},
                    children=[
                        html.Button(id='sim_plot_button',
                                    n_clicks=0,
                                    children='Plot',
                                    )]),
                html.Div(
                    className='row',
                    id='sim_plot',
                    style={'display': 'none'},
                    children={})])

    def register_callbacks(self):
        @callback(
            Output(component_id='show_sim_plot_button', component_property='style'),
            Input(component_id='selected species', component_property='value'),
            State(component_id='gen range slider', component_property='value'),
        )
        def show_sim_plot_button(specs: list[str],
                                 selected_gen: list[int]):
            if specs is not None and\
            all([sp in self.species for sp in specs]) and\
            all([gen_i in range(self.gapp.sim_tot_g) for gen_i in selected_gen]):
                return {'display': 'block'}
            else:
                return {'display': 'none'}
            
        @callback(    
            Output(component_id='sim_plot', component_property='style'),
            Output(component_id='sim_plot', component_property='children'),
            Input(component_id='show_sim_plot_button', component_property='n_clicks'),
            State(component_id='selected species', component_property='value'),
            State(component_id='sim_P', component_property='value'),
            State(component_id='sim_T', component_property='value'),
            State(component_id='gen range slider', component_property='value')
        )
        def update_sim_figure(clic,
                              specs: list[str],
                              pres: float,
                              temp: float,
                              selected_gen: list[int]
                              ):
            nel = []
            fig = go.Figure()
            if (clic is None or
                not all([sp in self.species for sp in specs]) or
                not all([gen_i in range(self.gapp.sim_tot_g) for gen_i in selected_gen])):
                return ({'display': 'none'},
                        [])
            idx = 0

            gen_arr = [
                np.array(self.sim_db.get_TP_sim_profiles(
                    table=f'G{gen_i}',
                    species=specs,
                    pres=np.round(Q_(f"{pres} torr").to("Pa").magnitude, 5),
                    temp=temp))
                for gen_i in selected_gen]
            op: list[float] = [1.0-((i+1)*0.9/len(selected_gen))
                               for i in range(len(selected_gen))]
            for idx, arr in enumerate(gen_arr):
                if idx == 0:
                    # gen_array[generations, elements, columns]
                    # columns : P (Pa), T (K), sim_id, time, species
                    # species are in the same order as requested
                    min_sim_id = arr[:, 2].min()
                    nsteps: int = int(np.sum(arr[:, 2] == min_sim_id))
                nel.append(int(len(arr[:, 2])/nsteps))
                specs_arr = np.reshape(
                    arr,
                    newshape=(
                        nel[-1],
                        nsteps,
                        4+len(specs)))
                specs_arr = specs_arr[:, :, 4:]
                for sp_idx, sp in enumerate(specs):
                    for elem in range(len(specs_arr)):
                        if idx == len(gen_arr)-1 and\
                            elem == len(specs_arr)-1:
                            fig.add_trace(go.Scatter(
                                x=arr[:, 3][:nsteps],
                                y=specs_arr[elem, :, sp_idx].T,
                                mode='lines',
                                name=sp,
                                opacity=op[idx],
                                hoverinfo='name'
                                ))
                        else:
                            fig.add_trace(go.Scatter(
                                x=arr[:, 3][:nsteps],
                                y=specs_arr[elem, :, sp_idx].T,
                                mode='lines',
                                name=sp,
                                showlegend=False,
                                opacity=op[idx],
                                # hoveron='fills',
                                hoverinfo='name'
                                ))
                    if idx == len(gen_arr)-1:
                        fig.update_traces(
                            marker=dict(
                                color=fig.layout['template']['layout']['colorway'][sp_idx]),
                            selector=dict(name=sp))
            # Add experimental profiles
            tidx: int = self.settings['rc_temp'].index(temp)
            pidx: int = self.settings['rc_pres'].index(pres)
            eidx: int = pidx * len(self.settings['rc_temp']) + tidx
            exp_p = self.settings['exp_profiles'][eidx]
            sidx = []
            for sp in specs:
                sidx.append(self.species.index(sp)+1)
            for sp in sidx:
                fig.add_trace(go.Scatter(
                                x=exp_p[0],
                                y=exp_p[sp],
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
                                title='Molar fraction',
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
            # Reduce opacity to see different species
            # fig.update_traces(opacity=0.75)
            return {'display': 'block'}, [
                html.H3(children=[
                    'Concentration profiles for species ',
                    f'{specs} in generations {selected_gen}']),
                html.H5(children=f'Number of elements: {nel}'),
                dcc.Graph(figure=fig)]

