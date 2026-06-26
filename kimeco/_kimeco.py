import os
import time
from typing import Any
import shutil
from kimeco.goat import GOATs
from kimeco.readers.mess_input import MessInputReader
from kimeco.parameters import SOP
import logging
from kimeco.logger_config import create_logger, KMOLogger
from kimeco.user_input import KMOInput
from kimeco.kinmec import KiMec
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.sensitivity.linear import Linear
from kimeco.model import Model
from kimeco.enums import Optimizers, RestartType
from kimeco.optimizers.GeneticAlgo.exponential import Exponential
from kimeco.optimizers.GeneticAlgo.tournament import Tournament
from kimeco.optimizers.NelderMead.nelder_mead import NelderMead
from kimeco.optimizers.NelderMead.nelder_mead_swarm import NelderMeadSwarm
from kimeco.writers.mess import MessWriter


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
        # Create logger with level from settings (after raw_input is parsed)
        # Will be set to proper level after settings are loaded
        self.klog: KMOLogger = create_logger(f'{name}.log', level=logging.INFO)
        if sim_job:
            self.klog.setLevel(logging.ERROR)
        self.raw_input = KMOInput(
            input_file=input_file,
            init_loc=init_loc,
            klog=self.klog)
        self.settings: dict[str, Any] = self.raw_input.full_run_settings()
        # Postprocessing simulations replay pp_experiments through the
        # standard pipeline. When the (sub)process runs in postprocess mode
        # the experiment list must follow the pp conditions; the rate grid
        # follows automatically through settings['postprocess'].
        if self.settings.get('postprocess') and \
                self.settings.get('pp_experiments'):
            self.settings['experiments'] = self.settings['pp_experiments']
            self.settings['n_exp'] = len(self.settings['pp_experiments'])
        if not sim_job:
            self.klog.setLevel(self.settings['log_level'])
        self.klog.info(f"{'Input reading...':<65}{'PASSED':>15}")
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

        self.mech.add_SOP(self.init_SOP)
        self.first_sensi: bool = len(self.settings['active_p']) == 0

    def set_initial_sop(self,
                        postprocess=False) -> None:
        """Create the initial SOP with associated template
        """
        mr = MessInputReader(
            settings=self.settings,
            mechanism_species=[
                sp.name if hasattr(sp, "name") else str(sp)
                for sp in self.mech.species
            ],
            klog=self.klog,
            postprocess=postprocess)
        (self.init_SOP, self.input_tpls) = mr.read()
        if mr._trigger_stop:
            raise ValueError(
                "Input file reading failed due to missing species in the "
                "mechanism file. Check the log for details."
            )

    def initialize_workdir(self) -> None:
        """Create and access the working directory
        """
        if not os.path.isdir(self.settings['workdir']):
            os.mkdir(self.settings['workdir'])
        os.chdir(self.settings['workdir'])

    def copy_necessary_files(self) -> None:
        """Copy files necessary for MESS calculation"""
        for idx, input_tpl_lines in enumerate(self.input_tpls):
            with open(f'mess_tpl_PES{idx:02d}', 'w') as f:
                f.writelines(input_tpl_lines)

        for file in self.init_SOP.files2copy:
            shutil.copy(
                f'{self.init_loc}/{file}',
                f'{self.settings["workdir"]}/{file}')

    def initialize_databases(self) -> None:
        """Create the three databases used by KiMecO
        """
        start_time: float = time.time()
        self.sop_db = SOP_DB(sop=self.init_SOP,
                             name='KMO_DB_SOP',
                             threads=self.settings['threads'],
                             path=self.settings['workdir'],
                             klog=self.klog)
        sop_db_time: float = time.time() - start_time
        msg = 'SOP_DB initialized:'
        self.klog.info(f"{msg:<65}{sop_db_time:>15.1f}")
        self.kin_db = KIN_DB(sop=self.init_SOP,
                             name='KMO_DB_KIN',
                             threads=self.settings['threads'],
                             path=self.settings['workdir'])
        kin_db_time: float = time.time() - start_time - sop_db_time
        msg = 'KIN_DB initialized:'
        self.klog.info(f"{msg:<65}{kin_db_time:>15.1f}")
        self.sim_db = SIM_DB(
            name='KMO_DB_SIM',
            threads=self.settings['threads'],
            path=self.settings['workdir'])
        sim_db_time: float = (
            time.time() - start_time - sop_db_time - kin_db_time)
        msg = 'SIM_DB initialized:'
        self.klog.info(f"{msg:<65}{sim_db_time:>15.1f}")

    def set_scoring_function(self) -> None:
        """Define which scoring function to use"""
        # if self.settings['scoring_func'].casefold() == 'weighteddif':
        #     self.sf = Scoring(settings=self.settings, initial_SOP=self.init_SOP)
        # else:
        #     # Default scoring function
        self.sf = Scoring(settings=self.settings, initial_SOP=self.init_SOP)
        # self.klog.info(f"{'Scoring function:':<65}{self.sf.name:>15}")

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
        or run a first densitivity analysis.
        """
        # User friendly for jupyter notebook use
        Linear.reset()
        self.sensitivity = Linear(
            models=[Model(
                sop=self.init_SOP,
                id=0)],
            settings=self.settings,
            rc_tpls=self.input_tpls,
            sf=self.sf,
            pert=self.pert,
            klog=self.klog)
        if not self.sensitivity.models_from_db:
            self.klog.info(f"{'Running sensitivity analysis':<65}")
        else:
            self.klog.info(f"{'SA read from DB':<65}")
        self.sensitivity.run()  # Only actually run if necessary
        self.settings['active_p'] = self.sensitivity.selected
        self.sf.set_active_p(self.settings['active_p'])
        self.f_mdl: Model = self.sensitivity.models[0]
        if not self.sensitivity.models_from_db or \
            (self.settings['restart'] == RestartType.RESCORE and
             self.sensitivity.models_from_db):
            self.sensitivity.save_initial_model(
                sop_db=self.sop_db,
                kin_db=self.kin_db,
                sim_db=self.sim_db
            )

        msg = f"{'Parameters selected for perturbation:':<80}"
        msg += '\n'
        msg += "{}".format(self.settings['active_p']).replace("'", '"')
        self.klog.info(msg)

        # # Reinitialize the perturbator once the list of parameters to perturb
        # has been reduced
        self.pert: Perturbator = Perturbator(
            settings=self.settings,
            initial_SOP=self.init_SOP,
            klog=self.klog
            )
        # self.klog.info(
        #     f"{'Selected parameters transmitted to perturbator':<80}")

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
                    input_tpls=self.input_tpls,
                    sop_db=self.sop_db,
                    kin_db=self.kin_db,
                    sim_db=self.sim_db,
                    f_mdl=self.f_mdl,
                    klog=self.klog)
            elif self.settings['ga_type'].casefold() == 'exp':
                self.optimizer = Exponential(
                    settings=self.settings,
                    sf=self.sf,
                    pert=self.pert,
                    input_tpls=self.input_tpls,
                    sop_db=self.sop_db,
                    kin_db=self.kin_db,
                    sim_db=self.sim_db,
                    f_mdl=self.f_mdl,
                    klog=self.klog)
            else:
                raise TypeError('Unknown genetic algorythm requested')
        elif self.settings['optimizer'] == Optimizers.NM:
            self.optimizer = NelderMead(
                    settings=self.settings,
                    sf=self.sf,
                    pert=self.pert,
                    input_tpls=self.input_tpls,
                    sop_db=self.sop_db,
                    kin_db=self.kin_db,
                    sim_db=self.sim_db,
                    f_mdl=self.f_mdl,
                    klog=self.klog)
        else:
            raise NotImplementedError('Unknown optimizer requested')
        self.klog.info(f"{'OPTIMIZER:':<65}{self.optimizer.name}")

    def get_ensemble(self, name: str) -> list[Model]:
        """
        Resolve an ensemble name to a list of Models.

        Supported formats:
        - 'Gdddd' e.g., 'G0001': GA generation dddd
        - 'GT-1': last GOATs generation
        - 'GTxxxx': specific GOATs generation
        """
        name = name.strip()
        models: list[Model] = []
        if name.startswith('G') and len(name) == 5 and name[1:].isdigit():
            gen = int(name[1:])
            if gen != 1:
                raise NotImplementedError("Only generation 1 is supported")
                # TODO: Add previous mdl in SOP_db to know all mdls
                #  of a generation, and not only the new ones.
            table: str = f'G{gen:04d}'
            f_mdl_row = self.sop_db.get_table(table=table)[0]
            f_mdl = Model(
                sop=SOP.from_db_row(
                    sop_tpl=self.init_SOP,
                    row=f_mdl_row[1:]),
                id=0,
                gen=0)
            self.sf.fscore(mdl=f_mdl)
            models.append(f_mdl)
            if self.sop_db.table_exists(table):
                rows = self.sop_db.get_table(table=table)
                for row in rows:
                    sop: SOP = SOP.from_db_row(
                        sop_tpl=self.init_SOP,
                        row=row[1:])
                    models.append(
                        Model(
                            sop=sop,
                            id=row[0],
                            gen=gen,
                        )
                    )
        elif name.startswith('GT'):
            # GOATs ensemble resolution from optimizer.goats
            if hasattr(self.optimizer, 'goats'):
                goats: GOATs = self.optimizer.goats
                # 'GT-1' means last generation
                if name == 'GT-1':
                    models = goats.get_goat_for_gen(-1)
                else:
                    # 'GTxxxx' means specific generation
                    gen = int(name[2:])
                    models = goats.get_goat_for_gen(gen)
            else:
                self.klog.warning(
                    f"No GOATs object for ensemble '{name}'.")
        if not models:
            self.klog.warning(f"Ensemble '{name}' not found or empty.")
        return models

    def run_nms(self, models: list[Model]) -> None:
        """Run NelderMeadSwarm starting from provided models."""
        if not models:
            return
        swarm = NelderMeadSwarm(
            models=models,
            settings=self.settings,
            sf=self.sf,
            sop_db=self.sop_db,
            sim_db=self.sim_db,
            kin_db=self.kin_db,
            input_tpls=self.input_tpls,
            klog=self.klog,
            pert=self.pert,
        )
        bests = swarm.run()
        self.klog.info(
            f"NMS completed: {len(bests)} NM finished successfully.")
        best_mdl: Model = bests[
            bests.index(min(bests, key=lambda mdl: mdl.score))]
        msg = f"{'Best model after NMS:':<65}"
        msg += "\n" + f"ID: {best_mdl.id}, Score: {best_mdl.score:.4f}"
        msg += "\nParameters:\n"
        for k, v in best_mdl.sop.parameters_names.items():
            msg += f"  {k}: {v}\n"
        self.klog.info(msg)
        mw = MessWriter(
            SOP=best_mdl.sop,
            tpl=self.input_tpls)
        mw.write(
            loc=self.settings['workdir'],
            filename='best_after_nms.inp')

    def finalize(self) -> None:
        # Optionally run NMS after optimizer based on settings
        start_key = self.settings['NMS_start']
        if isinstance(start_key, str) and start_key.strip():
            ens = self.get_ensemble(start_key.strip())
            self.run_nms(ens)
