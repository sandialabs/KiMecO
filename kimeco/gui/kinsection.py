from dash import html, dcc, callback, Output, Input, State
import plotly.graph_objects as go
import numpy as np
from kimeco.gui.section import Section
from plotly.graph_objs._figure import Figure
from dash.exceptions import PreventUpdate


class KINSection(Section):

    @property
    def layout(self) -> html.Div:
        return html.Div(
            className='row', id='kin',
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
                html.H4('Pressure (Torr):'),
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

            all_gen_rates = []
            for gen_i in selected_gen:
                for p in pres:
                    for t in temp:
                        for _to in To:
                            # Find the corresponding name in db
                            for k, v in self.settings['ct_names'].items():
                                if v == _to:
                                    tmp_to = k
                                    break
                            if tmp_to in self.init_SOP.wells_names:
                                to = tmp_to
                            else:
                                for bim in self.init_SOP.bimolecular:
                                    if tmp_to in bim.frag_names:
                                        to = bim.name
                                        break
                            for _frm in From:
                                # Find the corresponding name in db
                                for k, v in self.settings['ct_names'].items():
                                    if v == _frm:
                                        tmp_frm = k
                                        break
                                if tmp_frm in self.init_SOP.wells_names:
                                    frm = tmp_frm
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
                all_gen_rates.append(self.kin_db.batch_select())
            all_figs = []
            for gen_i, rates in zip(selected_gen, all_gen_rates):
                for p in pres:
                    for t in temp:
                        for to in To:
                            for frm in From:
                                all_figs.extend(self.make_figure(
                                    gen_name=f'G{gen_i:04d}',
                                    p=p,
                                    t=t,
                                    To=to,
                                    From=frm,
                                    rates=rates
                                ))
            return {'display': 'block'}, all_figs

    def make_figure(self,
                    gen_name: str,
                    p: float,
                    t: float,
                    To: str,
                    From: str,
                    rates: dict[dict[dict[tuple, float]]]):
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
        else:
            unit = 'cm<sup>3</sup> s<sup>-1</sup> molecule<sup>-1</sup>'
            for bim in self.init_SOP.bimolecular:
                if tmp_frm in bim.frag_names:
                    frm = bim.name
                    break
        cond = (p, t, to, frm)

        fig = go.Figure()
        nbinsx = 30
        # Overlay both histograms
        fig.update_layout(
            barmode='overlay',
            xaxis=dict(
                title=f'Rate coefficient ({unit})',
                #   type="log",
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
        p_t_to_frm = []
        for origin in rates:
            for kin_id in rates[origin]:
                p_t_to_frm.append(rates[origin][kin_id][cond])
        avrg = np.average(p_t_to_frm)
        nel = len(p_t_to_frm)
        fig.add_trace(go.Histogram(
            histfunc="count",
            x=p_t_to_frm,
            nbinsx=min(len(p_t_to_frm), nbinsx),
            autobinx=False,
            name=f'Gen {gen_name}',
            bingroup=1))
        title = f"Rate coefficients from {From} to {To} in {gen_name}"
        pres = f"P={p} Torr"
        temp = f"P={t} K"

        return [html.H3(title),
                html.H3(pres),
                html.H3(temp),
                html.H5(f'Average: {avrg:.3E}'),
                html.H5(f'Number of elements: {nel}'),
                dcc.Graph(figure=fig)]
