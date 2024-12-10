from dash import Dash, html, dcc, callback, Output, Input, State
import plotly.express as px
import sys
import os
from game.readers.mess_input import MessInputReader
from game.database.game_db import Game_db
from game.user_input import check_input
from game.parameters import SOP
import pandas as pd
from plotly.graph_objs._figure import Figure


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
    sop_tot_g = len(sop_db._tables)
    kin_db = Game_db(name='GAME_DB_KIN')
    sim_db = Game_db(name='GAME_DB_SIM')

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
        ##############################
        # SOP section
        html.Div(
            className='row', id='sop',
            style={'display': 'none'},
            children=[
                html.H3('Select Which type of parameter to plot:'),
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
                                         id='param_selection')
                            ]),
                dcc.RadioItems(
                    options=[
                        {'label': 'One generation at a time', 'value': 0},
                        {'label': 'Multiple generation at a time', 'value': 1}
                    ],
                    id='sop_gen_mode'),
                # Generation SLIDER
                html.Div(
                    className='row',
                    id='sop_gen_slider',
                    children=[
                        html.H3(
                            'Select which generation to plot information from:'),
                        # Select from which generation
                        dcc.Slider(
                            id='one gen sop slider',
                            min=0,
                            max=sop_tot_g-1,
                            step=1,
                            value=0,
                            marks={0: 'Generation 0',
                                   sop_tot_g-1: f'Generation {sop_tot_g-1}'},
                            tooltip={
                                    "always_visible": False,
                                    "template": "Generation {value}"})
                    ],
                    style={'display': 'none'}
                        ),
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
                    id='sop_one_gen_plot',
                    style={'display': 'none'},
                    children=[
                        html.H3(children={}, id='title_dist'),
                        html.H5(children={}, id='sop_single_gen_avrg'),
                        html.H5(children={}, id='sop_single_gen_elem'),
                        dcc.Graph(figure={}, id='param_dist')
                    ])]),
        html.Div(className='row', id='kin', style={'display': 'none'}),
        html.Div(className='row', id='sim', style={'display': 'none'})
    ]

    # Add controls to build the interaction
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
        return sop_style, kin_style, sim_style

    # SOP interactions
    # Show generation slider if one generation at a time
    @callback(
        Output(component_id='sop_gen_slider', component_property='style'),
        Input(component_id='sop_gen_mode', component_property='value')
    )
    def sop_gen_sliders_appears(multi_gen):
        if multi_gen == 0:
            style = {'display': 'block'}
        else:
            style = {'display': 'none'}
        return style

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
        Input(component_id='param_selection', component_property='value'),
        Input(component_id='sop_gen_mode', component_property='value')
    )
    def show_sop_one_gen_plot_button(selected_param, gen_mode):
        if selected_param in init_SOP.parameters_names and gen_mode == 0:
            return {'display': 'block'}
        else:
            return {'display': 'none'}

    # Plot the distribution of the requested parameter
    @callback(
        Output(component_id='sop_one_gen_plot', component_property='style'),
        Output(component_id='param_dist', component_property='figure'),
        Output(component_id='title_dist', component_property='children'),
        Output(component_id='sop_single_gen_avrg', component_property='children'),
        Output(component_id='sop_single_gen_elem', component_property='children'),
        Input(component_id='show_sop_plot_button', component_property='n_clicks'),
        State(component_id='param_selection', component_property='value'),
        State(component_id='one gen sop slider', component_property='value')
    )
    def update_figure(clic, param, gen):
        rows = sop_db.get_table(table=f'G{gen}')
        names = ['sop_id']
        for nm in init_SOP.parameters_names:
            names.append(nm)
        df = pd.DataFrame(data=rows, columns=names)
        fig: Figure = px.histogram(df, x=param, nbins=20)
        return ({'display': 'block'},
                fig,
                f'Distribution of {param} in generation {gen}',
                f'Average: {df[param].mean()}',
                f'Number of elements: {len(df[param])}')

    PORT = '8000'
    ADDRESS = '127.0.0.1'
    app.run(port=PORT, host=ADDRESS)
