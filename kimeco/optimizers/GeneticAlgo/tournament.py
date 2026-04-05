import time

from kimeco.logger_config import KMOLogger
from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.element import Element
from kimeco.generation import Generation
import random
from typing import Any
from kimeco.scoring_f.scoring import Scoring


class Tournament(GeneticAlgorithm):
    def __init__(self,
                 settings: dict[str, Any],
                 sf: Scoring,
                 pert: Perturbator,
                 sop_db: SOP_DB,
                 sim_db: SIM_DB,
                 kin_db: KIN_DB,
                 f_el: Element,
                 input_tpls: list[list[str]],
                 klog: KMOLogger) -> None:
        super().__init__(
            settings=settings,
            sf=sf,
            pert=pert,
            input_tpls=input_tpls,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            f_el=f_el,
            klog=klog)
        self.name = 'Tournament'

    def isconverged(self,
                    gen: Generation
                    ) -> bool:
        if gen.best_score < self.settings['score_conv']:
            return True
        else:
            return False

    def create_next_gen(self,
                        gen: Generation
                        ) -> tuple[dict[int, Element], list[Element]]:
        """Pair all elements, keep the one with the best score,
        and create a new element from the loser.

        Args:
            gen (Generation): previous generation

        Returns:
            list[Element]: list of elements of the new generation.
        """
        start_time: float = time.time()
        # Change the intensity of the perturbation
        next_gen: list[Element] = gen.elements
        # shuffled: list[Element] = copy.copy(gen.elements)
        shuffled: list[int] = [i for i in range(len(next_gen))]
        # Safe guard
        for i in shuffled:
            if i != next_gen[i].id:
                raise AttributeError(
                    f'The elements of Generation {gen.id} are not ordered!')
        random.shuffle(shuffled)
        prev_gen: dict[int, Element] = {}
        half = int(len(shuffled)/2)
        for idx in range(len(shuffled[:half])):
            el1: Element = next_gen[shuffled[idx]]
            el2: Element = next_gen[shuffled[idx+half]]
            if el1.score < el2.score:
                winner: Element = el1
                loser: Element = el2
            else:
                winner: Element = el2
                loser: Element = el1
            # Prev gen saves the winners from which a new element is created.
            prev_gen[loser.id] = next_gen[winner.id]
            next_gen[loser.id] = Element(
                sop=self.pert.perturb(sop=winner.sop),
                id=loser.id,
                gen=gen.id+1)
            end_time: float = time.time()
            runtime: float = end_time - start_time
            message: str = f'Time to create next generation: {runtime:.2f}s'
            self.klog.info(message)
        return prev_gen, next_gen
