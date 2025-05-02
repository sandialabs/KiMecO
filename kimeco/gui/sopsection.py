from dash import html, dcc, Output, Input, State, MATCH
from plotly.graph_objs._figure import Figure
import plotly.graph_objects as go
import pandas as pd
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.gui.section import Section
from kimeco.barrier import Barrier
from kimeco.well import Well
from kimeco.bimolecular import Bimolecular
from dash.exceptions import PreventUpdate
from typing import Any
from kimeco.gui.histogram import Histogram


class SOPSection(Section):
    def __init__(self, gapp) -> None:
        super().__init__(gapp)
        self.pert: Perturbator = gapp.pert

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
                boundaries = self.get_boundaries(col)
                plot_settings = self.get_plot_options(
                    col,
                    ptype)
                sop_plot_children.extend(
                    self.make_figure(
                        boundaries,
                        plot_settings,
                        col,
                        selected_gen
                    )
                )
            return ({'display': 'block'},
                    sop_plot_children
                    )

        @self.app.callback(
            Output({'type': 'sop_figure', 'index': MATCH}, 'figure'),
            Input({'type': 'nbin_sop', 'index': MATCH}, 'value'),
            State({'type': 'sop_figure', 'index': MATCH}, 'figure'),
        )
        def update_fig_nbin(nbin,
                            fig):

            # Create a new figure object based on the existing figure
            new_fig = go.Figure(data=fig['data'], layout=fig['layout'])

            # Update the nbinsx for each histogram trace
            if nbin is not None:
                new_fig.update_traces(nbinsx=nbin)

            return new_fig
            
    def get_boundaries(self,
                       col: str) -> list[str]:
        """Get the boundary conditions directly from the perturbator

        Args:
            col (str): parameter's name

        Returns:
            list[str]: [min, max]
        """
        idx = self.sop_db.columns.index(col)
        init_val: float = self.gapp.init_vals[idx+1]
        raw_molec: str = col.split('__')[0]
        param: str = col.split('__')[1]
        if 'score' in col:
            return [0.0, 0.0]
        for substr in self.pert.ptypes:
            if substr in param:
                if substr == 'e' and\
                   isinstance(self.init_SOP.items[raw_molec], Barrier):
                    ptype = 'b'
                else:
                    ptype = substr
                break

        return self.pert.get_boundaries(
            ptype=ptype,
            i_val=init_val)

    def get_plot_options(self,
                         col: str,
                         ptype: str
                         ) -> dict[str, Any]:
        """Setup the figure ploting options depending on
        the parameter to plot.

        Args:
            col (str): parameter's name
            ptype (str): parameter's type

        Raises:
            NotImplementedError: _description_
            NotImplementedError: _description_
            KeyError: _description_

        Returns:
            dict[str, Any]: dictionary of options settings
        """
        plot_settings: dict[str, Any] = {
            'title': col,
            'tickformat': '.2f',
            'unit': ''
        }
        raw_molec: str = col.split('__')[0]
        if raw_molec in self.settings['ct_names']:
            molec = self.settings['ct_names'][raw_molec]
        else:
            molec = raw_molec
        param: str = col.split('__')[1]
        if ptype == 'score' and param == 'score':
            plot_settings['title'] = ptype
            plot_settings['tickformat'] = 'e'
        elif ptype == 'e' and param == 'e':
            plot_settings['title'] = \
                f'Energy of {molec} (kcal mol<sup>-1</sup>)'
            plot_settings['unit'] = ' (kcal mol<sup>-1</sup>)'
        elif ptype == 'if' and param == 'if':
            plot_settings['unit'] = ' (cm<sup>-1</sup>)'
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
            plot_settings['title'] = \
                f'I. frequency from {From} to {To} (cm<sup>-1</sup>)'
        elif ptype == 'hr' and 'hr' in param:
            plot_settings['title'] = f'Rotor perturbation {param} of {molec}'
        elif ptype == 'f_p' and 'hf_p' in param:
            plot_settings['title'] = \
                f'Frequency perturbation {param} of {molec}'
        elif ptype == 'f_p' and 'lf_p' in param:
            plot_settings['title'] = \
                f'Frequency perturbation {param} of {molec}'
        elif ptype == 'f_p' and 'sf_p' in param:
            plot_settings['title'] = \
                f'Symmetry factor {param} of {molec}'
        elif (ptype == 'lj' and
                ('epsi' in param or 'sigma' in param)):
            plot_settings['title'] = f"{param}"
        elif (ptype == 'me' and param == 'fact'):
            plot_settings['title'] = \
                "dE<sup>(0)</sup><sub>down</sub> (cm<sup>-1</sup>)"
            plot_settings['unit'] = ' (cm<sup>-1</sup>)'
        elif (ptype == 'me' and param == 'pow'):
            plot_settings['title'] = f"{param}"
        else:
            raise KeyError('Unknown type of parameter selected.')
        return plot_settings

    def make_figure(self,
                    boundaries: float,
                    plot_settings: dict,
                    col: str,
                    selected_gen: list[int]):
        # Add line for initial value to the graph
        idx = self.sop_db.columns.index(col)
        init_val: float = self.gapp.init_vals[idx+1]

        all_gen_rows = {}
        for gen_i in selected_gen:
            for origin in self.gapp.goats[gen_i].split():
                gen_id = int(origin.split('_')[0])
                el_id = int(origin.split('_')[1])
                self.sop_db.prepare_batch_select(
                    table=f'G{gen_id:04d}',
                    row_id=el_id
                )
            all_gen_rows[gen_i] = self.sop_db.batch_select(col)
        hist = Histogram(
            data=all_gen_rows,
            settings=plot_settings
        )
        hist.add_vline(x=init_val,
                       line_width=2,
                       line_color='black')

        lb: float = min(boundaries)
        ub: float = max(boundaries)
        if lb != ub:
            hist.add_vline(x=lb,
                           line_width=4,
                           line_color='brown')
            hist.add_vline(x=ub,
                           line_width=4,
                           line_color='brown')

        return hist.layout()
