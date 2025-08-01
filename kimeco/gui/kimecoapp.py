from dash import Dash, html, dcc, Output, Input, State
from dash.exceptions import PreventUpdate
import sys
import os
from kimeco.readers.mess_input import MessInputReader
from kimeco.user_input import check_input
from kimeco.scoring_f.weighteddif import WeightedDif
from kimeco.parameters import SOP
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.gui.sopsection import SOPSection
from kimeco.gui.kinsection import KINSection
from kimeco.gui.simsection import SIMSection
from kimeco.gui.corsection import CORSection
from kimeco.Perturbators.perturbator import Perturbator
from kimeco import kimeco_path
from logging import Logger
from kimeco.logger_config import setup_logger


class KimecoApp:
    def __init__(self,
                 input_file: str,
                 klog: Logger) -> None:

        self.klog: Logger = klog
        self.settings: dict = check_input(input_file=input_file,
                                          klog=klog)
        mr = MessInputReader(settings=self.settings)
        self.init_SOP: SOP
        self.input_tpl: list[str]
        (self.init_SOP, self.input_tpl) = mr.read()
        if not os.path.isdir(self.settings['project_name']):
            self.klog.info('''
    KIMECO graphical interface can only analyse the data
    of existing database created by a previous KIMECO run.
    Run KIMECO with project_name: {},
    and then analyse the results.'''.format(
                self.settings['project_name']))
            sys.exit()
        os.chdir(self.settings['project_name'])
        self.loc: str = os.getcwd()
        self.sop_db = SOP_DB(sop=self.init_SOP,
                             name='KMO_DB_SOP')
        self.sop_tot_g: int = len(self.sop_db.tables)
        self.kin_db = KIN_DB(sop=self.init_SOP,
                             name='KMO_DB_KIN')
        self.kin_tot_g: int = len(self.kin_db.tables)
        self.sim_db = SIM_DB(sop=self.init_SOP,
                             name='KMO_DB_SIM')
        self.sim_tot_g: int = len(self.sim_db.tables)
        if os.path.isfile('SA_DB_SOP.db'):
            self.sa_db = SOP_DB(sop=self.init_SOP,
                                name='SA_DB_SOP')

        # Define which scoring function to use
        if self.settings['scoring_func'].casefold() == 'weighteddif':
            self.sf = WeightedDif(settings=self.settings)
        else:
            # Default scoring function
            self.sf = WeightedDif(settings=self.settings)

        self.species: list[str] = self.init_SOP.species

        self.og_names = {v: k for k, v in self.settings['ct_names'].items()}
        for ct_name, name in self.og_names.items():
            if name not in self.init_SOP.wells_names:
                for bimol in self.init_SOP.bimolecular:
                    if name in bimol.frag_names:
                        self.og_names[ct_name] = bimol.name
        if os.path.isfile('SA_DB_SOP.db'):
            self.init_vals = self.sa_db.get_table(table='SA')[0]
        else:
            self.init_vals = self.sop_db.get_table(table='G0000')[0]

        self.pert: Perturbator = Perturbator(
            settings=self.settings,
            initial_SOP=self.init_SOP,
            klog=self.klog
            )
        with open(self.loc + '/goat.txt', 'r') as f:
            self.goats = f.readlines()
        # Initialize app
        self.app = Dash(
            assets_url_path=f"{kimeco_path}/gui/assets")
        self.create_layout()
        self.register_callbacks()

    def create_layout(self):
        self.app.layout = [
            html.Div(className='row', children=[
                html.H1('KiMecO Analyser'),
                html.H2('Data to analyse:'),
                dcc.RadioItems(options=[
                    {'label': 'Set of parameters', 'value': 'SOP'},
                    {'label': 'Rate coefficients', 'value': 'KIN'},
                    {'label': 'Concentration profiles', 'value': 'SIM'},
                    {'label': 'Correlation plots', 'value': 'COR'}
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
                    html.H4('Number of generations.'),
                    dcc.Input(
                        min=1,
                        max=self.sop_tot_g,
                        type="number",
                        value=1,
                        placeholder="Number of generations",
                        id='gen_num'),
                    # Select from which generation
                    html.H4('Slide to select generations.'),
                    dcc.RangeSlider(
                        id='gen range slider',
                        min=0,
                        max=self.sop_tot_g-1,
                        step=1,
                        pushable=True,
                        value=[0],
                        marks={
                            0: 'Generation 0',
                            self.sop_tot_g-1:
                                f'Generation {self.sop_tot_g-1}'},
                        tooltip={
                            "always_visible": False,
                            "template": "Generation {value}"})
                    ]),
            SOPSection(self).layout,
            KINSection(self).layout,
            SIMSection(self).layout,
            CORSection(self).layout]

    def register_callbacks(self):
        # GENERATION CONTROL
        @self.app.callback(
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
            while (len(selected_gen) != gen_num and
                   len(selected_gen) < self.sop_tot_g and
                   len(selected_gen) >= 1):

                if len(selected_gen) < gen_num:
                    for i in range(self.sop_tot_g):
                        if i not in selected_gen:
                            selected_gen.append(i)
                            break
                else:
                    selected_gen.pop(-1)
            return selected_gen

        # Select which division to show: sop, kin or sim
        @self.app.callback(
            Output(component_id='sop', component_property='style'),
            Output(component_id='kin', component_property='style'),
            Output(component_id='sim', component_property='style'),
            Output(component_id='cor', component_property='style'),
            Input(component_id='rb_start', component_property='value')
        )
        def update_layout(data_type):
            if data_type == 'SOP':
                sop_style = {'display': 'block'}
                kin_style = {'display': 'none'}
                sim_style = {'display': 'none'}
                cor_style = {'display': 'none'}
            elif data_type == 'KIN':
                sop_style = {'display': 'none'}
                kin_style = {'display': 'block'}
                sim_style = {'display': 'none'}
                cor_style = {'display': 'none'}
            elif data_type == 'SIM':
                sop_style = {'display': 'none'}
                kin_style = {'display': 'none'}
                sim_style = {'display': 'block'}
                cor_style = {'display': 'none'}
            elif data_type == 'COR':
                sop_style = {'display': 'none'}
                kin_style = {'display': 'none'}
                sim_style = {'display': 'none'}
                cor_style = {'display': 'block'}
            else:
                raise PreventUpdate
            return sop_style, kin_style, sim_style, cor_style

    def run(self):
        PORT = '8000'
        ADDRESS = '127.0.0.1'
        self.app.run(port=PORT, host=ADDRESS)


def main() -> None:
    klog: Logger = setup_logger(name='KiMecO_GUI.log')
    if len(sys.argv) != 2:
        print("""
    KIMECO needs various parameters to be set in a JSON input file.
    This JSON input file shopuld be supplied as the first and only
    argument.

    Usage:  kmoui path/to/JSON/input/file.json
    """)
        try:
            input_file: str = sys.argv[1]
        except IndexError as e:
            klog.debug(e)
            klog.info('To use KIMECO, supply the input file as argument.')
        sys.exit()
    input_file = sys.argv[1]
    kmo_app = KimecoApp(input_file, klog=klog)
    kmo_app.run()


if __name__ == "__main__":
    main()
