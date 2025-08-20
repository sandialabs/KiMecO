from logging import Logger
from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.element import Element
from kimeco.generation import Generation
import random
import numpy as np
from numpy.typing import NDArray
from typing import Any
from kimeco.scoring_f.scoring import Scoring
import time


class Exponential(GeneticAlgorithm):
    def __init__(self,
                 settings: dict[str, Any],
                 sf: Scoring,
                 pert: Perturbator,
                 sop_db: SOP_DB,
                 sim_db: SIM_DB,
                 kin_db: KIN_DB,
                 f_el: Element,
                 input_tpl: list[str],
                 location: str,
                 klog: Logger) -> None:
        super().__init__(
            settings=settings,
            sf=sf,
            pert=pert,
            input_tpl=input_tpl,
            location=location,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            f_el=f_el,
            klog=klog)
        self.name = 'Exponential'

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
        new_els = 0
        gen_len: int = len(gen.elements)
        available_ids: list[int] = [i for i in range(gen_len)]
        scores: NDArray = np.array([el.score for el in gen.elements])
        child_prob: NDArray = np.exp(
            (np.min(scores) - scores)/np.median(scores)
            )
        idxs = range(gen_len)
        # Always keep the best element
        best_idx: int = int(np.where(max(child_prob) == child_prob)[0][0])
        to_perturb: dict[int, int] = {best_idx: 1}
        idx: int = random.choice(idxs)
        next_gen = []
        selected = 2  # Best element already in to_perturb
        # Switch focus on good score as gen.id increases
        std: float = np.exp(1-(np.sqrt(gen.id)/2))/2
        # Select the source of all elements for next gen
        while selected < gen_len:
            rng: float = np.random.normal(1, std)
            # Add the element from previous gen and one perturbed version
            if rng < child_prob[idx]:
                if idx not in to_perturb:
                    if selected < gen_len - 1:
                        to_perturb[idx] = 1
                        selected += 2
                    idx = random.choice(idxs)
                # Then perturb it if selected again
                else:
                    to_perturb[idx] += 1
                    selected += 1
                    idx = random.choice(idxs)
                # otherwise try another
            else:
                idx = random.choice(idxs)
        next_gen: list[Element] = gen.elements
        prev_gen: dict[int, Element] = {}
        # Remove the selected elements from the available ids
        for el_id in to_perturb:
            if el_id in available_ids:
                available_ids.pop(available_ids.index(el_id))
                prev_gen[el_id] = next_gen[el_id]
        # Perturb n times the selected elements
        for el_id, n_perturb in to_perturb.items():
            for i in range(n_perturb):
                new_el_id: int = available_ids.pop(-1)
                prev_gen[new_el_id] = next_gen[el_id]
                next_gen[new_el_id] = Element(
                    sop=self.pert.perturb(sop=next_gen[el_id].sop),
                    id=new_el_id,
                    gen=gen.id+1)
                new_els += 1
        msg: str = f'{new_els} new elements created.'
        self.klog.info(msg)
        end_time: float = time.time()
        runtime: float = end_time - start_time
        message: str = f'Time to create next generation: {runtime:.2f}s'
        self.klog.info(message)
        return prev_gen, next_gen
