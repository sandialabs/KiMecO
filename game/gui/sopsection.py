from dash import html, dcc, Output, Input, State
from plotly.graph_objs._figure import Figure
import plotly.graph_objects as go
import pandas as pd
from game.gui.section import Section
from game.barrier import Barrier
from game.well import Well
from game.bimolecular import Bimolecular


class SOPSection(Section):

    @property
    def _layout(self) -> html.Div:
        return html.Div(
            className='row', id='sop',
            style={'display': 'none'},
            children=[
                html.H3('Type of parameter to plot:'),
                dcc.RadioItems(options=[
                    {'label': 'Energies', 'value': 'e'},
                    {'label': 'Frequencies', 'value': 'f_p'},
                    {'label': 'Imaginary freq', 'value': 'if'},
                    {'label': 'Rotor perturbation', 'value': 'r'},
                    {'label': 'Sigmas', 'value': 'sigma'},
                    {'label': 'Epsilon', 'value': 'epsi'},
                    {'label': 'Score', 'value': 'score'}],
                                value='Energies',
                                inline=True,
                                id='ptype'),
                html.Div(className='row',
                         id='param_select_row',
                         style={'display': 'none'},
                         children=[
                            # Select which parameter
                            dcc.Dropdown(options={},
                                         id='param_selection')
                            ]),
                # Plot BUTTON
                html.Div(
                    id='sop_plot_button',
                    style={'display': 'none'},
                    children=[
                        html.Button(id='sop_plot_b',
                                    n_clicks=0,
                                    children='Plot',
                                    )]),
                html.Div(
                    className='row',
                    id='sop_plot',
                    style={'display': 'none'},
                    children=[
                        html.H3(children={}, id='sop_dist_title'),
                        html.H5(children={}, id='sop_avrg'),
                        html.H5(children={}, id='sop_elem'),
                        dcc.Graph(figure={}, id='param_dist')
                    ])])

    def register_callbacks(self):
        # SOP interactions
        # Show parameter selection once the type of parameter has been selected
        @self.app.callback(
            Output(component_id='param_select_row', component_property='style'),
            Output(component_id='param_selection', component_property='options'),
            Input(component_id='ptype', component_property='value')
        )
        def update_param_choice(param_type: str
                                ) -> tuple[dict[str, str], list[dict[str, str]]]:
            """Create a list of parameters depending on user selected ptype.

            Args:
                param_type (str): parameter identifier in the sop db.

            Returns:
                tuple[dict[str, str], list[str]]: _description_
            """
            filtered_param: list[dict[str, str]] = []
            for col in self.sop_db.columns[1:]:
                molec: str = col.split('__')[0]
                if molec in self.settings['ct_names']:
                    molec = self.settings['ct_names'][molec]
                param: str = col.split('__')[1]
                if param_type == 'score':
                    filtered_param.append({
                        'label': f"{molec}",
                        'value': col})
                elif param_type == 'e' or param_type == 'if':
                    if param.startswith('epsi'):
                        continue
                    if molec in self.settings['score_sp']:
                        filtered_param.append({
                            'label': f"{molec}",
                            'value': col})
                    else:
                        filtered_param.append({
                            'label': f"{molec} {param}",
                            'value': col})
                else:
                    filtered_param.append({
                        'label': f"{molec} {param}",
                        'value': col})

            if param_type != '':
                style: dict[str, str] = {'display': 'block'}
            else:
                style = {'display': 'none'}
            return style, filtered_param

        # Show sop plot button once generation and parameters have been selected
        @self.app.callback(
            Output(component_id='sop_plot_button', component_property='style'),
            Input(component_id='param_selection', component_property='value')
        )
        def show_sop_plot_button(selected_param: str
                                 ) -> dict[str, str]:
            if selected_param in self.init_SOP.parameters_names:
                return {'display': 'block'}
            else:
                return {'display': 'none'}

        # Plot the distribution of the requested parameter
        @self.app.callback(
            Output(component_id='sop_plot', component_property='style'),
            Output(component_id='param_dist', component_property='figure'),
            Output(component_id='sop_dist_title', component_property='children'),
            Output(component_id='sop_avrg', component_property='children'),
            Output(component_id='sop_elem', component_property='children'),
            Input(component_id='sop_plot_b', component_property='n_clicks'),
            State(component_id='ptype', component_property='value'),
            State(component_id='param_selection', component_property='value'),
            State(component_id='gen range slider', component_property='value')
        )
        def update_sop_figure(clic,
                              ptype: str,
                              param: str,
                              selected_gen: list[int]
                              ) -> tuple[dict[str, str], Figure, str, str, str]:
            if clic == 0:
                return ({'display': 'none'},
                        go.Figure(),
                        '',
                        '',
                        '')
            title: str
            std_allowed: float
            fig = go.Figure()
            for idx, col in enumerate(self.sop_db.columns):
                if col == param:
                    init_val: float = self.gapp.init_vals[idx+1]
                    fig.add_vline(x=init_val,
                                  line_dash='dash',
                                  line_width=2,
                                  line_color='black')
                    break

            tickformat: str = '.2f'
            if 'score' in ptype:
                title = fr'{ptype}'
                tickformat: str = 'e'
            elif '__' in param:
                short_p: str = param.split('__')[1]
                if param.split('__')[0] in self.settings['ct_names']:
                    molec = self.settings['ct_names'][param.split('__')[0]]
                else:
                    molec = param.split('__')[0]
                if ptype == 'e':
                    title = f'Energy of {molec} (kcal/mol)'
                    if not isinstance(
                       self.init_SOP.items[param.split('__')[0]], Barrier):
                        std_allowed = self.settings['std_e'] * self.settings['max_std']
                    else:
                        std_allowed = self.settings['std_b'] * self.settings['max_std']
                elif ptype == 'f':
                        std_allowed = self.settings['std_hf_p'] * self.settings['max_std']
                        title = fr'Frequency {short_p} of {molec} (1/cm)'
                elif ptype == 'r':
                    std_allowed = self.settings['std_hr'] * self.settings['max_std']
                    title = f'Rotor perturbation {short_p} of {molec}'
                elif ptype == 'if':
                    std_allowed = self.settings['std_if'] * self.settings['max_std']
                    bar: Barrier = self.init_SOP.items[molec]
                    if isinstance(bar.connected[0], Well):
                        if bar.connected[0].name in self.settings['ct_names']:
                            From: str = self.settings['ct_names'][bar.connected[0].name]
                        else:
                            From = bar.connected[0].name
                    elif isinstance(bar.connected[0], Bimolecular):
                        From = ''
                        for idx, frag in enumerate(bar.connected[0].frag_names()):
                            if idx == 1:
                                From += ' + '
                            if frag in self.settings['ct_names']:
                                From += self.settings['ct_names'][frag]
                            else:
                                From += frag
                    else:
                        raise NotImplementedError('Unknown reactant object.')
                    if isinstance(bar.connected[0], Well):
                        if bar.connected[1].name in self.settings['ct_names']:
                            To: str = self.settings['ct_names'][bar.connected[1].name]
                        else:
                            To = bar.connected[1].name
                    elif isinstance(bar.connected[1], Bimolecular):
                        To = ''
                        for idx, frag in enumerate(bar.connected[1].frag_names()):
                            if idx == 1:
                                To += ' + '
                            if frag in self.settings['ct_names']:
                                To += self.settings['ct_names'][frag]
                            else:
                                To += frag
                    else:
                        raise NotImplementedError('Unknown reactant object.')
                    title = f'I. frequency from {From} to {To} (1/cm)'
                elif ptype == 'sigma':
                    std_allowed = self.settings['std_sigma'] * self.settings['max_std']
                    title = f"Sigma {short_p.split('_')[-1]}"
                elif ptype == 'epsi':
                    std_allowed = self.settings['std_epsi'] * self.settings['max_std']
                    title = f"Epsilon {short_p.split('_')[-1]}"
                else:
                    raise NotImplementedError('Unknown parameter')
                lb: float = init_val - std_allowed
                ub: float = init_val + std_allowed
                fig.add_vline(x=lb,
                              line_dash='dash',
                              line_width=4,
                              line_color='brown')
                fig.add_vline(x=ub,
                              line_dash='dash',
                              line_width=4,
                              line_color='brown')
            else:
                title = 'Score'
            avrg = []
            nel = []
            cols = ['sop_id']
            cols.extend(self.gapp.sop_db.columns)
            gen_rows = [
                self.gapp.sop_db.get_table(table=f'G{gen_i}')
                for gen_i in selected_gen]
            for idx, gen_rows in enumerate(gen_rows):
                df = pd.DataFrame(data=gen_rows, columns=cols)
                avrg.append(f"{df[param].mean():.3f}")
                nel.append(len(df[param]))
                fig.add_trace(go.Histogram(
                    histfunc="count",
                    x=df[param],
                    nbinsx=30,
                    name=f'Gen {selected_gen[idx]}',
                    bingroup=1))
            # Overlay both histograms
            fig.update_layout(barmode='overlay',
                              xaxis=dict(
                                title=title,
                                showline=True,
                                showgrid=True,
                                showticklabels=True,
                                linecolor='rgb(0, 0, 0)',
                                linewidth=2,
                                ticks='inside',
                                tickformat=tickformat,
                                tickfont=dict(
                                    family='Arial',
                                    size=12,
                                    color='rgb(0, 0, 0)')
                              ),
                              yaxis=dict(
                                title='Count of elements',
                                showline=True,
                                showgrid=True,
                                showticklabels=True,
                                linecolor='rgb(0, 0, 0)',
                                linewidth=2,
                                ticks='inside',
                                # tickformat='.2e',
                                tickfont=dict(
                                    family='Arial',
                                    size=12,
                                    color='rgb(0, 0, 0)')
                              ),
                              plot_bgcolor='white'
                              )
            # Reduce opacity to see both histograms
            fig.update_traces(opacity=0.75)
            return ({'display': 'block'},
                    fig,
                    f'Distribution of {param} in generation {selected_gen}',
                    f"Average: {avrg}",
                    f'Number of elements: {nel}')
