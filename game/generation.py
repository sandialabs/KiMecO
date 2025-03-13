import os
from typing import List, Dict, Any
from game.database.kin_db import KIN_DB
from game.database.sim_db import SIM_DB
from game.database.sop_db import SOP_DB
from game.element import Element, ElementStatus
from game.core import CoreRun
from game.scoring_f.scoring import Scoring
from game.Perturbators.perturbator import Perturbator
from game.parameters import SOP
import math
import time


class Generation(CoreRun):
    __id = 0

    @classmethod
    def total(cls) -> int:
        """Return the total number of Generation instances."""
        return cls.__id

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
        self.id: int = Generation.__id
        Generation.__id += 1
        super().__init__(
                 elements=elements,
                 settings=settings,
                 rc_tpl=rc_tpl,
                 loc=loc,
                 sop_db=sop_db,
                 kin_db=kin_db,
                 sim_db=sim_db,
                 sf=sf,
                 pert=pert,
                 previous_el=previous_el,
                 name=f'G{self.id:04d}')
        # Create generation directory
        gen_dir: str = f'{self.loc}/{self.name}'
        os.makedirs(gen_dir, exist_ok=True)
        os.chdir(gen_dir)

        if settings['restart'] == 'default':
            self.restore_gen_from_db()

    def run(self) -> None:
        """Run a generation until all of its elements are scored.
        """
        start_time: float = time.time()
        print(f'Running generation {self.id} ...')
        super().run()
        self.end_run(start_time)

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

    def restore_gen_from_db(self) -> None:
        """Create a complete list of elements from the data in the database.
        """
        # Read the data from the db
        rows = self.sop_db.get_table(table=self.name)
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
