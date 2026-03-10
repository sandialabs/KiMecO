import logging
from dash import Dash, html, dcc, Output, Input, State
from dash.exceptions import PreventUpdate
import sys
import os
from typing import Any
from kimeco._kimeco import KiMecO
from kimeco.kinmec import KiMec
from kimeco.logger_config import KMOLogger
from kimeco.logger_config import setup_logger
from kimeco.user_input import KMOInput
from kimeco.parameters import SOP
from kimeco.goat import GOATs
from kimeco.gui.sopsection import SOPSection
from kimeco.gui.kinsection import KINSection
from kimeco.gui.simsection import SIMSection
from kimeco.gui.corsection import CORSection
from kimeco import kimeco_path


class KimecoApp(KiMecO):
    def __init__(self,
                 input_file: str,
                 init_loc: str = os.getcwd(),
                 name: str = 'kmo_UI') -> None:
        """Class containing utilities function

        Args:
            settings (dict[str, Any]): user input
        """
        self.init_loc: str = init_loc
        self.klog: KMOLogger = setup_logger(f'{name}.log')
        self.klog.setLevel(logging.ERROR)
        self.raw_input = KMOInput(
            input_file=input_file,
            init_loc=init_loc,
            klog=self.klog)
        self.settings: dict[str, Any] = self.raw_input.full_run_settings()
        self.mech = KiMec(
            file=f"{self.init_loc}/{self.settings['ct_yaml']}",
            settings=self.settings,
            sop_tpl=self.init_SOP)
        self.init_SOP: SOP
        self.input_tpl: list[str]
        self.set_initial_sop()
        self.init_SOP.set_uncertainties(settings=self.settings)

        self.species: list[str] = self.init_SOP.species

        # GOAT file will be handled by a GOATs instance after DB init
        # Initialize app
        self.app = Dash(
            assets_url_path=f"{kimeco_path}/gui/assets")

    def initialize_databases(self) -> None:
        super().initialize_databases()
        self.init_vals = self.sop_db.get_table(table='G0000')[0]
        # Construct GOATs object so GUI sections can request Element objects
        goat_file: str = f"{self.settings['workdir']}/goats.txt"
        # Always construct GOATs from the same goat.txt used previously
        self.goats = GOATs.from_file(
            filename=goat_file,
            sop_db=self.sop_db,
            kin_db=self.kin_db,
            sim_db=self.sim_db,
        )
        self.n_gen: int = len(self.goats)

    def create_layout(self) -> None:
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
                        max=self.n_gen,
                        type="number",
                        value=1,
                        placeholder="Number of generations",
                        id='gen_num'),
                    # Select from which generation
                    html.H4('Slide to select generations.'),
                    dcc.RangeSlider(
                        id='gen range slider',
                        min=0,
                        max=self.n_gen-1,
                        step=1,
                        pushable=True,
                        value=[0],
                        marks={
                            0: 'Generation 0',
                            self.n_gen-1:
                                f'Generation {self.n_gen-1}'},
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
            Output(
                component_id='gen range slider', component_property='value'
            ),
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
                   len(selected_gen) < self.n_gen and
                   len(selected_gen) >= 1):

                if len(selected_gen) < gen_num:
                    for i in range(self.n_gen):
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
    # Call the setup function to configure logging
    if len(sys.argv) != 2:
        print("""
    KIMECO needs various parameters to be set in a JSON input file.
    This JSON input file should be supplied as the first and only
    argument.

    Usage:  kmo path/to/JSON/input/file.json
    """)
        sys.exit()
    try:
        kmoui = KimecoApp(input_file=sys.argv[1])
    except IndexError as e:
        print(e)
        print('To use KIMECO, supply the input file as argument.')
        sys.exit(-1)
    kmoui.initialize_workdir()
    kmoui.copy_necessary_files()
    kmoui.initialize_databases()
    kmoui.set_scoring_function()
    kmoui.set_perturbator()
    kmoui.set_important_parameters()
    kmoui.create_layout()
    kmoui.register_callbacks()
    kmoui.run()


if __name__ == "__main__":
    main()
