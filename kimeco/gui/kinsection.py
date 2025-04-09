from dash import html, dcc, callback, Output, Input, State
import plotly.graph_objects as go
import pandas as pd
from kimeco.gui.section import Section
from plotly.graph_objs._figure import Figure


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
                    # multi=True,
                    id='rc_from'),
                html.H4('To:'),
                dcc.Dropdown(options=[
                    sp for sp in self.species],
                    # multi=True,
                    id='rc_to'),
                html.H4('Pressure (Torr):'),
                dcc.Dropdown(options=[
                    p for p in self.settings['rc_pres']],
                    # multi=True,
                    id='rc_P'),
                html.H4('Temperature (K):'),
                dcc.Dropdown(options=[
                    t for t in self.settings['rc_temp']],
                    # multi=True,
                    id='rc_T'),
                # Plot BUTTON
                html.Div(
                    id='kin_plot_b',
                    style={'display': 'none'},
                    children=[
                        html.Button(id='kin_plot_button',
                                    n_clicks=0,
                                    children='Plot',
                                    )]),
                html.Div(
                    className='row',
                    id='kin_plot',
                    style={'display': 'none'},
                    children=[
                        html.H3(children={}, id='kin_dist_title'),
                        html.H5(children={}, id='kin_avrg'),
                        html.H5(children={}, id='kin_elem'),
                        dcc.Graph(figure={}, id='kin_dist')])])

    def register_callbacks(self):
        @callback(
            Output(component_id='kin_plot_b', component_property='style'),
            Input(component_id='rc_from', component_property='value'),
            Input(component_id='rc_to', component_property='value'),
            Input(component_id='rc_P', component_property='value'),
            Input(component_id='rc_T', component_property='value'),
            State(component_id='gen range slider', component_property='value')
        )
        def show_kin_plot_button(rc_from: str,
                                 rc_to: str,
                                 rc_P: float,
                                 rc_T: float,
                                 selected_gen: list[int]):
            if (rc_from in self.species and
                rc_to in self.species and
                rc_P in self.settings['rc_pres'] and
                rc_T in self.settings['rc_temp'] and
                all([gen_i in range(self.gapp.kin_tot_g)
                     for gen_i in selected_gen])):
                return {'display': 'block'}
            else:
                return {'display': 'none'}

        # Plot and print the distribution of the requested rate coefficients
        @callback(
            Output(component_id='kin_plot', component_property='style'),
            Output(component_id='kin_dist', component_property='figure'),
            Output(component_id='kin_dist_title', component_property='children'),
            Output(component_id='kin_avrg', component_property='children'),
            Output(component_id='kin_elem', component_property='children'),
            Input(component_id='kin_plot_button', component_property='n_clicks'),
            State(component_id='rc_from', component_property='value'),
            State(component_id='rc_to', component_property='value'),
            State(component_id='rc_P', component_property='value'),
            State(component_id='rc_T', component_property='value'),
            State(component_id='gen range slider', component_property='value')
        )
        def update_kin_figure(clic,
                              From: str,
                              To: str,
                              pres: float,
                              temp: float,
                              selected_gen: list[int]
                              ) -> \
                tuple[dict[str, str], Figure, str, str, str]:
            avrg = []
            nel = []
            fig = go.Figure()
            if (clic == 0 or
                From not in self.species or
                To not in self.species or
                temp not in self.settings['rc_temp'] or
                pres not in self.settings['rc_pres']):

                return ({'display': 'none'},
                        fig,
                        '',
                        '',
                        '')
            gen_rows = [
                self.kin_db.get_kin_rc(table=f'G{gen_i:04d}',
                                       From=self.gapp.og_names[From],
                                       To=self.gapp.og_names[To],
                                       pres=pres,
                                       temp=temp)
                for gen_i in selected_gen]
            nbinsx = 30
            # Overlay both histograms
            fig.update_layout(barmode='overlay',
                              xaxis=dict(
                                title='Rate coefficient',
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
            for idx, gen_row in enumerate(gen_rows):
                df = pd.DataFrame(
                        data=gen_row,
                        columns=['kin_id', 'Rate coefficient'])
                avrg.append(f"{df['Rate coefficient'].mean():.3f}")
                nel.append(len(df['Rate coefficient']))
                fig.add_trace(go.Histogram(
                    histfunc="count",
                    x=df['Rate coefficient'],
                    nbinsx=nbinsx,
                    autobinx=False,
                    name=f'Gen {idx}',
                    bingroup=1))
            # Reduce opacity to see both histograms
            fig.update_traces(opacity=0.75)
            return ({'display': 'block'},
                    fig,
                    f"""Distribution of the rate\
                    coefficient from {From} to \
                    {To} in generations {selected_gen}""",
                    f'Average: {avrg}',
                    f'Number of elements: {nel}')
