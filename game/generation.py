import os
from typing import List, Dict, Any

from game.database.kin_db import KIN_DB
from game.database.sim_db import SIM_DB
from game.database.sop_db import SOP_DB
from game.element import Element
from game.scoring_f.scoring import Scoring
from game.well import Well
from game.barrier import Barrier
from game.parameters import SOP
import numpy as np
import numpy.typing as npt
from numpy import bool_
import math
from game.q_sys import QueueingSystem
from game.rate_coef import RateCo
from game.simulation import SIM
from game.Perturbators.perturbator import Perturbator


class Generation:
    __id = 0

    @classmethod
    def total(cls) -> int:
        """Number of generations instanciated.
        Used outside of the class to access __id.

        Returns:
            int: Total number of Generations instanciated.
        """
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
        self.species: List[str] = [
            self.elements[0].sop.items[specie].ct_name
            for specie, obj in self.elements[0].sop.items.items()
            if isinstance(obj, Well) and not isinstance(obj, Barrier)]
        # Rate coefficients template
        self.rc_tpl: List[str] = rc_tpl
        # where the generation is running
        self.loc: str = loc
        self.sf: Scoring = sf
        self.best_score: float = np.inf
        if not os.path.isdir(f'{self.loc}/G{self.id:04d}'):
            os.mkdir(f'{self.loc}/G{self.id:04d}')
        os.chdir(f'{self.loc}/G{self.id:04d}')
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.create_tables()
        if set['restart'] == 'default':
            self.restore_gen_from_db()
        self.qs = QueueingSystem(max_jobs=self.settings['max_jobs'],
                                 max_cpu=self.settings['max_cpu'],
                                 max_mem=self.settings['max_mem'],
                                 cpu_kin=self.settings['cpu_kin'],
                                 mem_kin=self.settings['mem_kin'],
                                 cpu_sim=self.settings['cpu_sim'],
                                 mem_sim=self.settings['mem_sim'],
                                 nkin=len(self.elements),
                                 nsim=len(self.elements) *
                                 len(self.settings['rc_temp']) *
                                 len(self.settings['rc_pres'])
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
        print(f'Running generation {self.id} ...')
        finished: npt.NDArray[bool_] = np.full(shape=(len(self.elements), 1),
                                               fill_value=False)

        while not all(finished):
            for idx, el in enumerate(self.elements):
                # Skip finished elements
                if finished[idx]:
                    continue
                # Reset failed caluclations
                if el.status == 'reset':
                    rst: int = el.reset
                    self.clean_q(self.elements[el.id])
                    self.elements[el.id] = Element(
                        sop=self.pert.perturb(sop=self.previous_el[el.id].sop),
                        id=el.id,
                        sf=self.sf)
                    # Keep track of how many elements have been reset
                    self.elements[el.id].reset = rst + 1
                    continue
                # Calculate rate coefficients
                if el.status == 'sop':
                    el.rateCoef = RateCo(sop=el.sop,
                                         settings=self.settings,
                                         software_tpl=self.rc_tpl,
                                         id=el.id,
                                         name=f'G{self.id:04d}E{el.id:04d}',
                                         loc=f'{self.loc}/G{self.id:04d}',
                                         q_sys=self.qs,
                                         db=self.kin_db)
                    el.rateCoef.set_status(table=f"G{self.id}")
                    if el.rateCoef.status == 'notInQueue':
                        el.rateCoef.q_up()
                    elif el.rateCoef.status == 'running':
                        continue
                    elif el.rateCoef.status == 'finished':
                        # Next status is set in this function as it can fail.
                        el.save_kin(db=self.kin_db,
                                    table=f'G{self.id}')
                # Calculate SIMs
                elif el.status == 'kin':
                    el.sim = SIM(sop=el.sop,
                                 kin=el.rateCoef,
                                 id=el.id,
                                 db=self.sim_db,
                                 gen_id=self.id,
                                 species=self.species,
                                 loc=f'{self.loc}/G{self.id:04d}',
                                 q_sys=self.qs,
                                 set=self.settings)
                    el.sim.q_up()
                    el.status = 'sim'
                # Recover simulations data
                elif el.status == 'sim':
                    for sim_i in range(len(el.sim.simulations)):
                        el.sim.set_status(sim=sim_i)
                    if all([True if stat == 'finished' else False
                            for stat in el.sim.status]):
                        el.recover_sim_profiles(db=self.sim_db,
                                                table=f'G{self.id}')
                        if el.status != 'reset':
                            el.status = 'scoring'
                    # Not sure yet why this case happens, but it does happen
                    elif any([True if stat == 'notInQueue' else False
                              for stat in el.sim.status]):
                        el.sim.q_up()
                # Scoring
                if el.status == 'scoring':
                    el.calc_score()
                if el.status == 'DONE':
                    el.prepare_upsert(db=self.sop_db,
                                      table=f'G{self.id}')
                    finished[idx] = True
                    if np.sum(el.scores) < self.best_score:
                        self.best_score: float = np.sum(el.scores)
            self.sop_db.batch_upsert()
            self.kin_db.batch_upsert()
            self.qs.run()

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
                el.status = 'DONE'
            for idx, gen_el in enumerate(self.elements):
                if el.id == gen_el.id:
                    self.elements[idx] = el
                    break

    def clean_q(self,
                elem: Element):
        """Reset the statuses in the queing system
        for an element when it gets reset.

        Args:
            elem (Element): Element that has status reset before
            it gets reperturbed.
        """
        self.qs.kin_q[elem.id]['status'] = 'notInQueue'
        if hasattr(elem, 'sim'):
            for sim in range(len(elem.sim.simulations)):
                sim_id: int = self.id * len(elem.sim.simulations) + sim
                self.qs.sim_q[sim_id]['status'] = 'notInQueue'

    def get_stats(self) -> tuple[Dict[str, float], Dict[str, float]]:
        """Calculate the standard deviation of each key in the
        parameters_names dictionary across all SOP objects.

        Args:
            sop_list (List[SOP]): List of SOP objects.

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
