from _thread import LockType
from typing import Any, Optional
import os
import glob
import threading
import numpy as np
from numpy.typing import NDArray
from kimeco.enums import ElementStatus
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.scoring_f.scoring import Scoring
from kimeco.logger_config import KMOLogger
import time
import concurrent.futures
import json


class CoreRun:

    def __init__(self,
                 elements: list[Element],
                 settings: dict[str, Any],
                 rc_tpl: list[str],
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 pert: Optional[Perturbator],
                 klog: KMOLogger,
                 previous_el: dict[int, Element] = {},
                 base_dir: str = '',
                 prefix: str = 'C') -> None:

        self.prefix: str = prefix
        self.klog: KMOLogger = klog
        self.elements: list[Element] = elements
        self.settings: dict[str, Any] = settings
        self.previous_el: dict[int, Element] = previous_el
        self.pert: Optional[Perturbator] = pert
        self.base_dir: str = base_dir
        # List of species names used by cantera
        self.sc_species: list[str] = self.settings['score_sp']
        # Rate coefficients template
        self.rc_tpl: list[str] = rc_tpl
        self.loc: str = settings['workdir']
        # Scoring function
        self.sf: Scoring = sf

        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.create_tables()
        self.pres: list[float] = settings["rc_pres"]
        self.temp: list[float] = settings["rc_temp"]

        self.qs = QueueingSystem(
            settings=self.settings,
            nel=len(self.elements),
            nhlp=0,  # Helpers removed - no longer used
            klog=self.klog)
        self.clean_files()
        # Contain the time when a sim_id was first queried
        self.requeue_timer = {}

        # Thread-safe locks
        self.el_locks: dict[tuple[int, int], LockType] = {(el.gen, el.id): threading.Lock() for el in self.elements}
        self.qs_lock = threading.Lock()
        self.requeue_lock = threading.Lock()
        self.file_locks = {}

        # Create base directory
        base_path: str = f'{self.loc}/{self.base_dir}'
        os.makedirs(base_path, exist_ok=True)

        # Create folders for each element's generation
        if self.elements:
            generations_present = set(el.gen for el in self.elements)

            for gen in generations_present:
                gen_name = f'{self.prefix}{gen:04d}'
                gen_dir = f'{base_path}/{gen_name}'
                os.makedirs(gen_dir + '/logs', exist_ok=True)

                # Get elements in this generation
                gen_elements = [el for el in self.elements if el.gen == gen]
                subfolders_needed = set(
                    el.id // 50 for el in gen_elements
                )

                for subfolder_num in subfolders_needed:
                    subfolder = f'{gen_dir}/{subfolder_num:02d}'
                    os.makedirs(subfolder + '/logs', exist_ok=True)

                    # Copy files necessary for MESS calculation
                    first_el = next(
                        el for el in gen_elements
                        if el.id // 50 == subfolder_num
                    )
                    for file in first_el.sop.files2copy:
                        src = f'{self.loc}/{file}'
                        dst = f'{subfolder}/{file}'
                        if (not os.path.isfile(dst) and
                            os.path.isfile(src)):
                            os.symlink(src, dst)

        # Change to base directory
        os.chdir(base_path)

    def get_table_name(self, el: Element) -> str:
        """Get the table name for an element based on its generation.

        Args:
            el: Element

        Returns:
            Table name (e.g., 'G0000')
        """
        return f'{self.prefix}{el.gen:04d}'

    def get_gen_folder(self, el: Element) -> str:
        """Get the generation folder path for an element.

        Args:
            el: Element

        Returns:
            Path to generation folder (e.g., 'workdir/base_dir/G0000')
        """
        return f'{self.loc}/{self.base_dir}/{self.get_table_name(el)}'

    def get_element_subfolder(self, el: Element) -> str:
        """Get the element subfolder path (50 elements per subfolder).

        Args:
            el: Element

        Returns:
            Path to element subfolder (e.g., 'workdir/base_dir/G0000/01')
        """
        return f'{self.get_gen_folder(el)}/{el.id//50:02d}'

    def clean_files(self) -> None:
        for el in self.elements:
            if el.status != ElementStatus.DONE:
                table_name: str = self.get_table_name(el)
                for file in glob.glob(
                    f"{table_name}{el.name}*"
                ):
                    os.remove(file)

    def create_tables(self) -> None:
        """Create the tables in all databases for all element generations.
        """
        if not self.elements:
            return

        # Get unique generations from elements
        generations: set[int] = set(el.gen for el in self.elements)

        for gen in generations:
            tbl_name: str = f'{self.prefix}{gen:04d}'

            # SOP
            if tbl_name not in self.sop_db.tables:
                self.sop_db.create_new_table(name=tbl_name)

            # KIN
            if tbl_name not in self.kin_db.tables:
                self.kin_db.create_new_table(name=tbl_name)

            # SIM
            if tbl_name not in self.sim_db.tables:
                self.sim_db.create_new_table(name=tbl_name)

    @property
    def finished(self) -> bool:
        return all([el.status == ElementStatus.DONE
                    for el in self.elements])

    def run(self) -> None:
        """Run a generation until all of its elements are scored.
        """
        while not self.finished:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=self.settings['threads']) as exec:
                futures = []
                for idx, el in enumerate(self.elements):
                    # Safeguard
                    if self.elements[idx].id != el.id:
                        raise IndexError(
                            'Incorrect ordering of the elements.')
                    if el.status == ElementStatus.DONE:
                        continue

                    # Try to acquire lock, skip if busy
                    if not self.el_locks[(el.gen, el.id)].acquire(blocking=False):
                        continue

                    # Submit work with lock held
                    futures.append(
                        exec.submit(self._process_element_locked, el))

                # Wait for all futures to complete and check for errors
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        self.klog.error(f'Error processing element: {e}')

            self.sop_db.batch_upsert()
            self.kin_db.batch_upsert()
            self.sim_db.batch_upsert()
            self.collect_sim_profiles()
            with self.qs_lock:
                self.qs.run()

    def _process_element_locked(self, el: Element) -> None:
        """Process element with lock already held by caller.
        Lock will be released in finally block.
        """
        try:
            if el.status == ElementStatus.RESET:
                self.reset_element(el)
            elif el.status == ElementStatus.SOP:
                self.calculate_rate_coefficients(el)
            elif el.status == ElementStatus.KIN:
                self.run_simulation(el)
            elif el.status == ElementStatus.SIM:
                self.recover_simulation_data(el)
            elif el.status == ElementStatus.RESCORE:
                self.recalc_score(el)
            elif el.status == ElementStatus.SCORING:
                self.calc_score(el)
            elif el.status == ElementStatus.TO_SAVE:
                self.finalize_element(el)
        finally:
            self.el_locks[(el.gen, el.id)].release()

    def reset_element(self,
                      el: Element) -> None:
        """Reset a failed element."""
        rst: int = el.reset
        table_name: str = self.get_table_name(el)

        self.elements[el.id] = Element(
            sop=self.pert.perturb(sop=self.previous_el[el.id].sop),
            id=el.id,
            gen=el.gen
            )
        for file in glob.glob(f"{table_name}{el.name}*"):
            os.remove(file)
        self.elements[el.id].reset = rst + 1

    def calculate_rate_coefficients(self, el: Element) -> None:
        """Calculate rate coefficients for an element."""
        table_name: str = self.get_table_name(el)
        if hasattr(el, 'thread_id'):
            q_idx: int = el.thread_id
        else:
            q_idx = el.id
        el.rateCoef = RateCo(
            sop=el.sop,
            settings=self.settings,
            software_tpl=self.rc_tpl,
            id=el.id,
            q_idx=q_idx,
            name=f'{table_name}{el.name}',
            loc=self.get_gen_folder(el),
            q_sys=self.qs,
            db=self.kin_db,
            klog=self.klog
        )
        el.rateCoef.set_status(table=table_name)
        if el.rateCoef.status == JobStatus.NOT_IN_QUEUE:
            el.rateCoef.q_up()
        elif el.rateCoef.status == JobStatus.FINISHED:
            el.save_kin(db=self.kin_db, table=table_name)

    def run_simulation(self,
                       el: Element) -> None:
        """Run the simulation for an element."""
        table_name: str = self.get_table_name(el)
        if hasattr(el, 'thread_id'):
            q_idx: int = el.thread_id
        else:
            q_idx = el.id
        el.sim = SIM(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            q_idx=q_idx,
            db=self.sim_db,
            gen_name=table_name,
            sc_species=self.sc_species,
            loc=self.get_gen_folder(el),
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        el.sim.q_up()
        el.status = ElementStatus.SIM

    def recover_simulation_data(self,
                                el: Element) -> None:
        """Recover simulation data for an element."""
        nsim: int = len(self.pres) * len(self.temp)
        table_name: str = self.get_table_name(el)

        # Change status from RUNNING to FINISHED (may have failed)
        el.sim.set_status()
        if el.sim.status == JobStatus.FINISHED:
            with self.qs_lock:
                self.qs.pickUp(id=el.sim.q_idx, jtype='sim')
            el.sim.set_status()

        # Reset Element if simulation had an error
        if el.sim.status == JobStatus.FAILED:
            el.status = ElementStatus.RESET
            return

        # If successful, read JSON files
        if el.sim.status == JobStatus.PICKED_UP or\
           el.sim.status == JobStatus.NOT_IN_QUEUE:
            if any([prof is None for prof in el.sim.profiles]):
                # Read JSON files for each simulation profile
                for sim in range(nsim):
                    if el.sim.profiles[sim] is not None:
                        continue  # Already loaded

                    sim_id: int = el.id * nsim + sim
                    flnm: str = f'{self.get_element_subfolder(el)}' + \
                           f'/{table_name}{el.name}S{sim:02d}.json'

                    if not os.path.isfile(flnm):
                        # File doesn't exist yet - check if we should requeue
                        with self.requeue_lock:
                            if sim_id not in self.requeue_timer:
                                self.requeue_timer[sim_id] = time.time()
                                continue
                            # Wait maximum 30 sec for file
                            elif (time.time() -
                                  self.requeue_timer[sim_id] < 30.0):
                                continue
                            else:
                                self.requeue_timer[sim_id] = time.time()
                                msg = (f'Missing file: {el.name}S{sim:02d}'
                                       '.json - resubmitting')
                                self.klog.info(msg)
                                el.sim.q_up()
                                return
                    else:
                        # File exists
                        if os.path.getsize(flnm) == 0:
                            time.sleep(2)

                        with open(flnm, 'r') as f:
                            data: dict[str, list[float]] = json.load(f)
                        # Prepare data for batch upsert
                        row_ids: list[float] = data.pop('row_ids')
                        el.sim.profiles[sim] = np.array([vals for vals in data.values()])[4:]
                        for row_id in row_ids:
                            row_data = {
                                col: data[col][row_ids.index(row_id)]
                                for col in data.keys()
                                if col != 'row_ids'
                            }
                            self.sim_db.prepare_batch_upsert(
                                table=table_name,
                                id=row_id,
                                values=row_data
                            )

                        # Delete JSON file after successful read
                        os.remove(flnm)
                        el.status = ElementStatus.SCORING

    def finalize_element(self,
                         el: Element) -> None:
        """Make sure element is saved before changing status."""
        table_name = self.get_table_name(el)

        if self.sop_db.entry_exist(table=table_name, id=el.id):
            el.status = ElementStatus.DONE
        else:
            el.prepare_upsert(db=self.sop_db, table=table_name)

    def collect_sim_profiles(self) -> None:
        """Batch recovery of concentration profiles from the database.
        This is used primarily for restart scenarios (RESCORE mode) where
        profiles already exist in the database but not as JSON files.
        """
        if len(self.sim_db._select) == 0:
            return
        nsim: int = self.settings['n_exp']

        collecting: dict[str, dict[int, NDArray]] = \
            self.sim_db.batch_select()

        # Process each table's results
        for table_name, profiles in collecting.items():
            for i in range(len(table_name)):
                if table_name[i].isdigit():
                    prefix_end = i
                    break
            gen_id = int(table_name[prefix_end:])  # Extract from G####

            for sim_id, db_data in profiles.items():
                el_id: int = sim_id // nsim
                sim_idx: int = sim_id % nsim

                # Find element with matching ID and generation
                el = None
                for element in self.elements:
                    if element.id == el_id and element.gen == gen_id:
                        el = element
                        break

                if el is None:
                    continue  # Element not found

                # number of timesteps
                nsteps: int = len(self.settings['exp_profiles'][sim_idx][0])

                # Validate data completeness
                if len(db_data) != nsteps:
                    continue

                el.sim.profiles[sim_idx] = db_data.T[1:]

                # Scoring needs all the profiles
                if all([prof is not None for prof in el.sim.profiles]):
                    el.status = ElementStatus.SCORING

    def recalc_score(self,
                     el: Element) -> None:
        """Reload simulated profiles from db, and rescore them.
        Save the new score by overwritting the old one.

        Args:
            el (Element): Element
        """
        table_name = self.get_table_name(el)
        if hasattr(el, 'thread_id'):
            q_idx: int = el.thread_id
        else:
            q_idx = el.id
        el.rateCoef = RateCo(
            sop=el.sop,
            settings=self.settings,
            software_tpl=self.rc_tpl,
            id=el.id,
            q_idx=q_idx,
            name=f'{table_name}{el.name}',
            loc=self.get_gen_folder(el),
            q_sys=self.qs,
            db=self.kin_db,
            klog=self.klog
        )
        el.sim = SIM(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            q_idx=q_idx,
            db=self.sim_db,
            gen_name=table_name,
            sc_species=self.sc_species,
            loc=self.get_gen_folder(el),
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        if any([prof is None for prof in el.sim.profiles]):
            el.request_sim_profiles(sim_db=self.sim_db,
                                    table=table_name)

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
            scores: list[float] = self.sf.score(sim=el.sim)
            for idx, k in enumerate(el.sop.scores):
                el.sop.scores[k] = scores[idx]
            el.status = ElementStatus.TO_SAVE
        except IndexError as e:
            self.klog.debug(str(e))
            # Occurs when a simulation didn't work so profiles were not saved
            el.status = ElementStatus.RESET
            self.klog.info(f'Resetting element {el.id}: error during scoring.')

    @property
    def best_score(self) -> float:
        return min([el.score for el in self.elements])
