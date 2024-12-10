from dash import Dash, html, dcc, callback, Output, Input
import sys
import os
from game.readers.mess_input import MessInputReader
from game.database.game_db import Game_db
from game.user_input import check_input
from game.gui.sopanalyser import SOPAnalyser
from game.parameters import SOP


def main() -> None:
    if len(sys.argv) != 1:
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
        html.Div(className='row', id='core_layout')
    ]

    # Add controls to build the interaction
    @callback(
        Output(component_id='core_layout', component_property='children'),
        Input(component_id='rb_start', component_property='value')
    )
    def update_core_layout(data_type):
        if data_type == 'SOP':
            app_core = SOPAnalyser(sop_db)
        elif data_type == 'KIN':
            app_core = KinAnalyser(kin_db)
        elif data_type == 'SIM':
            app_core = SimAnalyser(sim_db)
        return app_core.layout()

    PORT = '8000'
    ADDRESS = '127.0.0.1'
    if __name__ == '__main__':
        app.run(port=PORT, host=ADDRESS)
        