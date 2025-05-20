from dash import html, dcc, callback, Output, Input, State
import numpy as np
from typing import Any
from numpy.typing import NDArray
from kimeco.gui.section import Section
from plotly.graph_objs._figure import Figure
from dash.exceptions import PreventUpdate
from kimeco.gui.histogram import Histogram


class KINSection(Section):

    @property
    def layout(self) -> html.Div:
        return html.Div(
            id='kin',
            style={'display': 'none'},
            children=[
                html.H3('Select which rate coefficients to plot:'),
                html.H4('From:'),
                dcc.Dropdown(options=[
                    sp for sp in self.species],
                    multi=True,
                    id='rc_from'),
                html.H4('To:'),
                dcc.Dropdown(options=[
                    sp for sp in self.species],
                    multi=True,
                    id='rc_to'),
                html.H4(f'Pressure ({self.settings["pres_unit"]}):'),
                dcc.Dropdown(options=[
                    p for p in self.settings['rc_pres']],
                    multi=True,
                    id='rc_P'),
                html.H4('Temperature (K):'),
                dcc.Dropdown(options=[
                    t for t in self.settings['rc_temp']],
                    multi=True,
                    id='rc_T'),
                # Plot BUTTON
                html.Div(
                    id='kin_plot_b',
                    style={'display': 'none'},
                    children=[
                        html.Button(id='kin_plot_button',
                                    children='Plot',
                                    )]),
                html.Div(
                    className='row',
                    id='kin_plot')])

    def register_callbacks(self):
        @callback(
            Output('kin_plot_b', 'style'),
            Input('rc_from', 'value'),
            Input('rc_to', 'value'),
            Input('rc_P', 'value'),
            Input('rc_T', 'value')
        )
        def show_kin_plot_button(rc_from: list[str],
                                 rc_to: list[str],
                                 rc_P: list[float],
                                 rc_T: list[float]):
            if rc_from is None or\
               rc_to is None or\
               rc_P is None or\
               rc_T is None:
                raise PreventUpdate
            else:
                return {'display': 'block'}

        # Plot and print the distribution of the requested rate coefficients
        @callback(
            Output('kin_plot', 'style'),
            Output('kin_plot', 'children'),
            Input('kin_plot_button', 'n_clicks'),
            State('rc_from', 'value'),
            State('rc_to', 'value'),
            State('rc_P', 'value'),
            State('rc_T', 'value'),
            State('gen range slider', 'value'),
            prevent_initial_call=True,
            running=[
                (Output("kin_plot_button", "disabled"), True, False),
                (Output("kin_plot_button", "children"), 'Updating', 'Plot')]
        )
        def update_kin_figure(clic,
                              From: list[str],
                              To: list[str],
                              pres: list[float],
                              temp: list[float],
                              selected_gen: list[int]
                              ) -> \
                tuple[dict[str, str], Figure, str, str, str]:
            if clic is None:
                raise PreventUpdate

            for gen_i in selected_gen:
                for p in pres:
                    for t in temp:
                        for _to in To:
                            # Find the corresponding name in db
                            for k, v in self.settings['ct_names'].items():
                                if v == _to:
                                    tmp_to: str = k
                                    break
                            if tmp_to in self.init_SOP.wells_names:
                                to: str = tmp_to
                            else:
                                for bim in self.init_SOP.bimolecular:
                                    if tmp_to in bim.frag_names:
                                        to = bim.name
                                        break
                            for _frm in From:
                                # Find the corresponding name in db
                                for k, v in self.settings['ct_names'].items():
                                    if v == _frm:
                                        tmp_frm: str = k
                                        break
                                if tmp_frm in self.init_SOP.wells_names:
                                    frm: str = tmp_frm
                                else:
                                    for bim in self.init_SOP.bimolecular:
                                        if tmp_frm in bim.frag_names:
                                            frm = bim.name
                                            break
                                for origin in self.gapp.goats[gen_i].split():
                                    gen_id = int(origin.split('_')[0])
                                    kin_id = int(origin.split('_')[1])
                                    self.kin_db.prepare_batch_select(
                                        table=f'G{gen_id:04d}',
                                        kin_id=kin_id,
                                        p=p,
                                        t=t,
                                        From=frm,
                                        To=to
                                    )
            # Only do one request for all gen
            all_gen_rates: dict[str, dict[int, NDArray]] = \
                self.kin_db.batch_select()
            all_figs: list[Histogram] = []
            for p in pres:
                for t in temp:
                    for to in To:
                        for frm in From:
                            all_figs.extend(self.make_figure(
                                generations=selected_gen,
                                p=p,
                                t=t,
                                To=to,
                                From=frm,
                                rates=all_gen_rates
                            ))
            return {'display': 'block'}, all_figs

    def make_figure(self,
                    generations: list[int],
                    p: float,
                    t: float,
                    To: str,
                    From: str,
                    rates: list[dict[dict[dict[tuple, float]]]]):
        plot_settings: dict[str, Any] = {
            'title': '',
            'tickformat': '.2e',
            'unit': ''
        }
        # Find the names as saved in the kin db
        for k, v in self.settings['ct_names'].items():
            if v == To:
                tmp_to = k
                break
        if tmp_to in self.init_SOP.wells_names:
            to = tmp_to
        else:
            for bim in self.init_SOP.bimolecular:
                if tmp_to in bim.frag_names:
                    to = bim.name
                    break
        for k, v in self.settings['ct_names'].items():
            if v == From:
                tmp_frm = k
                break
        if tmp_frm in self.init_SOP.wells_names:
            frm = tmp_frm
            unit = 's<sup>-1</sup> '
            plot_settings['unit'] = u's\u207B\u00B9'
        else:
            unit = 'cm<sup>3</sup> molecule<sup>-1</sup> s<sup>-1</sup>'
            plot_settings['unit'] = \
                u'cm\u00B3 molecule\u207B\u00B9 s\u207B\u00B9'
            for bim in self.init_SOP.bimolecular:
                if tmp_frm in bim.frag_names:
                    frm = bim.name
                    break
        cond = (p, t, to, frm)

        all_gen_rows: dict[int, list[float]] = {}
        for gen_i in generations:
            all_gen_rows[gen_i] = np.empty(
                len(self.gapp.goats[gen_i].split()))
            for idx, origin in enumerate(self.gapp.goats[gen_i].split()):
                gen_id = int(origin.split('_')[0])
                kin_id = int(origin.split('_')[1])
                all_gen_rows[gen_i][idx] = \
                    rates[f"G{gen_id:04d}"][kin_id][cond]

        plot_settings['title'] = \
            f"Rate coefficients ({unit}) from {From} to {To} at"
        plot_settings['title'] += \
            f" {p} {self.settings['pres_unit']}/{t} K"
        hist = Histogram(
            data=all_gen_rows,
            settings=plot_settings
        )
        return hist.layout()
