
from typing import Any
import os
import glob
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element, ElementStatus
from kimeco.scoring_f.scoring import Scoring
from kimeco.templates.sim_helper import sim_helper
import logging
from kimeco.logger_config import setup_logger


# Call the setup function to configure logging
setup_logger()
glog = logging.getLogger()


class CoreRun:
    def __init__(self,
                 elements: list[Element],
                 settings: dict[str, Any],
                 rc_tpl: list[str],
                 loc: str,
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 pert: Perturbator,
                 previous_el: dict[int, Element] = {},
                 name: str = 'core') -> None:

        self.elements: list[Element] = elements
        self.settings: dict[str, Any] = settings
        self.previous_el: dict[int, Element] = previous_el
        self.pert: Perturbator = pert
        self.name: str = name
        # List of species names used by cantera
        self.sc_species: list[str] = self.settings['score_sp']
        # Rate coefficients template
        self.rc_tpl: list[str] = rc_tpl
        self.loc: str = loc
        self.sf: Scoring = sf
        self.sim_hlpers = [
            [] for i in range(self.settings['max_helpers'])
            ]

        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.create_tables()
        self.qs = QueueingSystem(
            max_jobs=self.settings['max_jobs'],
            max_cpu=self.settings['max_cpu'],
            max_mem=self.settings['max_mem'],
            cpu_kin=self.settings['cpu_kin'],
            mem_kin=self.settings['mem_kin'],
            cpu_sim=self.settings['cpu_sim'],
            mem_sim=self.settings['mem_sim'],
            nkin=len(self.elements),
            nsim=len(self.elements) *
            len(self.settings['rc_temp']) *
            len(self.settings['rc_pres']),
            nhlp=self.settings['max_helpers']
            )
        self.name = name
        self.clean_files()

    def clean_files(self):
        for el in self.elements:
            if el.status != ElementStatus.DONE:
                for file in glob.glob(
                    f"{self.name}{el.name}*"
                ):
                    os.remove(file)

    def create_tables(self) -> None:
        """Create the tables in all databases
        """
        # Create table for gen in SOP, KIN and SIM
        # SOP
        tbl_name: str = self.name
        if tbl_name not in self.sop_db.tables:
            self.sop_db.create_table(
                name=tbl_name
                )
        # KIN
        if tbl_name not in self.kin_db.tables:
            self.kin_db.create_table(
                name=tbl_name
                )
        # SIM
        if tbl_name not in self.sim_db.tables:
            self.sim_db.create_table(
                name=tbl_name
                )

    @property
    def finished(self):
        return all([el.status == ElementStatus.DONE
                    for el in self.elements])

    def run(self) -> None:
        """Run a generation until all of its elements are scored.
        """
        while not self.finished:
            for el in self.elements:
                # Safeguard
                if self.elements[el.id].id != el.id:
                    raise IndexError('Incorrect ordering of the elements.')
                if el.status == ElementStatus.DONE:
                    continue
                if el.status == ElementStatus.RESET:
                    self.reset_element(el)
                    continue
                if el.status == ElementStatus.SOP:
                    self.calculate_rate_coefficients(el)
                elif el.status == ElementStatus.KIN:
                    self.run_simulation(el)
                elif el.status == ElementStatus.SIM:
                    self.recover_simulation_data(el)
                elif el.status == ElementStatus.SCORING:
                    self.calc_score(el)
                if el.status == ElementStatus.TO_SAVE:
                    self.finalize_element(el)
            self.sop_db.batch_upsert()
            self.kin_db.batch_upsert()
            self.check_helpers_status()
            self.collect_sim_profiles()
            self.qs.run()

    def reset_element(self, el: Element) -> None:
        """Reset a failed element."""
        rst: int = el.reset
        self.elements[el.id] = Element(
            sop=self.pert.perturb(sop=self.previous_el[el.id].sop),
            id=el.id
            )
        for file in glob.glob(f"{self.name}{el.name}*"):
            os.remove(file)
        self.elements[el.id].reset = rst + 1

    def calculate_rate_coefficients(self, el: Element) -> None:
        """Calculate rate coefficients for an element."""
        el.rateCoef = RateCo(
            sop=el.sop,
            settings=self.settings,
            software_tpl=self.rc_tpl,
            id=el.id,
            name=f'{self.name}{el.name}',
            loc=f'{self.loc}/{self.name}',
            q_sys=self.qs,
            db=self.kin_db
        )
        el.rateCoef.set_status(table=self.name)
        if el.rateCoef.status == JobStatus.NOT_IN_QUEUE:
            el.rateCoef.q_up()
        elif el.rateCoef.status == JobStatus.FINISHED:
            el.save_kin(db=self.kin_db, table=self.name)

    def run_simulation(self,
                       el: Element) -> None:
        """Run the simulation for an element."""
        el.sim = SIM(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            db=self.sim_db,
            gen_name=self.name,
            sc_species=self.sc_species,
            species=self.elements[0].sop.species,
            loc=f'{self.loc}/{self.name}',
            q_sys=self.qs,
            set=self.settings
        )
        el.sim.q_up()
        el.status = ElementStatus.SIM

    def recover_simulation_data(self,
                                el: Element) -> None:
        """Recover simulation data for an element."""
        for sim_idx, prof in enumerate(el.sim.profiles):
            sim_id: int = el.id * len(el.sim.simulations) + sim_idx
            # Change status from RUNNING to FINISHED (may have failed)
            el.sim.set_status(sim_idx)
            # Check if failed
            if el.sim.status[sim_idx] == JobStatus.FINISHED:
                self.qs.pickUp(id=sim_id,
                               jtype='sim')
                el.sim.set_status(sim_idx)
            # If successful, do the request
            if el.sim.status[sim_idx] == JobStatus.PICKED_UP or\
               el.sim.status[sim_idx] == JobStatus.NOT_IN_QUEUE:
                if prof is None:
                    el.request_sim_profiles(db=self.sim_db, table=self.name)
                    break
            # Reset Element if simulation had an error
            elif el.sim.status[sim_idx] == JobStatus.FAILED:
                el.status = ElementStatus.RESET

    def finalize_element(self,
                         el: Element) -> None:
        """Make sure element is saved before changing status."""
        if self.sop_db.entry_exist(table=self.name,
                                   id=el.id):
            el.status = ElementStatus.DONE
        else:
            el.prepare_upsert(db=self.sop_db, table=self.name)

    def collect_sim_profiles(self):
        """Batch recovery of the concentration profiles to avoid
        multiple db transactions.
        """
        if len(self.sim_db._select) == 0:
            return
        nsim: int = len(self.settings['rc_pres']) *\
            len(self.settings['rc_temp'])
        collected: list[int] = []
        to_collect = self.sim_db._select[self.name]
        collecting: dict[int, list[list[Any]]] = self.sim_db.batch_select()
        for sim_id, db_data in collecting[self.name].items():
            el: Element = self.elements[sim_id // nsim]
            sim: int = sim_id % nsim
            # number of timesteps
            nsteps = len(self.settings['exp_profiles'][sim][0])
            # Happens because of data concurrency
            if len(db_data) != nsteps:
                continue
            # The data are correct, free the queuing system
            el.sim.profiles[sim] = db_data

            # Scoring needs all the profiles
            if all([prof is not None for prof in el.sim.profiles]):
                el.status = ElementStatus.SCORING
            collected.append(sim_id)
        if collected == to_collect:
            return
        hlp_idx = -1
        # Look if helpers are available
        for idx, hlp in enumerate(self.sim_hlpers):
            if len(hlp) == 0:
                hlp_idx = idx
                break
        # Don't create helpers if none available
        if hlp_idx == -1:
            return
        # Create helpers if needed
        need_helper = [
            i for i in to_collect
            if i not in collected
        ]

        filenames = []
        # Avoid asking multiple helpers to do the same
        assigned_ids = set()  # Set to track already assigned sim_ids

        # Collect all sim_ids that are already assigned to helpers
        for hlp in self.sim_hlpers:
            assigned_ids.update(hlp)

        # Filter need_helper to remove any sim_ids that are already assigned
        for sim_id in need_helper:
            el: Element = self.elements[sim_id // nsim]
            sim: int = sim_id % nsim
            flnm: str = \
                f'{self.loc}/{self.name}/{self.name}{el.name}S{sim:02d}.json'
            # Happens because of long write times
            if os.path.isfile(f'{flnm}'):
                if len(self.sim_hlpers[hlp_idx]) < 30:
                    if sim_id not in assigned_ids:
                        self.sim_hlpers[hlp_idx].append(sim_id)
                        filenames.append(f'{flnm}')
                else:
                    break
            else:
                continue
        if len(self.sim_hlpers[hlp_idx]) == 0:
            return

        self.submit_helper(hlp_idx=hlp_idx,
                           filenames=filenames)

    def submit_helper(self,
                      hlp_idx: int,
                      filenames: list[str]) -> None:
        hlp_name: str = f'hlp_{hlp_idx}'
        hlp_job: str = sim_helper.format(
            db=self.sim_db,
            hlp_idx=hlp_idx,
            filenames=filenames,
            table=self.name
            )
        with open(f'{self.loc}/{self.name}/{hlp_name}.py', 'w') as f:
            f.write(hlp_job)
        self.qs.add_to_q(
                 name=hlp_name,
                 idx=hlp_idx,
                 location=f'{self.loc}/{self.name}',
                 jtype='hlp',
                 ressources=(1, 300)
                 )

    def check_helpers_status(self) -> None:
        """Management of helpers status.
        """
        nsim: int = len(self.settings['rc_pres']) *\
            len(self.settings['rc_temp'])
        for i in range(len(self.sim_hlpers)):
            if self.qs.status(i, 'hlp') == JobStatus.FINISHED:
                self.qs.pickUp(id=i,
                               jtype='hlp')
            if self.qs.status(i, 'hlp') == JobStatus.FAILED:
                glog.warning(f'Helper {i} failed to collect sim profiles.')
                glog.warning('Corresponding sim_ids are reset')
                for sim_id in self.sim_hlpers[i]:
                    el: Element = self.elements[sim_id // nsim]
                    el.status = ElementStatus.RESET
                self.sim_hlpers[i] = []
            elif self.qs.status(i, 'hlp') == JobStatus.NOT_IN_QUEUE:
                self.sim_hlpers[i] = []

    def calc_score(self,
                   el: Element) -> None:
        """Calculate the score of the element
        using the user requested function.
        If the elif statement for a new scoring function
        is missing, also add the chosen string to
        the implemented_sf list in default_settings.py.

        Args:
            settings (dict[str, Any]): User input + default settings
        """
        try:
            scores = self.sf.score(sim=el.sim)
            for idx, k in enumerate(el.sop.scores):
                el.sop.scores[k] = scores[idx]
            el.status = ElementStatus.TO_SAVE
        except IndexError as e:
            glog.debug(e)
            # Occurs when a simulation didn't work so profiles were not saved
            el.status = ElementStatus.RESET
            glog.info(f'Resetting element {el.id}: error during scoring.')

    @property
    def best_score(self):
        return min([el.score for el in self.elements])
