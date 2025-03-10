import os
from typing import List, Dict, Any
from game.database.kin_db import KIN_DB
from game.database.sim_db import SIM_DB
from game.database.sop_db import SOP_DB
from game.element import Element, ElementStatus
from game.scoring_f.scoring import Scoring
from game.parameters import SOP
import numpy as np
import numpy.typing as npt
from numpy import bool_
import math
import time
from game.q_sys import QueueingSystem, JobStatus
from game.rate_coef import RateCo
from game.simulation import SIM
from game.Perturbators.perturbator import Perturbator
from game.templates.sim_helper import sim_helper


class Generation:
    __id = 0

    @classmethod
    def total(cls) -> int:
        """Return the total number of Generation instances."""
        return cls.__id

    def __init__(self,
                 elements: list[Element],
                 set: dict[str, Any],
                 rc_tpl: list[str],
                 loc: str,
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 pert: Perturbator,
                 previous_el: dict[int, Element] = {}
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
        self.elements: List[Element] = elements
        self.previous_el: dict[int, Element] = previous_el
        self.id: int = Generation.__id
        Generation.__id += 1
        self.pert: Perturbator = pert
        self.settings: dict[str, Any] = set
        # List of species names used by cantera
        self.species: List[str] = self.settings['score_sp']
        # Rate coefficients template
        self.rc_tpl: List[str] = rc_tpl
        # where the generation is running
        self.loc: str = loc
        self.sf: Scoring = sf
        self.best_score: float = np.inf
        self.sim_hlpers = [
            [] for i in range(self.settings['max_helpers'])
            ]
        # Create generation directory
        gen_dir = f'{self.loc}/G{self.id:04d}'
        os.makedirs(gen_dir, exist_ok=True)
        os.chdir(gen_dir)

        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.create_tables()

        if set['restart'] == 'default':
            self.restore_gen_from_db()

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

    def create_tables(self) -> None:
        """Create the tables in all databases
        """
        # Create table for gen in SOP, KIN and SIM
        # SOP
        tbl_name: str = f'G{self.id}'
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

    def run(self) -> None:
        """Run a generation until all of its elements are scored.

        Args:
            q_sys (QueueingSystem): Queueing system in charge of managing
                                    the ressources and running as many jobs
                                    in parallel as possible.
        """
        start_time = time.time()
        print(f'Running generation {self.id} ...')
        finished: npt.NDArray[bool_] = np.full(shape=(len(self.elements), 1),
                                               fill_value=False)
        while not all(finished):
            for idx, el in enumerate(self.elements):
                if finished[idx]:
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
                    el.calc_score()
                if el.status == ElementStatus.DONE:
                    self.finalize_element(el, idx, finished)
            self.sop_db.batch_upsert()
            self.kin_db.batch_upsert()
            self.check_helpers_status()
            self.collect_sim_profiles()
            self.qs.run()
        self.end_run(start_time)

    def reset_element(self, el: Element) -> None:
        """Reset a failed element."""
        rst: int = el.reset
        self.elements[el.id] = Element(
            sop=self.pert.perturb(sop=self.previous_el[el.id].sop),
            id=el.id,
            sf=self.sf
        )
        self.elements[el.id].reset = rst + 1

    def calculate_rate_coefficients(self, el: Element) -> None:
        """Calculate rate coefficients for an element."""
        el.rateCoef = RateCo(
            sop=el.sop,
            settings=self.settings,
            software_tpl=self.rc_tpl,
            id=el.id,
            name=f'G{self.id:04d}E{el.id:04d}',
            loc=f'{self.loc}/G{self.id:04d}',
            q_sys=self.qs,
            db=self.kin_db
        )
        el.rateCoef.set_status(table=f"G{self.id}")
        if el.rateCoef.status == JobStatus.NOT_IN_QUEUE:
            el.rateCoef.q_up()
        elif el.rateCoef.status == JobStatus.FINISHED:
            el.save_kin(db=self.kin_db, table=f'G{self.id}')

    def run_simulation(self,
                       el: Element) -> None:
        """Run the simulation for an element."""
        el.sim = SIM(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            db=self.sim_db,
            gen_id=self.id,
            species=self.species,
            loc=f'{self.loc}/G{self.id:04d}',
            q_sys=self.qs,
            set=self.settings
        )
        el.sim.q_up()
        el.status = ElementStatus.SIM

    def recover_simulation_data(self,
                                el: Element) -> None:
        """Recover simulation data for an element."""
        for prof in el.sim.profiles:
            if prof is None:
                el.request_sim_profiles(db=self.sim_db, table=f'G{self.id}')
                break

    def finalize_element(self,
                         el: Element,
                         idx: int,
                         finished: npt.NDArray[bool_]) -> None:
        """Finalize an element after scoring."""
        el.prepare_upsert(db=self.sop_db, table=f'G{self.id}')
        finished[idx] = True
        if np.sum(el.scores) < self.best_score:
            self.best_score = np.sum(el.scores)

    def end_run(self, start_time: float) -> None:
        """Report the runtime of the generation."""
        end_time = time.time()
        runtime = end_time - start_time
        print(f'Generation {self.id} completed in {runtime:.2f} seconds.')
        self.means, self.stds = self.get_stats()
        print(f'Best score: {self.best_score}')
        print('Statistics:')
        print('{:16s} {:10s} {:10s}'.format(
            'Parameter name',
            'Mean',
            'STD dev'
        ))
        for k in self.means:
            print('{:16s} {:-10.2e} {:-10.2e}'.format(
                k,
                self.means[k],
                self.stds[k]
            ))

    def collect_sim_profiles(self):
        """Batch recovery of the concentration profiles to avoid
        multiple db transactions.
        """
        if len(self.sim_db._select) == 0:
            return
        nsim: int = len(self.settings['rc_pres']) *\
            len(self.settings['rc_temp'])
        collected: list[int] = []
        to_collect = self.sim_db._select[f'G{self.id}']
        collecting: dict[int, list[list[Any]]] = self.sim_db.batch_select()
        for sim_id, rows in collecting.items():
            el: Element = self.elements[sim_id // nsim]
            sim: int = sim_id % nsim
            # number of timesteps
            nsteps = len(self.settings['exp_profiles'][sim][0])
            db_data = np.array(
                [i[1:] for i in rows])
            # Happens because of data concurrency
            if len(db_data) != nsteps:
                continue
            el.sim.profiles[sim] = db_data
            self.qs.pickUp(id=sim_id,
                           jtype='sim')
            go2scoring = True
            for prof in el.sim.profiles:
                if prof is None:
                    go2scoring = False
                    break
            if go2scoring:
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
        unique_need_helper = []
        for sim_id in need_helper:
            if len(unique_need_helper) < 30:
                if sim_id not in assigned_ids:
                    unique_need_helper.append(sim_id)
            else:
                break
        if len(unique_need_helper) == 0:
            return

        self.sim_hlpers[hlp_idx] = unique_need_helper
        for sim_id in self.sim_hlpers[hlp_idx]:
            el: Element = self.elements[sim_id // nsim]
            sim: int = sim_id % nsim
            flnm: str = f'G{self.id:04d}E{el.id:04d}S{sim:02d}.json'
            if os.path.isfile(f'{flnm}'):
                filenames.append(f'{flnm}')
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
            gen=self.id
            )
        with open(f'{self.loc}/G{self.id:04d}/{hlp_name}.py', 'w') as f:
            f.write(hlp_job)
        self.qs.add_to_q(
                 name=hlp_name,
                 idx=hlp_idx,
                 location=f'{self.loc}/G{self.id:04d}',
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
                print(f'Helper {i} failed to collect sim profiles.',
                      'Corresponding sim_ids are reset')
                for sim_id in self.sim_hlpers[i]:
                    el: Element = self.elements[sim_id // nsim]
                    el.status = ElementStatus.RESET
                self.sim_hlpers[i] = []
            elif self.qs.status(i, 'hlp') == JobStatus.NOT_IN_QUEUE:
                self.sim_hlpers[i] = []

    def restore_gen_from_db(self) -> None:
        """Create a complete list of elements from the data in the database.
        """
        # Read the data from the db
        rows = self.sop_db.get_table(table=f'G{self.id}')
        # Create the list of elements from the db
        new_gen: List[Element] = [Element(
            sop=SOP.from_db_row(sop_tpl=self.elements[0].sop,
                                row=row[1:]),
            id=row[0],
            sf=self.sf)
            for idx, row in enumerate(rows) if idx < self.settings['n_elem']]
        for el in new_gen:
            not_default: List[bool] = [
                i != self.sf.default_score for i in el.scores]
            if all(not_default):
                el.status = ElementStatus.DONE
            for idx, gen_el in enumerate(self.elements):
                if el.id == gen_el.id:
                    self.elements[idx] = el
                    break

    def get_stats(self) -> tuple[Dict[str, float], Dict[str, float]]:
        """Calculate the standard deviation of each key in the
        parameters_names dictionary across all SOP objects.

        Returns:
            Dict[str, float]: Dictionary with the mean values for each key.
            Dict[str, float]:
                Dictionary with the standard deviation for each key.
        """
        sop_list: List[SOP] = [el.sop for el in self.elements]

        # Initialize dictionaries to hold the sum of values,
        # sum of squared values, and a count of SOPs
        sum_values: Dict[str, float] = {}
        sum_squared_values: Dict[str, float] = {}
        count: int = len(sop_list)

        # Iterate through each SOP object
        for sop in sop_list:
            parameters = sop.parameters_names
            for key, value in parameters.items():
                if key not in sum_values:
                    sum_values[key] = 0.0
                    sum_squared_values[key] = 0.0
                sum_values[key] += value
                sum_squared_values[key] += value ** 2

        # Calculate the standard deviation for each key
        stddev_values: Dict[str, float] = {}
        mean_values: Dict[str, float] = {}
        for key in sum_values:
            mean: float = sum_values[key] / count
            mean_values[key] = mean
            variance: float = (sum_squared_values[key] / count) - (mean ** 2)
            stddev_values[key] = math.sqrt(variance) if variance > 0 else 0.0

        return mean_values, stddev_values
