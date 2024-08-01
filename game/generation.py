from typing import Any
from game.element import Element
from game.parameters import SOP
from game.perturbator import Perturbator
import numpy as np
import numpy.typing as npt
from numpy import bool_, ndarray

from game.rate_constants import RateCo
from game.simulation import SIM

class Generation:
    __id = 0

    def __init__(self,
                 sop: SOP,
                 n: int,
                 pert: Perturbator,
                 set: dict[str, Any],
                 rc_tpl: list[str]
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
        """
        self.sop: SOP = sop
        self.id: int = Generation.__id
        Generation.__id += 1
        self.pert: Perturbator = pert
        self.elements: list[Element] = []
        self.settings: dict[str, Any] = set
        self.rc_tpl: list[str] = rc_tpl
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

    def run(self) -> None:
        finished: npt.NDArray[bool_] = np.full(shape=(len(self.elements), 1),
                                               fill_value=False)
        while not all(finished):
            for el in self.elements:
                # Calculate rate coefficients
                if el.status == 0:
                    el.rateCoef = RateCo(sop=el.sop,
                                         settings=self.settings,
                                         software_tpl=self.rc_tpl,
                                         id=f'G{self.id}E{el.id}')
                    el.rateCoef.calculate()
                    el.status = 1
                # Recover rate coefficients
                elif el.status == 1:
                    if el.rateCoef.job_finished:
                        el.rateCoef.recover_rslts()
                        el.status = 2
                # Calculate SIMs
                elif el.status == 2:
                    el.sim = SIM(sop=el.sop,
                                 kin=el.rateCoef,
                                 ct_sim=self.settings['ct_yaml'],
                                 ct_names=self.settings['ct_names'])
                    el.sim.run()
