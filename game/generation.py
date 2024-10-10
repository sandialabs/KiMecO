import os
import sys
from typing import Any

from game.element import Element
from game.parameters import SOP
from game.perturbator import Perturbator
from game.database.game_db import Game_db
import numpy as np
import numpy.typing as npt
from numpy import bool_

from game.q_sys import QueueingSystem
from game.rate_coef import RateCo
from game.simulation import SIM


class Generation:
    __id = 0

    def __init__(self,
                 sop: SOP,
                 n: int,
                 pert: Perturbator,
                 set: dict[str, Any],
                 rc_tpl: list[str],
                 loc: str,
                 sop_db: Game_db,
                 kin_db: Game_db,
                 sim_db: Game_db
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
        Element.__id = 0
        self.pert: Perturbator = pert
        self.elements: list[Element] = []
        self.settings: dict[str, Any] = set
        self.rc_tpl: list[str] = rc_tpl
        self.loc: str = loc
        if not os.path.isdir(f'{self.loc}/G{self.id}'):
            os.mkdir(f'{self.loc}/G{self.id}')
        os.chdir(f'{self.loc}/G{self.id}')
        self.sop_db: Game_db = sop_db
        self.kin_db: Game_db = kin_db
        self.sim_db: Game_db = sim_db
        self.generate(n=n)
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
            # Creates an Element from a perturbed SOP and save it in the db
            self.elements.append(Element(sop=self.pert.perturb(sop=self.sop)))
            self.elements[-1].save_sop(db=self.sop_db)

    def run(self) -> None:
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
                                         id=el.id,
                                         name=f'G{self.id}E{el.id}',
                                         loc=f'{self.loc}/G{self.id}',
                                         q_sys=self.qs,
                                         db=self.kin_db)
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
                                 id=el.id,
                                 db=self.sim_db,
                                 gen_id=self.id,
                                 loc=f'{self.loc}/G{self.id}',
                                 q_sys=self.qs,
                                 set=self.settings)
                    el.sim.q_up()
                    el.status = 3
                # Recover simulations data
                elif el.status == 3:
                    all_finished = True
                    for sim in range(len(el.sim.simulations)):
                        el.sim.set_status(sim)
                        if el.sim.status[sim] == 'finished':
                            el.sim.recover_results(sim)
                        else:
                            all_finished = False
                    if all_finished:
                        el.status = 4
                # Scoring
                elif el.status == 4:
                    el.calc_score(settings=self.settings)
            self.qs.run()


