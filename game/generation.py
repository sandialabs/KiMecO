import os
from typing import List, Any
from game.database.kin_db import KIN_DB
from game.database.sim_db import SIM_DB
from game.database.sop_db import SOP_DB
from game.element import Element, ElementStatus
from game.core import CoreRun
from game.scoring_f.scoring import Scoring
from game.Perturbators.perturbator import Perturbator
from game.parameters import SOP
import numpy as np
import numpy.typing as npt
from numpy import bool_
import time
import logging
from game.logger_config import setup_logger


# Call the setup function to configure logging
setup_logger()
glog = logging.getLogger()


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
        glog.info(f'Running generation {self.id} ...')
        super().run()
        self.end_run(start_time)

    def end_run(self, start_time: float) -> None:
        """Report the runtime of the generation."""
        end_time = time.time()
        runtime = end_time - start_time
        message = f'Generation {self.id} completed. RUNTIME:'
        glog.info(f'{message:<65}{runtime:>14.2f}s.')
        glog.info(f"{'Best score:':<65}{self.best_score:>14.2f}")

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
            sf=self.sf,
            gen=self.id)
            for idx, row in enumerate(rows) if idx < self.settings['n_elem']]
        for el in new_gen:
            not_default: List[bool] = [
                i != el.sop._default_score for i in el.scores]
            if all(not_default):
                el.status = ElementStatus.DONE
            for idx, gen_el in enumerate(self.elements):
                if el.id == gen_el.id:
                    self.elements[idx] = el
                    break

    # Override the core method to only save new elements from gen_id
    def finalize_element(self,
                         el: Element,
                         idx: int,
                         finished: npt.NDArray[bool_]) -> None:
        """Finalize an element after scoring."""
        # Avoids saving elements in multiple tables
        if el.gen == self.id:
            el.prepare_upsert(db=self.sop_db, table=self.name)
        finished[idx] = True
        if np.sum(el.scores) < self.best_score:
            self.best_score = np.sum(el.scores)
