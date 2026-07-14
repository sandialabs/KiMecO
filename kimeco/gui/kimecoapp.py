import logging
from dash import Dash, html, dcc, Output, Input, State
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
from kimeco.database.sim_db import SIM_DB
from kimeco.gui.sopsection import SOPSection
from kimeco.gui.kinsection import KINSection
from kimeco.gui.simsection import SIMSection
from kimeco.gui.corsection import CORSection
from kimeco.gui.dbsection import DBSection
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
        ct_yaml_path = self.settings['ct_yaml']
        if not os.path.isabs(ct_yaml_path):
            ct_yaml_path = os.path.join(self.init_loc, ct_yaml_path)
        self.mech = KiMec(
            file=ct_yaml_path,
            settings=self.settings)
        self.init_SOP: SOP
        self.input_tpls: list[list[str]]
        self.set_initial_sop()
        self.init_SOP.set_uncertainties(settings=self.settings)

        self.species: list[str] = self.init_SOP.species

        # GOAT file will be handled by a GOATs instance after DB init
        # Initialize app
        self.app = Dash(
            assets_url_path=f"{kimeco_path}/gui/assets",
            suppress_callback_exceptions=True)

    def initialize_databases(self) -> None:
        super().initialize_databases()
        self.pp_sim_db: SIM_DB | None = None
        pp_sim_path = f"{self.settings['workdir']}/PP_DB_SIM.db"
        if os.path.isfile(pp_sim_path):
            self.pp_sim_db = SIM_DB(
                name='PP_DB_SIM',
                threads=self.settings['threads'],
                path=self.settings['workdir'],
                tbl_name=None)
        self.init_vals = self.sop_db.get_table(table='G0000')[0]
        # Construct GOATs object so GUI sections can request Model objects
        goat_file: str = f"{self.settings['workdir']}/goats.txt"
        # Always construct GOATs from the same goat.txt used previously
        self.goats = GOATs.from_file(
            filename=goat_file,
            sop_db=self.sop_db,
            kin_db=self.kin_db,
            sim_db=self.sim_db,
            sf=self.sf,
        )
        self.n_gen: int = len(self.goats)

    def create_layout(self) -> None:
        self.app.layout = [
            html.Div(className='row', children=[
                html.H1('KiMecO Analyser'),
                html.H2('Data to analyse:'),
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
            ############################
            #       SECTION TABS       #
            ############################
            dcc.Tabs(
                id='rb_start',
                value='SOP',
                children=[
                    dcc.Tab(
                        label='Set of parameters',
                        value='SOP',
                        children=[SOPSection(self).layout]),
                    dcc.Tab(
                        label='Rate coefficients',
                        value='KIN',
                        children=[KINSection(self).layout]),
                    dcc.Tab(
                        label='Concentration profiles',
                        value='SIM',
                        children=[SIMSection(self).layout]),
                    dcc.Tab(
                        label='Correlation plots',
                        value='COR',
                        children=[CORSection(self).layout]),
                    dcc.Tab(
                        label='Databases',
                        value='DB',
                        children=[DBSection(self).layout]),
                ])]

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

    def run(self):
        PORT = '8000'
        ADDRESS = '127.0.0.1'
        self.app.run(port=PORT, host=ADDRESS)


def _print_help() -> None:
    print(
        """
KiMecO UI (kmoui)
Launch the KiMecO web interface to analyze optimization results.

This command reads a JSON input file, initializes the KiMecO databases/work
context, and starts a Dash server for interactive exploration of SOP/KIN/SIM
and correlation views.

Usage:
  kmoui INPUT_JSON

Arguments:
  INPUT_JSON    Path to the KiMecO JSON configuration file.

Options:
  -h, --help    Show this help message and exit.
""".strip()
    )


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] in {'-h', '--help'}:
        _print_help()
        sys.exit(0)

    if len(sys.argv) != 2:
        _print_help()
        sys.exit(1)

    try:
        kmoui = KimecoApp(input_file=sys.argv[1])
    except IndexError as e:
        print(e)
        print('To use KiMecO UI, supply the input file as argument.')
        sys.exit(-1)
    kmoui.initialize_workdir()
    kmoui.copy_necessary_files()
    kmoui.set_scoring_function()
    kmoui.initialize_databases()
    kmoui.set_perturbator()
    kmoui.set_important_parameters()
    kmoui.create_layout()
    kmoui.register_callbacks()
    kmoui.run()


if __name__ == "__main__":
    main()
