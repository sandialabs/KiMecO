import os
from typing import Any
from game.element import Element
from game.parameters import SOP
from game.perturbator import Perturbator
import numpy as np
import numpy.typing as npt
from numpy import bool_

from game.queue.q_sys import QueueingSystem
from game.rate_constants import RateCo
from game.simulation import SIM


class Generation:
    __id = 0

    def __init__(self,
                 sop: SOP,
                 n: int,
                 pert: Perturbator,
                 set: dict[str, Any],
                 rc_tpl: list[str],
                 loc: str
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
        self.sop: SOP = sop
        self.id: int = Generation.__id
        Generation.__id += 1
        self.pert: Perturbator = pert
        self.elements: list[Element] = []
        self.settings: dict[str, Any] = set
        self.rc_tpl: list[str] = rc_tpl
        self.loc: str = loc
        if not os.path.isdir(f'{self.loc}/G{self.id}'):
            os.mkdir(f'{self.loc}/G{self.id}')
        self.generate(n=n)

    def generate(self,
                 n: int) -> None:
        """Generate all the perturbed set of parameters
        and store then in the self elements array.

        Args:
            n (int): _description_
        """
        # Reset the element id for each generation
        Element.__id = 0
        while len(self.elements) < n:
            self.elements.append(Element(sop=self.pert.perturb(sop=self.sop)))

    def run(self,
            q_sys: QueueingSystem) -> None:
        """Run a generation until all of its elements are scored.

        Args:
            q_sys (QueueingSystem): Queueing system in charge of managing
                                    the ressources and running as many jobs
                                    in parallel as possible.
        """
        finished: npt.NDArray[bool_] = np.full(shape=(len(self.elements), 1),
                                               fill_value=False)
        while not all(finished):
            for el in self.elements:
                # Calculate rate coefficients
                if el.status == 0:
                    el.rateCoef = RateCo(sop=el.sop,
                                         settings=self.settings,
                                         software_tpl=self.rc_tpl,
                                         id=f'G{self.id}E{el.id}',
                                         loc=f'{self.loc}/G{self.id}',
                                         q_sys=q_sys)
                    el.rateCoef.q_up()
                    el.status = 1
                # Recover rate coefficients
                elif el.status == 1:
                    el.rateCoef.set_status()
                    if el.rateCoef.status == 'finished':
                        el.rateCoef.recover_rslts()
                        el.status = 2
                # Calculate SIMs
                elif el.status == 2:
                    el.sim = SIM(sop=el.sop,
                                 kin=el.rateCoef,
                                 ct_sim=self.settings['ct_yaml'],
                                 ct_names=self.settings['ct_names'],
                                 id=f'G{self.id}E{el.id}',
                                 loc=f'{self.loc}/G{self.id}',
                                 q_sys=q_sys,
                                 set=self.settings)
                    el.sim.q_up()
            q_sys.run()
