from dash import html, dcc, callback, Output, Input, State
import numpy as np
from typing import Any, Optional, List, Tuple
from kimeco.gui.section import Section
# Figure import not required for current return types; keep types minimal
from dash.exceptions import PreventUpdate
from kimeco.gui.histogram import Histogram
from kimeco.goat import RateResult


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
                html.H4('PES IDs (optional):'),
                dcc.Dropdown(options=[
                    pid for pid in self.init_SOP.pes_ids],
                    multi=True,
                    id='rc_pes'),
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
            State('rc_pes', 'value'),
            State('gen range slider', 'value'),
            prevent_initial_call=True,
            running=[
                (Output("kin_plot_button", "disabled"), True, False),
                (Output("kin_plot_button", "children"), 'Updating', 'Plot')]
        )
        def update_kin_figure(
            clic,
            From: list[str],
            To: list[str],
            pres: list[float],
            temp: list[float],
            pes_ids: Optional[list[int]],
            selected_gen: list[int],
        ) -> tuple[dict[str, str], list[Any]]:
            if clic is None:
                raise PreventUpdate

            # Build requested P/T conditions
            req_conditions = [(float(p), float(t)) for p in pres for t in temp]

            # Resolve displayed names to DB keys once and prepare pairs
            rate_pairs_db: List[Tuple[Optional[str], Optional[str]]] = []
            display_to_db: dict[Tuple[str, str],
                                Tuple[Optional[str], Optional[str]]] = {}
            for disp_to in To:
                if disp_to in self.init_SOP.wells_names:
                    to_db_candidate = disp_to
                else:
                    to_db_candidate = next(
                        (bim.name for bim in self.init_SOP.bimolecular
                         if disp_to in bim.frag_names),
                        None,
                    )
                for disp_frm in From:
                    if disp_frm in self.init_SOP.wells_names:
                        frm_db_candidate = disp_frm
                    else:
                        frm_db_candidate = next(
                            (bim.name for bim in self.init_SOP.bimolecular
                             if disp_frm in bim.frag_names),
                            None,
                        )
                    rate_pairs_db.append((frm_db_candidate, to_db_candidate))
                    display_to_db[(disp_frm, disp_to)] = (
                        frm_db_candidate,
                        to_db_candidate,
                    )

            # Fetch all rates in a single batched DB call
            all_rates: RateResult = self.gapp.goats.get_rate_coefficients(
                req_conditions,
                selected_gen,
                rate_pairs_db,
                pes_ids=pes_ids,
            )

            figs: list[Any] = []
            for p in pres:
                for t in temp:
                    for disp_to in To:
                        for disp_frm in From:
                            db_pair = display_to_db.get((disp_frm, disp_to))
                            result = self.make_figure(
                                generations=selected_gen,
                                p=float(p),
                                t=float(t),
                                To=disp_to,
                                From=disp_frm,
                                db_pair=db_pair,
                                rates=all_rates,
                            )
                            # make_figure may return a single component
                            # or a list
                            if isinstance(result, list):
                                figs.extend(result)
                            else:
                                figs.append(result)

            if not figs:
                # No figures produced — show a helpful message in the UI
                msg = html.Div([
                    html.P(
                        'No data available for the selected '
                        'species/conditions.'
                    ),
                    html.P(
                        'Check that you selected valid From/To species,'
                        ' pressures, temperatures, and generations.'
                    ),
                ])
                return {'display': 'block'}, [msg]

            return {'display': 'block'}, figs

    def make_figure(
        self,
        generations: list[int],
        p: float,
        t: float,
        To: str,
        From: str,
        db_pair: Optional[Tuple[Optional[str], Optional[str]]],
        rates: RateResult,
    ) -> Any:
        plot_settings: dict[str, Any] = {
            'title': '',
            'tickformat': '.2e',
            'unit': ''
        }

        frm_db, to_db = (None, None) if db_pair is None else db_pair

        # Determine unit and display names (keep display names From/To)
        if frm_db in self.init_SOP.wells_names:
            unit = 's<sup>-1</sup> '
            plot_settings['unit'] = u's\u207B\u00B9'
        else:
            unit = 'cm<sup>3</sup> molecule<sup>-1</sup> s<sup>-1</sup>'
            plot_settings['unit'] = (
                u'cm\u00B3 molecule\u207B\u00B9 s\u207B\u00B9'
            )

        all_gen_rows: dict[int, np.ndarray] = {}
        for gen_i in generations:
            tokens = []
            try:
                tokens = self.gapp.goats.generations[gen_i]
            except Exception:
                tokens = []
            all_gen_rows[gen_i] = np.empty(len(tokens))
            for idx, (mdl_gen, mdl_id) in enumerate(tokens):
                val = None
                if (gen_i in rates
                        and frm_db is not None
                        and to_db is not None):
                    conds = rates[gen_i]
                    key_cond = (float(p), float(t))
                    pair = conds.get(key_cond, {})
                    pair = pair.get((frm_db, to_db), {})
                    val = pair.get((mdl_gen, mdl_id), None)
                all_gen_rows[gen_i][idx] = (
                    val if val is not None else np.nan
                )

        plot_settings['title'] = (
            f"Rate coefficients ({unit}) from {From} to {To} at"
            f" {p} {self.settings['pres_unit']}/{t} K"
        )
        # Histogram expects dict[int, list[float]]; convert arrays to lists

        def coerce_list(arr):
            if hasattr(arr, 'tolist'):
                raw = arr.tolist()
            else:
                raw = list(arr)
            coerced: list[float] = []
            for v in raw:
                try:
                    coerced.append(float(v))
                except Exception:
                    coerced.append(float('nan'))
            return coerced

        hist_data = {g: coerce_list(arr) for g, arr in all_gen_rows.items()}
        hist = Histogram(
            data=hist_data,
            settings=plot_settings,
        )
        return hist.layout()
