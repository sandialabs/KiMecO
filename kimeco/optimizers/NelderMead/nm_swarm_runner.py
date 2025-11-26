import time
import os
import glob
from numpy.typing import NDArray
from typing import Any
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.scoring_f.scoring import Scoring
from kimeco.enums import RestartType, ElementStatus
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.templates.sim_helper import sim_helper
from logging import Logger
import shutil
from enum import Enum


class ThreadStatus(Enum):
    IDLE = 'IDLE'
    BUSY = 'BUSY'


class NMSRunner:
    def __init__(self,
                 settings: dict[str, Any],
                 rc_tpl: list[str],
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 klog: Logger,
                 ) -> None:
        """Generation object manages the worflow of
        a given set of elements, going from creating them
        (perturbed SOPs) to calculating the rate constants
        and doing the cantera Simulation

        Args:
            sop (SOP): Initial set of parameters to be perturbed
            n (int): number of elements in the generation
            pert (Perturbator): Perturbator object used to perturb the SOP
                                of this generation
            set (dict): Settings.
            rc_tpl: Template for rate constant calculation.
            loc: Location. Absolute path of where the gen folder should be.
        """
        self.thread_status: dict[int, ThreadStatus] = {
            i: ThreadStatus.IDLE for i in range(self.settings['threads'])
        }
        self.klog: Logger = klog
        self.elements: list[Element] = []
        self.settings: dict[str, Any] = settings
        # List of species names used by cantera
        self.sc_species: list[str] = self.settings['score_sp']
        # Rate coefficients template
        self.rc_tpl: list[str] = rc_tpl
        self.loc: str = settings['workdir']
        self.swarm_loc: str = f"{self.loc}/nm_swarm"
        # Scoring function
        self.sf: Scoring = sf
        self.sim_hlpers = [
            [] for _ in range(self.settings['max_helpers'])
            ]
        self.elem_count: int = 0
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.timers: dict[Any, float] = {
            estat: 0.0 for estat in ElementStatus
            }
        self.timers['collecting_sim'] = 0.0
        self.pres: list[float] = settings["rc_pres"]
        self.temp: list[float] = settings["rc_temp"]

        self.qs = QueueingSystem(
            settings=self.settings,
            nel=self.settings['threads'],
            nhlp=self.settings['max_helpers'],
            klog=self.klog)
        # Contain the time when a sim_id was first queried
        self.requeue_timer = {}

        self.logger_tpl = '{message:<65}{number:>14.2f}'

    def clean_files(self,
                    el: Element) -> None:
        """Remove files from previous runs for an element."""
        name: str = f'NM{el.gen:04d}/'
        if el.status != ElementStatus.DONE:
            for file in glob.glob(
                f"{name}{el.name}*"
            ):
                os.remove(file)

    def add_element(self,
                    el: Element) -> None:
        """Add an element to the generation."""
        for thread in self.thread_status:
            if self.thread_status[thread] == ThreadStatus.IDLE:
                self.thread_status[thread] = ThreadStatus.BUSY
                el.thread_id = thread
                break
        self.elements.append(el)
        self.elem_count += 1
        self.create_tables(el)
        self.clean_files(el)
        name: str = f'NM{el.gen:04d}'
        # Create core directory
        core_dir: str = self.swarm_loc
        nm_dir: str = f'{core_dir}/{name}'
        os.makedirs(nm_dir + '/logs', exist_ok=True)
        for subfolder in range(el.id//50+1):
            os.makedirs(
                nm_dir + f'/{subfolder:02d}' + '/logs', exist_ok=True)
            # Copy files necessary for MESS calculation
            for file in el.sop.files2copy:
                shutil.copyfile(f'{self.loc}/{file}',
                                f'{nm_dir}/{subfolder:02d}/{file}')
        os.chdir(core_dir)
        if self.elem_count % 1000 == 0:
            self.sop_db.defragmentate()
            self.kin_db.defragmentate()
            self.sim_db.defragmentate()

    def create_tables(self,
                      el: Element) -> None:
        """Create the tables in all databases
        """
        # Create table for gen in SOP, KIN and SIM
        # SOP
        tbl_name: str = f'NM{el.gen:04d}'
        if tbl_name not in self.sop_db.tables:
            self.sop_db.create_new_table(
                name=tbl_name
                )
        # KIN
        if tbl_name not in self.kin_db.tables:
            self.kin_db.create_new_table(
                name=tbl_name
                )
        # SIM
        if tbl_name not in self.sim_db.tables:
            self.sim_db.create_new_table(
                name=tbl_name
                )

    def run(self,
            nm_el: Element) -> Element:
        """Run a generation until all of its elements are scored.
        """
        self.add_element(nm_el)
        while not nm_el.status == ElementStatus.DONE:
            for idx, el in enumerate(self.elements):
                # Safeguard
                if self.elements[idx].id != el.id:
                    raise IndexError(
                        'Incorrect ordering of the elements.')
                if el.status == ElementStatus.DONE:
                    continue
                if el.status == ElementStatus.RESET:
                    el.sop.scores = {
                        k: float('inf') for k in el.sop.scores}
                    self.klog.warning(
                        f'Vertice ({el.gen} {el.id}) failed.',
                        'Returned with a high score.')
                    el.status = ElementStatus.DONE
                    continue
                if el.status == ElementStatus.SOP:
                    self.calculate_rate_coefficients(el)
                elif el.status == ElementStatus.KIN:
                    self.run_simulation(el)
                elif el.status == ElementStatus.SIM:
                    self.recover_simulation_data(el)
                # Only accessed on restart if RestartType is RESCORE
                elif el.status == ElementStatus.RESCORE:
                    self.recalc_score(el)
                elif el.status == ElementStatus.SCORING:
                    self.calc_score(el)
                if el.status == ElementStatus.TO_SAVE:
                    self.finalize_element(el)
            self.sop_db.batch_upsert()
            self.kin_db.batch_upsert()
            self.check_helpers_status()
            self.collect_sim_profiles()
            self.qs.run()
        self.elem_count -= 1
        self.thread_status[nm_el.thread_id] = ThreadStatus.IDLE
        self.klog.debug(
            f'Vertice {nm_el.id} in for NM {nm_el.gen} is done.')
        # Might not be 100% safe in multi-threading
        nm_idx: int = self.elements.index(nm_el)
        return self.elements.pop(nm_idx)

    def calculate_rate_coefficients(self,
                                    el: Element) -> None:
        """Calculate rate coefficients for an element."""
        name: str = f'NM{el.gen:04d}'
        start_time: float = time.time()
        el.rateCoef = RateCo(
            sop=el.sop,
            settings=self.settings,
            software_tpl=self.rc_tpl,
            id=el.id,
            thread_id=el.thread_id,
            name=f'{name}{el.name}',
            loc=f'{self.swarm_loc}/{name}',
            q_sys=self.qs,
            db=self.kin_db,
            klog=self.klog
        )
        el.rateCoef.set_status(table=name)
        if el.rateCoef.status == JobStatus.NOT_IN_QUEUE:
            el.rateCoef.q_up()
        elif el.rateCoef.status == JobStatus.FINISHED:
            el.save_kin(db=self.kin_db, table=name)
        self.timers[ElementStatus.SOP] += \
            (time.time() - start_time)

    def run_simulation(self,
                       el: Element) -> None:
        """Run the simulation for an element."""
        name: str = f'NM{el.gen:04d}'
        start_time: float = time.time()
        el.sim = SIM(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            thread_id=el.thread_id,
            db=self.sim_db,
            gen_name=name,
            sc_species=self.sc_species,
            loc=f'{self.swarm_loc}/{name}',
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        el.sim.q_up()
        self.timers[ElementStatus.KIN] += \
            (time.time() - start_time)
        el.status = ElementStatus.SIM

    def recover_simulation_data(self,
                                el: Element) -> None:
        """Recover simulation data for an element."""

        name: str = f'NM{el.gen:04d}'
        # Avoid large batch_select causing I/O errors
        start_time: float = time.time()
        if len(self.sim_db._select) > 2000:
            self.klog.debug(f'Already {len(self.sim_db._select)} selected')
            return

        # Change status from RUNNING to FINISHED (may have failed)
        el.sim.set_status()
        if el.sim.status == JobStatus.FINISHED:
            self.qs.pickUp(id=el.id, jtype='sim')
            el.sim.set_status()
        # If successful, do the request
        if el.sim.status == JobStatus.PICKED_UP or\
           el.sim.status == JobStatus.NOT_IN_QUEUE:
            if any([prof is None for prof in el.sim.profiles]):
                el.request_sim_profiles(sim_db=self.sim_db,
                                        table=name)
        # Reset Element if simulation had an error
        elif el.sim.status == JobStatus.FAILED:
            el.status = ElementStatus.RESET
        self.timers[ElementStatus.SIM] += \
            (time.time() - start_time)

    def finalize_element(self,
                         el: Element) -> None:
        """Make sure element is saved before changing status."""
        name: str = f'NM{el.gen:04d}'
        start_time: float = time.time()
        if self.sop_db.entry_exist(table=name,
                                   id=el.id):
            el.status = ElementStatus.DONE
        else:
            el.prepare_upsert(db=self.sop_db, table=name)
        self.timers[ElementStatus.TO_SAVE] += \
            (time.time() - start_time)

    def collect_sim_profiles(self) -> None:
        """Batch recovery of the concentration profiles to avoid
        multiple db transactions.
        """
        start_time: float = time.time()
        if len(self.sim_db._select) == 0:
            return
        nsim: int = len(self.pres) *\
            len(self.temp)
        collected: dict[str, list[int]] = {}
        to_collect: dict[str, list[int]] = self.sim_db._select.copy()
        collecting: dict[str, dict[int, NDArray]] = self.sim_db.batch_select()
        for name in collecting.keys():
            nm_id = int(name[2:6])
            for sim_id, db_data in collecting[name].items():
                # There is only one Element per nm_id
                el: Element = [
                    el for el in self.elements if el.gen == nm_id][0]
                supposed_el_id: int = sim_id // nsim
                if el.id != supposed_el_id:
                    raise IndexError(
                        f'Incorrect sim_id {sim_id} for element id {el.id}'
                        f' (expected {supposed_el_id})'
                    )
                sim: int = sim_id % nsim
                # number of timesteps
                nsteps: int = len(self.settings['exp_profiles'][sim][0])
                # Happens because of data concurrency
                if len(db_data) != nsteps:
                    continue
                # The data are correct, free the queuing system
                el.sim.profiles[sim] = db_data

                # Scoring needs all the profiles
                if all([prof is not None for prof in el.sim.profiles]):
                    el.status = ElementStatus.SCORING
                if name not in collected:
                    collected[name] = []
                collected[name].append(sim_id)
        if collected == to_collect:
            msg = 'Collected all requested sim profiles.'
            self.klog.debug(msg)
            self.timers['collecting_sim'] += (
                time.time() - start_time)
            return
        elif self.settings['restart'] == RestartType.RESCORE:
            msg = f'Collected {len(collected)}/{len(to_collect)} sim profiles.'
            msg += 'Waiting for the others from DB.'
            self.klog.debug(msg)
            # Only True for Linear sensitivity analysis
            if not hasattr(self, 'selected'):
                return
        else:
            msg = f'Collected {len(collected)}/{len(to_collect)} sim profiles.'
            msg += 'Requesting the others from helpers.'
            self.klog.debug(msg)
        # Some profiles are not saved in the database yet
        hlp_idx: int = -1
        # Look if helpers are available
        for idx, hlp in enumerate(self.sim_hlpers):
            if len(hlp) == 0:
                hlp_idx = idx
                break
        # Don't create helpers if none available
        if hlp_idx == -1:
            return
        # Create helpers if needed
        need_helper: list[tuple[str, int]] = []
        for name in to_collect.keys():
            if name not in collected:
                need_helper.append(
                    (name, to_collect[name][0])
                )
            
        filenames = []
        # Avoid asking multiple helpers to do the same
        assigned_ids = set()  # Set to track already assigned sim_ids

        # Collect all sim_ids that are already assigned to helpers
        for hlp in self.sim_hlpers:
            assigned_ids.update(hlp)

        # Filter need_helper to remove any sim_ids that are already assigned
        for (name, sim_id) in need_helper:
            nm_id = int(name[2:6])
            el: Element = [el for el in self.elements if el.gen == nm_id][0]
            supposed_el_id: int = sim_id // nsim
            if el.id != supposed_el_id:
                raise IndexError(
                    f'Incorrect sim_id {sim_id} for element id {el.id}'
                    f' (expected {supposed_el_id})'
                )
            el: Element = self.elements[sim_id // nsim]
            sim: int = sim_id % nsim
            flnm: str = \
                f'{self.swarm_loc}/{name}/{el.id//50:02d}' +\
                f'/{name}{el.name}S{sim:02d}.json'
            # Happens because of long write times
            if os.path.isfile(flnm):
                if len(self.sim_hlpers[hlp_idx]) < 50:
                    if (name, sim_id) not in assigned_ids:
                        self.sim_hlpers[hlp_idx].append((name, sim_id))
                        filenames.append(flnm)
                # The job has finished without error, but didn't write
                # json file
                else:
                    break
            else:
                if sim_id not in self.requeue_timer:
                    self.requeue_timer[sim_id] = time.time()
                # Wait maximum 30 sec for file to be written
                elif time.time() - self.requeue_timer[sim_id] < 30.0:
                    continue
                # or resubmit
                else:
                    self.requeue_timer[sim_id] = time.time()
                    msg: str = f'Missing file: {el.name}S{sim:02d}.json'
                    msg += ' Sim re-submitted.'
                    self.klog.info(msg)
                    el.sim.q_up()
                continue
        if len(self.sim_hlpers[hlp_idx]) == 0:
            self.timers['collecting_sim'] += (time.time() - start_time)
            return

        self.submit_helper(hlp_idx=hlp_idx,
                           filenames=filenames)
        self.timers['collecting_sim'] += (time.time() - start_time)

    def submit_helper(self,
                      hlp_idx: int,
                      filenames: list[str]) -> None:
        """Submit a helper job to process simulation profiles.

        Args:
            hlp_idx (int): Index of the helper.
            filenames (list[str]): List of filenames to process.
        """
        hlp_name: str = f'hlp_{hlp_idx}'
        hlp_job: str = sim_helper.format(
            db=self.sim_db,
            hlp_idx=hlp_idx,
            filenames=filenames
            )
        with open(f'{self.swarm_loc}/{hlp_name}.py', 'w') as f:
            f.write(hlp_job)
        self.qs.add_to_q(
            name=hlp_name,
            idx=hlp_idx,
            location=f'{self.swarm_loc}',
            jtype='hlp',
            ressources=(self.settings['cpu_kin'], self.settings['mem_hlp'])
            )

    def recalc_score(self,
                     el: Element) -> None:
        """Reload the simulated profiles from the db, and rescore them.
        Save the new score by overwritting the old one.

        Args:
            el (Element): Element
        """
        name = f'NM{el.gen:04d}'
        el.rateCoef = RateCo(
            sop=el.sop,
            settings=self.settings,
            software_tpl=self.rc_tpl,
            id=el.id,
            thread_id=el.thread_id,
            name=f'{name}{el.name}',
            loc=f'{self.swarm_loc}/{name}',
            q_sys=self.qs,
            db=self.kin_db,
            klog=self.klog
        )
        el.sim = SIM(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            db=self.sim_db,
            gen_name=name,
            sc_species=self.sc_species,
            loc=f'{self.swarm_loc}/{name}',
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        if any([prof is None for prof in el.sim.profiles]):
            el.request_sim_profiles(sim_db=self.sim_db,
                                    table=name)

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
        start_time: float = time.time()
        try:
            scores: list[float] = self.sf.score(sim=el.sim)
            for idx, k in enumerate(el.sop.scores):
                el.sop.scores[k] = scores[idx]
            el.status = ElementStatus.TO_SAVE
        except IndexError as e:
            self.klog.debug(e)
            # Occurs when a simulation didn't work so profiles were not saved
            el.status = ElementStatus.RESET
            self.klog.info(f'Resetting element {el.id}: error during scoring.')
        self.timers[ElementStatus.SCORING] += \
            (time.time() - start_time)

    def check_helpers_status(self) -> None:
        """Management of helpers status.
        """
        nsim: int = len(self.pres) *\
            len(self.temp)
        for i in range(len(self.sim_hlpers)):
            if self.qs.status(i, 'hlp') == JobStatus.FINISHED:
                self.qs.pickUp(id=i,
                               jtype='hlp')
            if self.qs.status(i, 'hlp') == JobStatus.FAILED:
                self.klog.warning(f'Helper {i} failed to collect sim profiles.')
                self.klog.warning('Corresponding sim_ids are reset')
                for sim_id in self.sim_hlpers[i]:
                    el: Element = self.elements[sim_id // nsim]
                    el.status = ElementStatus.RESET
                self.sim_hlpers[i] = []
            elif self.qs.status(i, 'hlp') == JobStatus.NOT_IN_QUEUE:
                self.sim_hlpers[i] = []

    @property
    def best_score(self) -> float:
        return min([el.score for el in self.elements])
