import os
from typing import Any
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.core import CoreRun
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
import time
import logging
from kimeco.logger_config import setup_logger
import shutil


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
        os.mkdir('logs')
        # Copy files necessary for MESS calculation
        for file in self.elements[0].sop.files2copy:
            shutil.copyfile(f'{self.loc}/{file}', f'{gen_dir}/{file}')
        # Clean the SIM database
        if not self.finished and self.sim_db.table_exists(self.name):
            self.sim_db.wipe_table(self.name)

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

    def reset_element(self, el: Element) -> None:
        """Reset a failed element."""
        rst: int = el.reset
        self.elements[el.id] = Element(
            sop=self.pert.perturb(sop=self.previous_el[el.id].sop),
            id=el.id,
            gen=self.id
        )
        self.elements[el.id].reset = rst + 1
