from dash import Dash, html, dcc, callback, Output, Input, State
import sys
import os

import numpy as np
from game.readers.mess_input import MessInputReader
from game.database.game_db import Game_db
from game.element import Element
from game.user_input import check_input
from game.parameters import SOP
from game.well import Well
from game.barrier import Barrier
from game.scoring_f.weighteddif import WeightedDif
import pandas as pd
from plotly.graph_objs._figure import Figure
import plotly.graph_objects as go
import math


def main() -> None:
    if len(sys.argv) != 2:
        print("""
    GAME needs various parameters to be set in a JSON input file.
    This JSON input file shopuld be supplied as the first and only
    argument.

    Usage:  game path/to/JSON/input/file.json
    """)
        sys.exit()
    try:
        input_file: str = sys.argv[1]
    except IndexError:
        print('To use GAME, supply the input file as argument.')
        sys.exit(-1)

    settings: dict = check_input(input_file=input_file)

    mr = MessInputReader(settings=settings)
    init_SOP: SOP
    input_tpl: list[str]
    (init_SOP, input_tpl) = mr.read()
    if not os.path.isdir(settings['project_name']):
        print('''GAME graphical interface can only analyse the data
              of existing database created by a previous GAME run.
              Run GAME with project_name:{project_name},
              and then analyse the results.''')
        sys.exit()
    os.chdir(settings['project_name'])
    sop_db = Game_db(name='GAME_DB_SOP')
    sop_tot_g: int = len(sop_db._tables)
    kin_db = Game_db(name='GAME_DB_KIN')
    kin_tot_g: int = len(kin_db._tables)
    sim_db = Game_db(name='GAME_DB_SIM')

    # Define which scoring function to use
    if settings['scoring_func'].casefold() == 'weighteddif':
        sf = WeightedDif(settings=settings)
    else:
        # Default scoring function
        sf = WeightedDif(settings=settings)
    elem = Element(sop=init_SOP, id=0, sf=sf)

    species: list[str] = [
            elem.sop.items[specie].ct_name
            for specie, obj in elem.sop.items.items()
            if isinstance(obj, Well) and not isinstance(obj, Barrier)]
    og_names = {v: k for k, v in settings['ct_names'].items()}
    for ct_name, name in og_names.items():
        if name not in init_SOP.wells_names:
            for bimol in init_SOP.bimolecular:
                if name in bimol.frag_names():
                    og_names[ct_name] = bimol.name

    # Initialize app
    external_stylesheets: list[str] = ['~/projects/ethylperoxy/me/file.css']
    app = Dash(external_stylesheets=external_stylesheets)

    # App layout
    app.layout = [
        html.Div(className='row', children=[
            html.H1(children='Welcome to GAME graphical interface'),
            html.H2(children='Data to analyse:'),
            dcc.RadioItems(options=[
                {'label': 'Set of parameters', 'value': 'SOP'},
                {'label': 'Rate coefficients', 'value': 'KIN'},
                {'label': 'Concentration profiles', 'value': 'SIM'}
                ],
                        value='Set of parameters',
                        inline=True,
                        id='rb_start')

        ]),
        ############################
        #   GENERATION SELECTION   #
        ############################
        html.Div(
            className='row',
            id='gen_selection',
            style={'display': 'block'},
            children=[
                html.H3('Enter the number \
                        of generation to plot.'),
                dcc.Input(
                    min=1,
                    max=sop_tot_g,
                    type="number",
                    value=1,
                    placeholder="Number of generation",
                    id='gen_num'),
                # Select from which generation
                dcc.RangeSlider(
                    id='gen range slider',
                    min=0,
                    max=sop_tot_g-1,
                    step=1,
                    pushable=True,
                    value=[0],
                    marks={
                        0: 'Generation 0',
                        sop_tot_g-1: f'Generation {sop_tot_g-1}'},
                    tooltip={
                            "always_visible": False,
                            "template": "Generation {value}"})
                ]),
        ############################
        #        SOP SECTION       #
        ############################
        html.Div(
            className='row', id='sop',
            style={'display': 'none'},
            children=[
                html.H3('Select which type of parameter to plot:'),
                dcc.RadioItems(options=[
                    {'label': 'Energies', 'value': '_e'},
                    {'label': 'Imaginary freq', 'value': '_if'},
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
                                         value='score',
                                         id='param_selection')
                            ]),
                # Plot BUTTON
                html.Div(
                    id='show_sop_plot_button',
                    style={'display': 'none'},
                    children=[
                        html.Button(id='sop_plot_button',
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
                    ])]),
        ############################
        #        KIN SECTION       #
        ############################
        html.Div(
            className='row', id='kin',
            style={'display': 'none'},
            children=[
                html.H3('Select which rate coefficients to plot:'),
                html.H4('From:'),
                dcc.Dropdown(options=[
                    sp for sp in species],
                    # multi=True,
                    id='rc_from'),
                html.H4('To:'),
                dcc.Dropdown(options=[
                    sp for sp in species],
                    # multi=True,
                    id='rc_to'),
                html.H4('Pressure (Torr):'),
                dcc.Dropdown(options=[
                    p for p in settings['rc_pres']],
                    # multi=True,
                    id='rc_P'),
                html.H4('Temperature (K):'),
                dcc.Dropdown(options=[
                    t for t in settings['rc_temp']],
                    # multi=True,
                    id='rc_T'),
                # Plot BUTTON
                html.Div(
                    id='show_kin_plot_button',
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
                        dcc.Graph(figure={}, id='kin_dist')])]),
        html.Div(className='row', id='sim', style={'display': 'none'})
    ]

    # GENERATION CONTROL
    @callback(
        Output(component_id='gen range slider', component_property='value'),
        State(component_id='gen range slider', component_property='value'),
        Input(component_id='gen_num', component_property='value')
    )
    def update_gen_slider(selected_gen: list[int],
                          gen_num: int) -> list[int]:
        """Adjust the number of button in the generation RangeSlider

        Args:
            gen_num (int): Number requested
            selected_gen (list[int]): curent generation selection

        Returns:
            list[int]: selected generations
        """
        while len(selected_gen) != gen_num and\
            len(selected_gen) < sop_tot_g and\
            len(selected_gen) >= 1:

            if len(selected_gen) < gen_num:
                for i in range(sop_tot_g):
                    if i not in selected_gen:
                        selected_gen.append(i)
                        break
            else:
                selected_gen.pop(-1)
        return selected_gen

    # Select which division to show: sop, kin or sim
    @callback(
        Output(component_id='sop', component_property='style'),
        Output(component_id='kin', component_property='style'),
        Output(component_id='sim', component_property='style'),
        Input(component_id='rb_start', component_property='value')
    )
    def update_layout(data_type):
        if data_type == 'SOP':
            sop_style = {'display': 'block'}
            kin_style = {'display': 'none'}
            sim_style = {'display': 'none'}
        elif data_type == 'KIN':
            sop_style = {'display': 'none'}
            kin_style = {'display': 'block'}
            sim_style = {'display': 'none'}
        elif data_type == 'SIM':
            sop_style = {'display': 'none'}
            kin_style = {'display': 'none'}
            sim_style = {'display': 'block'}
        else:
            sop_style = {'display': 'none'}
            kin_style = {'display': 'none'}
            sim_style = {'display': 'none'}
        return sop_style, kin_style, sim_style

    # SOP interactions
    # Show parameter selection once the type of parameter has been selected
    @callback(
        Output(component_id='param_select_row', component_property='style'),
        Output(component_id='param_selection', component_property='options'),
        Input(component_id='ptype', component_property='value')
    )
    def update_param_choice(param_type):
        filtered_param: list[str] = [
            nm for nm in init_SOP.parameters_names if nm.endswith(param_type)]
        if len(filtered_param) != len(init_SOP.parameters_names):
            style = {'display': 'block'}
        else:
            style = {'display': 'none'}
        return style, filtered_param

    # Show sop plot button once generation and parameters have been selected
    @callback(
        Output(component_id='show_sop_plot_button', component_property='style'),
        Input(component_id='param_selection', component_property='value')
    )
    def show_sop_one_gen_plot_button(selected_param: str
                                     ) -> dict[str, str]:
        if selected_param in init_SOP.parameters_names:
            return {'display': 'block'}
        else:
            return {'display': 'none'}

    # Plot the distribution of the requested parameter
    @callback(
        Output(component_id='sop_plot', component_property='style'),
        Output(component_id='param_dist', component_property='figure'),
        Output(component_id='sop_dist_title', component_property='children'),
        Output(component_id='sop_avrg', component_property='children'),
        Output(component_id='sop_elem', component_property='children'),
        Input(component_id='show_sop_plot_button', component_property='n_clicks'),
        State(component_id='param_selection', component_property='value'),
        State(component_id='gen range slider', component_property='value')
    )
    def update_sop_figure(clic,
                          param: str,
                          selected_gen: list[int]
                          ) -> tuple[dict[str, str], Figure, str, str, str]:
        names: list[str] = ['sop_id']
        for nm in init_SOP.parameters_names:
            names.append(nm)
        avrg = []
        nel = []
        fig = go.Figure()
        gen_rows = [
            sop_db.get_table(table=f'G{gen_i}')
            for gen_i in selected_gen]
        for idx, gen_rows in enumerate(gen_rows):
            df = pd.DataFrame(data=gen_rows, columns=names)
            avrg.append(df[param].mean())
            nel.append(len(df[param]))
            fig.add_trace(go.Histogram(
                histfunc="count",
                x=df[param],
                nbinsx=20,
                name=f'Gen {selected_gen[idx]}',
                bingroup=1))
        # Overlay both histograms
        fig.update_layout(barmode='overlay',
                          xaxis_title_text=param,
                          yaxis_title_text='Count of elements')
        # Reduce opacity to see both histograms
        fig.update_traces(opacity=0.75)
        return ({'display': 'block'},
                fig,
                f'Distribution of {param} in generation {selected_gen}',
                f'Average: {avrg}',
                f'Number of elements: {nel}')

    # KIN Interactions
    # Show sop plot button once generation and parameters have been selected
    @callback(
        Output(component_id='show_kin_plot_button', component_property='style'),
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
        if rc_from in species and\
           rc_to in species and\
           rc_P in settings['rc_pres'] and\
           rc_T in settings['rc_temp'] and\
           all([gen_i in range(sop_tot_g) for gen_i in selected_gen]):
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
        Input(component_id='show_kin_plot_button', component_property='n_clicks'),
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
                          ) -> tuple[dict[str, str], Figure, str, str, str]:
        avrg = []
        nel = []
        fig = go.Figure()
        if From not in species or\
           To not in species or\
           temp not in settings['rc_temp'] or\
           pres not in settings['rc_pres']:
            return ({'display': 'none'},
                    fig,
                    '',
                    '',
                    '')
        gen_rows = [
            kin_db.get_kin_rc(table=f'G{gen_i}',
                              From=og_names[From],
                              To=og_names[To],
                              pres=pres,
                              temp=temp)
            for gen_i in selected_gen]
        nbinsx = 20
        for idx, gen_rows in enumerate(gen_rows):
            df = pd.DataFrame(
                    data=gen_rows,
                    columns=['kin_id', 'Rate coefficient'])
            avrg.append(df['Rate coefficient'].mean())
            nel.append(len(df['Rate coefficient']))
            fig.add_trace(go.Histogram(
                histfunc="count",
                x=df['Rate coefficient'],
                nbinsx=nbinsx,
                autobinx=False,
                name=f'Gen {idx}',
                bingroup=1))
        # Overlay both histograms
        fig.update_layout(barmode='overlay',
                          xaxis={'title': 'Rate coefficient',
                                 'tickformat': '.2e'},
                          yaxis_title_text='Count of elements')
        # Reduce opacity to see both histograms
        fig.update_traces(opacity=0.75)
        return ({'display': 'block'},
                fig,
                f"""Distribution of the rate\
                coefficient from {From} to \
                {To} in generations {selected_gen}""",
                f'Average: {avrg}',
                f'Number of elements: {nel}')

    PORT = '8000'
    ADDRESS = '127.0.0.1'
    app.run(port=PORT, host=ADDRESS)
