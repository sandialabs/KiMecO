from dash import html, dcc, Output, Input, State
from plotly.graph_objs._figure import Figure
import plotly.graph_objects as go
import pandas as pd
from kimeco.gui.section import Section
from kimeco.barrier import Barrier
from kimeco.well import Well
from kimeco.bimolecular import Bimolecular
from dash.exceptions import PreventUpdate
from typing import Any


class SOPSection(Section):

    @property
    def layout(self) -> html.Div:
        return html.Div(
            className='row', id='sop',
            style={'display': 'none'},
            children=[
                html.H3('Type of parameter to plot:'),
                dcc.RadioItems(options=[
                    {'label': 'Energies', 'value': 'e'},
                    {'label': 'Frequencies', 'value': 'f_p'},
                    {'label': 'Imaginary freq', 'value': 'if'},
                    {'label': 'Rotor perturbation', 'value': 'hr'},
                    {'label': 'Lennard-Jones', 'value': 'lj'},
                    {'label': 'Score', 'value': 'score'},
                    {'label': 'ME collision', 'value': 'me'}],
                                value='Energies',
                                inline=True,
                                id='ptype'),
                html.Div(className='row',
                         id='param_select_row',
                         style={'display': 'none'},
                         children=[
                            # Select which parameter
                            dcc.Dropdown(
                                multi=True,
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
                # Plotting area
                html.Div(
                    className='row',
                    id='sop_plot',
                    style={'display': 'none'}
                    )])

    def register_callbacks(self):
        # SOP interactions
        # Show parameter selection once the type of parameter has been selected
        @self.app.callback(
            Output('param_select_row', 'style'),
            Output('param_selection', 'options'),
            Input('ptype', 'value')
        )
        def update_param_choice(ptype: str
                                ) -> tuple[dict[str, str], list[dict[str, str]]]:
            """Create a list of parameters depending on user selected ptype.

            Args:
                ptype (str): parameter identifier in the sop db.

            Returns:
                tuple[dict[str, str], list[str]]: _description_
            """
            filtered_param: list[dict[str, str]] = []
            for col in self.sop_db.columns:
                molec: str = col.split('__')[0]
                if molec in self.settings['ct_names']:
                    molec = self.settings['ct_names'][molec]
                param: str = col.split('__')[1]
                if ptype == 'score':
                    if 'score' not in param:
                        continue
                    filtered_param.append({
                        'label': f"{molec}",
                        'value': col})
                elif ptype == 'e' and param == 'e':
                    filtered_param.append({
                        'label': f"{molec}",
                        'value': col})
                elif ptype == 'if' and param == 'if':
                    filtered_param.append({
                        'label': f"{molec}",
                        'value': col})
                elif ptype == 'hr' and 'hr' in param:
                    filtered_param.append({
                        'label': f"{molec} {param}",
                        'value': col})
                elif ptype == 'f_p' and 'f_p' in param:
                    filtered_param.append({
                        'label': f"{molec} {param}",
                        'value': col})
                elif (ptype == 'lj' and
                      ('epsi' in param or 'sigma' in param)):
                    filtered_param.append({
                        'label': f"{molec} {param}",
                        'value': col})
                elif (ptype == 'me' and
                      (param == 'pow' or param == 'fact')):
                    filtered_param.append({
                        'label': f"{molec} {param}",
                        'value': col})
                else:
                    continue

            if ptype != '':
                style: dict[str, str] = {'display': 'block'}
            else:
                style = {'display': 'none'}
            return style, filtered_param

        # Show sop plot button once generation and parameters have been selected
        @self.app.callback(
            Output('sop_plot_button', 'style'),
            Input('param_selection', 'value')
        )
        def show_sop_plot_button(selected_param: str
                                 ) -> dict[str, str]:
            if selected_param is None:
                raise PreventUpdate
            else:
                return {'display': 'block'}

        # Plot the distribution of the requested parameter
        @self.app.callback(
            Output('sop_plot', 'style'),
            Output('sop_plot', 'children'),
            Input('sop_plot_b', 'n_clicks'),
            State('ptype', 'value'),
            State('param_selection', 'value'),
            State('gen range slider', 'value'),
            prevent_initial_call=True,
            running=[(Output("sop_plot_b", "disabled"), True, False)]
        )
        def update_sop_figure(clic,
                              ptype: str,
                              param_selected: list[str],
                              selected_gen: list[int]
                              ) \
                -> tuple[dict[str, str], Figure, str, str, str]:
            if clic == 0 or clic is None:
                raise PreventUpdate

            sop_plot_children = []
            for col in param_selected:
                std_allowed, plot_settings = self.get_plot_options(
                    col,
                    ptype)
                sop_plot_children.extend(
                    self.make_figure(
                        std_allowed,
                        plot_settings,
                        col,
                        selected_gen
                    )
                )
            return ({'display': 'block'},
                    sop_plot_children
                    )

    def get_plot_options(self,
                         col: str,
                         ptype: str
                         ):
        std_allowed: float = 0.0
        plot_settings: dict[str, Any] = {
            'title': col
        }
        raw_molec: str = col.split('__')[0]
        if raw_molec in self.settings['ct_names']:
            molec = self.settings['ct_names'][raw_molec]
        else:
            molec = raw_molec
        param: str = col.split('__')[1]
        plot_settings['tickformat'] = '.2f'
        if ptype == 'score' and param == 'score':
            plot_settings['title'] = fr'{ptype}'
            plot_settings['tickformat'] = 'e'
        elif ptype == 'e' and param == 'e':
            plot_settings['title'] = f'Energy of {molec} (kcal/mol)'
            if not isinstance(
               self.init_SOP.items[raw_molec], Barrier):
                std_allowed = self.settings['std_e'] *\
                        self.settings['max_std']
            else:
                std_allowed = self.settings['std_b'] *\
                        self.settings['max_std']
        elif ptype == 'if' and param == 'if':
            std_allowed = self.settings['std_if'] *\
                    self.settings['max_std']
            bar: Barrier = self.init_SOP.items[raw_molec]
            if isinstance(bar.connected[0], Well):
                if bar.connected[0].name in self.settings['ct_names']:
                    From: str = \
                        self.settings['ct_names'][bar.connected[0].name]
                else:
                    From = bar.connected[0].name
            elif isinstance(bar.connected[0], Bimolecular):
                From = ''
                for idx, frag in enumerate(bar.connected[0].frag_names):
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
                    To: str = \
                        self.settings['ct_names'][bar.connected[1].name]
                else:
                    To = bar.connected[1].name
            elif isinstance(bar.connected[1], Bimolecular):
                To = ''
                for idx, frag in enumerate(bar.connected[1].frag_names):
                    if idx == 1:
                        To += ' + '
                    if frag in self.settings['ct_names']:
                        To += self.settings['ct_names'][frag]
                    else:
                        To += frag
            else:
                raise NotImplementedError('Unknown reactant object.')
            plot_settings['title'] = f'I. frequency from {From} to {To} (1/cm)'
        elif ptype == 'hr' and 'hr' in param:
            std_allowed = self.settings['std_hr'] *\
                    self.settings['max_std']
            plot_settings['title'] = f'Rotor perturbation {param} of {molec}'
        elif ptype == 'f_p' and 'f_p' in param:
            std_allowed = self.settings['std_hf_p'] *\
                    self.settings['max_std']
            plot_settings['title'] = \
                f'Frequency perturbation {param} of {molec}'
        elif (ptype == 'lj' and
                ('epsi' in param or 'sigma' in param)):
            if 'epsi' in param:
                std_allowed = self.settings['std_epsi'] *\
                        self.settings['max_std']
            elif 'sigma' in param:
                std_allowed = self.settings['std_sigma'] *\
                        self.settings['max_std']
            else:
                raise KeyError('Unknown parameter in Lennard-Jones.')
            plot_settings['title'] = f"{param}"
        elif (ptype == 'me' and
                (param == 'pow' or param == 'fact')):
            if param == 'pow':
                std_allowed = self.settings['std_pow'] *\
                        self.settings['max_std']
            elif param == 'fact':
                std_allowed = self.settings['std_fact'] *\
                        self.settings['max_std']
            else:
                raise KeyError('Unknown parameter in ME collison.')
        else:
            raise KeyError('Unknown type of parameter selected.')
        return std_allowed, plot_settings

    def make_figure(self,
                    std_allowed: float,
                    plot_settings: dict,
                    col: str,
                    selected_gen: list[int]):

        fig = go.Figure()
        # Add line for initial value to the graph
        idx = self.sop_db.columns.index(col)
        init_val: float = self.gapp.init_vals[idx+1]
        fig.add_vline(x=init_val,
                      line_dash='dash',
                      line_width=2,
                      line_color='black')

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

        avrg = []
        nel = []
        cols = ['sop_id']
        cols.extend(self.sop_db.columns)
        all_gen_rows = []
        for gen_i in selected_gen:
            self.gapp.glog.debug(
                f'Elements in goat line: {len(self.gapp.goats[gen_i].split())}')
            for origin in self.gapp.goats[gen_i].split():
                gen_id = int(origin.split('_')[0])
                el_id = int(origin.split('_')[1])
                self.sop_db.prepare_batch_select(
                    table=f'G{gen_id:04d}',
                    row_id=el_id
                )
            all_gen_rows.append(self.sop_db.batch_select())
        for idx, gen_rows in enumerate(all_gen_rows):
            df = pd.DataFrame(data=gen_rows, columns=cols)
            avrg.append(f"{df[col].mean():.3f}")
            nel.append(len(df[col]))
            fig.add_trace(go.Histogram(
                histfunc="count",
                x=df[col],
                nbinsx=30,
                name=f'Gen {selected_gen[idx]}',
                bingroup=1))
        # Overlay both histograms
        fig.update_layout(
            barmode='overlay',
            xaxis=dict(
                title=plot_settings['title'],
                showline=True,
                showgrid=True,
                showticklabels=True,
                linecolor='rgb(0, 0, 0)',
                linewidth=2,
                ticks='inside',
                tickformat=plot_settings['tickformat'],
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
                tickfont=dict(
                    family='Arial',
                    size=12,
                    color='rgb(0, 0, 0)')
            ),
            plot_bgcolor='white'
            )
        # Reduce opacity to see both histograms
        fig.update_traces(opacity=0.75)
        return [html.H3(
                    f'Distribution of {col} in generation {selected_gen}'
                    ),
                html.H5(f"Average: {avrg}"),
                html.H5(f'Number of elements: {nel}'),
                dcc.Graph(figure=fig)]
