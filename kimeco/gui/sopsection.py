from dash import html, dcc, Output, Input, State, MATCH
import plotly.graph_objects as go
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.gui.section import Section
from kimeco.barrier import Barrier
from kimeco.well import Well
from kimeco.bimolecular import Bimolecular
from dash.exceptions import PreventUpdate
from typing import Any
from kimeco.gui.histogram import Histogram
import numpy as np
from kimeco.enums import Ptype
from kimeco.database.kimeco_db import dbs


class SOPSection(Section):
    def __init__(self, gapp) -> None:
        super().__init__(gapp)
        self.pert: Perturbator = gapp.pert
        self.ptype2title: dict[str, str] = {
            Ptype.WE.value: 'Energy of {molec} (kcal mol<sup>-1</sup>)',
            Ptype.BE.value: 'Energy of {molec} (kcal mol<sup>-1</sup>)',
            Ptype.IF.value: 'Imaginary frequency of {molec} (cm<sup>-1</sup>)',
            Ptype.ETP.value: 'Energy transfer power',
            Ptype.ETF.value: 'Energy transfer factor (cm<sup>-1</sup>)',
            Ptype.SIG.value: '{col}',
            Ptype.EPSI.value: '{col}',
            Ptype.BFC.value: 'Batch frequency perturbation coefficient of {molec}',
            Ptype.IFC.value: 'Individual freq perturbation of {col} for {molec}',
            Ptype.HRS.value: 'Hindered rotor coefficient {col} of {molec}',
            Ptype.MRC.value: 'Symmetry factor of Multi-D rotor {col} of {molec}',
            Ptype.SFC.value: 'Symmetry factor of barrierless reaction {molec}',
            Ptype.SCORE.value: "Average of {molec}'s score across all experiments"
        }
        self.ptype2tfm: dict[str, str] = {
            Ptype.WE.value: '.2f',
            Ptype.BE.value: '.2f',
            Ptype.IF.value: '.2f',
            Ptype.ETP.value: '.2f',
            Ptype.ETF.value: '.2f',
            Ptype.SIG.value: '.2f',
            Ptype.EPSI.value: '.2f',
            Ptype.BFC.value: '.2f',
            Ptype.IFC.value: '.2f',
            Ptype.HRS.value: '.2f',
            Ptype.MRC.value: '.2f',
            Ptype.SFC.value: '.2f',
            Ptype.SCORE.value: '.2f'
        }
        self.ptype2unit: dict[str, str] = {
            Ptype.WE.value: u' (kcal mol\u207B\u00B9)',
            Ptype.BE.value: u' (kcal mol\u207B\u00B9)',
            Ptype.IF.value: u' (cm\u207B\u00B9)',
            Ptype.ETP.value: '',
            Ptype.ETF.value: u' (cm\u207B\u00B9)',
            Ptype.SIG.value: '',
            Ptype.EPSI.value: '',
            Ptype.BFC.value: '',
            Ptype.IFC.value: '',
            Ptype.HRS.value: '',
            Ptype.MRC.value: '',
            Ptype.SFC.value: '',
            Ptype.SCORE.value: ''
        }

    @property
    def layout(self) -> html.Div:
        return html.Div(
            id='sop',
            style={'display': 'none'},
            children=[
                html.H3('Type of parameter to plot:'),
                dcc.RadioItems(options=[
                    {'label': 'Energies',
                     'value': [Ptype.WE.value, Ptype.BE.value]},
                    {'label': 'Frequencies',
                     'value': [Ptype.IFC.value, Ptype.BFC.value]},
                    {'label': 'Imaginary freq',
                     'value': [Ptype.IF.value]},
                    {'label': 'Rotor perturbation',
                     'value': [Ptype.HRS.value, Ptype.MRC.value]},
                    {'label': 'Lennard-Jones',
                     'value': [Ptype.SIG.value, Ptype.EPSI.value]},
                    {'label': 'Score',
                     'value': [Ptype.SCORE.value]},
                    {'label': 'ME collision',
                     'value': [Ptype.ETF.value, Ptype.ETP.value]}],
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
        def update_p_choice(ptypes: list[str]
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
                param: str = col.split(dbs)[1]
                for ptype in ptypes:
                    if ptype in param:
                        if len(ptypes) == 1:
                            filtered_param.append({
                                'label': f"{molec}",
                                'value': col})
                        else:
                            filtered_param.append({
                                'label': f"{molec} {param}",
                                'value': col})
                        break

            if ptype != '':
                style: dict[str, str] = {'display': 'block'}
            else:
                style = {'display': 'none'}
            return style, filtered_param

        # Show sop plot button once generation and parameters are selected
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
                              ptype: list[str],
                              param_selected: list[str],
                              selected_gen: list[int]
                              ) -> tuple[dict[str, str], list[Any]]:
            if clic == 0 or clic is None:
                raise PreventUpdate

            sop_plot_children = []
            for col in param_selected:
                boundaries: list[float] = self.get_boundaries(col)
                plot_settings: dict[str, Any] = self.get_plot_options(
                    col,
                    ptype)
                sop_plot_children.extend(
                    self.make_figure(
                        boundaries=boundaries,
                        plot_settings=plot_settings,
                        col=col,
                        selected_gen=selected_gen
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
                       col: str) -> list[float]:
        """Get the boundary conditions directly from the perturbator

        Args:
            col (str): parameter's name

        Returns:
            list[str]: [min, max]
        """
        idx: int = self.sop_db.columns.index(col)
        init_val: float = self.gapp.init_vals[idx+1]
        param: str = col.split(dbs)[1]
        for ptype in Ptype:
            if ptype.value in param:
                break
        return self.pert.get_boundaries(
            ptype=ptype.value,
            i_val=init_val)

    def get_plot_options(self,
                         col: str,
                         ptypes: list[str]
                         ) -> dict[str, Any]:
        """Setup the figure ploting options depending on
        the parameter to plot.

        Args:
            col (str): parameter's name
            ptypes (list[Ptype]): list of parameter's type

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
        raw_molec: str = col.split(dbs)[0]
        if raw_molec in self.settings['ct_names']:
            molec = self.settings['ct_names'][raw_molec]
        else:
            molec: str = raw_molec
        param: str = col.split(dbs)[1]
        for ptype in ptypes:
            if ptype in param:
                break
        if ptype == Ptype.IF.value:
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
            molec = f'{From} to {To}'
        title: str = self.ptype2title[ptype]
        if '{molec}' in title and '{col}' in title:
            title = title.format(col=col, molec=molec)
        elif '{molec}' in title:
            title = title.format(molec=molec)
        elif '{col}' in title:
            title = title.format(col=col)
        plot_settings['title'] = title
        plot_settings['tickformat'] = self.ptype2tfm[ptype]
        plot_settings['unit'] = self.ptype2unit[ptype]

        # "dE<sup>(0)</sup><sub>down</sub> (cm<sup>-1</sup>)"

        return plot_settings

    def make_figure(self,
                    boundaries: list[float],
                    plot_settings: dict,
                    col: str,
                    selected_gen: list[int]):
        # Add line for initial value to the graph
        idx: int = self.sop_db.columns.index(col)
        init_val: float = self.gapp.init_vals[idx+1]

        all_gen_rows: dict[int, Any] = {}
        for gen_i in selected_gen:
            for origin in self.gapp.goats[gen_i].split():
                gen_id = int(origin.split('_')[0])
                el_id = int(origin.split('_')[1])
                self.sop_db.prepare_batch_select(
                    table=f'G{gen_id:04d}',
                    row_id=el_id
                )
            all_gen_rows[gen_i] = \
                np.concatenate(self.sop_db.batch_select_col(col))

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
