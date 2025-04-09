from copy import deepcopy
from kimeco.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.element import Element
from kimeco.generation import Generation
import random


class Tournament(GeneticAlgorithm):
    def converged(self,
                  gen: Generation
                  ) -> bool:
        if gen.best_score < self.settings['score_conv']:
            return True
        else:
            return False

    def next_gen(self,
                 gen: Generation
                 ) -> tuple[dict[int, Element], list[Element]]:
        """Pair all elements, keep the one with the best score,
        and create a new element from the loser.

        Args:
            gen (Generation): previous generation

        Returns:
            list[Element]: list of elements of the new generation.
        """
        # Change the intensity of the perturbation
        self.pert.set_gen_fact(gen=gen.id)
        next_gen: list[Element] = gen.elements
        prev_gen: dict[int, Element] = {}
        random.shuffle(gen.elements)
        half = int(len(gen.elements)/2)
        for idx, el1 in enumerate(gen.elements[1:half]):
            el2: Element = gen.elements[idx+half]
            if el1.score < el2.score:
                winner: Element = el1
                loser: Element = el2
            else:
                winner: Element = el2
                loser: Element = el1
            prev_gen[loser.id] = winner
            next_gen[loser.id] = Element(
                sop=self.pert.perturb(sop=winner.sop),
                id=loser.id,
                sf=self.sf,
                gen=gen.id+1)
        return prev_gen, next_gen
