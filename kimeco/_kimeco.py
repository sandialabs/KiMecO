
import os
import shutil
import time
from typing import Any
from kimeco.readers.mess_input import MessInputReader
from kimeco.parameters import SOP
from logging import Logger, WARNING
from kimeco.logger_config import setup_logger
from kimeco.user_input import KMOInput
from kimeco.kinmec import KiMec
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.weighteddif import WeightedDif
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.sensitivity.linear import Linear
from kimeco.element import Element
from kimeco.enums import Optimizers, RestartType
from kimeco.optimizers.GeneticAlgo.exponential import Exponential
from kimeco.optimizers.GeneticAlgo.tournament import Tournament
from kimeco.optimizers.nelder_mead import NelderMead


class KiMecO:
    def __init__(self,
                 input_file: str,
                 init_loc: str = os.getcwd(),
                 name: str = 'KiMecO',
                 sim_job: bool = False) -> None:
        """Class containing utilities function

        Args:
            settings (dict[str, Any]): user input
        """
        self.init_loc: str = init_loc
        self.klog: Logger = setup_logger(f'{name}.log')
        if sim_job:
            self.klog.setLevel(WARNING)
        self.raw_input = KMOInput(
            input_file=input_file,
            init_loc=init_loc,
            klog=self.klog)
        self.settings: dict[str, Any] = self.raw_input.full_run_settings()
        if not sim_job:
            self.klog.setLevel(self.settings['log_level'])
        self.klog.info(f"{'Input reading...':<65}{'PASSED':>15}")
        mr = MessInputReader(settings=self.settings)
        self.init_SOP: SOP
        self.input_tpl: list[str]
        (self.init_SOP, self.input_tpl) = mr.read()
        self.init_SOP.set_uncertainties(settings=self.settings)
        self.first_sensi: bool = len(self.settings['to_perturb']) == 0

    def check_kinmech(self) -> None:
        kin_mech = KiMec(
            file=f"{self.init_loc}/{self.settings['ct_yaml']}",
            settings=self.settings,
            sop_tpl=self.init_SOP)
        kin_mech.check_species()

    def initialize_workdir(self) -> None:
        """Create and access the working directory
        """
        if not os.path.isdir(self.settings['workdir']):
            os.mkdir(self.settings['workdir'])
        os.chdir(self.settings['workdir'])

    def copy_necessary_files(self) -> None:
        """Copy files necessary for MESS calculation"""
        with open('mess_tpl', 'w') as f:
            f.writelines(self.input_tpl)

        for file in self.init_SOP.files2copy:
            shutil.copyfile(
                f'{self.init_loc}/{file}',
                f'{self.settings["workdir"]}/{file}')

    def initialize_databases(self) -> None:
        """Create the three databases used by KiMecO
        """
        start_time: float = time.time()
        self.sop_db = SOP_DB(sop=self.init_SOP,
                             name='KMO_DB_SOP',
                             thread=self.settings['thread'],
                             path=self.settings['workdir'])
        sop_db_time: float = time.time() - start_time
        msg = 'SOP_DB initialized:'
        self.klog.info(f"{msg:<65}{sop_db_time:>15.1f}")
        self.kin_db = KIN_DB(sop=self.init_SOP,
                             name='KMO_DB_KIN',
                             thread=self.settings['thread'],
                             path=self.settings['workdir'])
        kin_db_time: float = time.time() - start_time - sop_db_time
        msg = 'KIN_DB initialized:'
        self.klog.info(f"{msg:<65}{kin_db_time:>15.1f}")
        self.sim_db = SIM_DB(sop=self.init_SOP,
                             name='KMO_DB_SIM',
                             thread=self.settings['thread'],
                             path=self.settings['workdir'])
        sim_db_time: float = \
            time.time() - start_time - sop_db_time - kin_db_time
        msg = 'SIM_DB initialized:'
        self.klog.info(f"{msg:<65}{sim_db_time:>15.1f}")

    def set_scoring_function(self) -> None:
        """Define which scoring function to use"""
        if self.settings['scoring_func'].casefold() == 'weighteddif':
            self.sf = WeightedDif(settings=self.settings)
        else:
            # Default scoring function
            self.sf = WeightedDif(settings=self.settings)
        self.klog.info(f"{'Scoring function:':<65}{self.sf.name:>15}")

    def set_perturbator(self) -> None:
        """Initialize the perturbator"""
        self.pert: Perturbator = Perturbator(
            settings=self.settings,
            initial_SOP=self.init_SOP,
            klog=self.klog
            )
        self.pert.print_pert_parameters()

    def set_important_parameters(self) -> None:
        """Start with user specified parameters,
        or run a first densitivity analysis
        """
        self.sensitivity = Linear(
            elements=[Element(
                sop=self.init_SOP,
                id=0)],
            settings=self.settings,
            rc_tpl=self.input_tpl,
            sf=self.sf,
            pert=self.pert,
            klog=self.klog)
        if not self.sensitivity.elements_from_db:
            self.klog.info(f"{'Running sensitivity analysis':<65}")
        else:
            self.klog.info(f"{'SA read from DB':<65}")
        self.sensitivity.run()  # Only actually run if necessary
        self.settings['to_perturb'] = self.sensitivity.selected
        self.f_el: Element = self.sensitivity.elements[0]
        if not self.sensitivity.elements_from_db or \
            (self.settings['restart'] == RestartType.RESCORE and
             self.sensitivity.elements_from_db):
            self.sensitivity.save_initial_element(
                sop_db=self.sop_db,
                kin_db=self.kin_db,
                sim_db=self.sim_db
            )

        msg = f"{'Parameters selected for perturbation:':<80}"
        msg += '\n'
        msg += "{}".format(self.settings['to_perturb']).replace("'", '"')
        self.klog.info(msg)

        # Reinitialize the perturbator once the list of parameters to perturb
        # has been reduced
        self.pert: Perturbator = Perturbator(
            settings=self.settings,
            initial_SOP=self.init_SOP,
            klog=self.klog
            )
        self.klog.info(
            f"{'Selected parameters transmitted to perturbator':<80}")

    def set_optimizer(self) -> None:
        """Define the optimizer being used for this run

        Raises:
            TypeError: Unknown GA
            TypeError: Unknown optimizer
        """
        if self.settings['optimizer'] == Optimizers.GA:
            if self.settings['ga_type'].casefold() == 'tournament':
                self.optimizer = Tournament(
                    settings=self.settings,
                    sf=self.sf,
                    pert=self.pert,
                    input_tpl=self.input_tpl,
                    sop_db=self.sop_db,
                    kin_db=self.kin_db,
                    sim_db=self.sim_db,
                    f_el=self.f_el,
                    klog=self.klog)
            elif self.settings['ga_type'].casefold() == 'exp':
                self.optimizer = Exponential(
                    settings=self.settings,
                    sf=self.sf,
                    pert=self.pert,
                    input_tpl=self.input_tpl,
                    sop_db=self.sop_db,
                    kin_db=self.kin_db,
                    sim_db=self.sim_db,
                    f_el=self.f_el,
                    klog=self.klog)
            else:
                raise TypeError('Unknown genetic algorythm requested')
        elif self.settings['optimizer'] == Optimizers.NM:
            self.optimizer = NelderMead(
                    settings=self.settings,
                    sf=self.sf,
                    pert=self.pert,
                    input_tpl=self.input_tpl,
                    sop_db=self.sop_db,
                    kin_db=self.kin_db,
                    sim_db=self.sim_db,
                    f_el=self.f_el,
                    klog=self.klog)
        else:
            raise NotImplementedError('Unknown optimizer requested')
        self.klog.info(f"{'OPTIMIZER:':<65}{self.optimizer.name}")
