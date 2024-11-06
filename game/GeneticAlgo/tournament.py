from game.GeneticAlgo.ga import GeneticAlgorythm
from game.element import Element
from game.generation import Generation
from game.parameters import SOP
import random


class Tournament(GeneticAlgorythm):
    def converged(self,
                  gen: Generation
                  ) -> bool:
        if gen.best_score < self.settings['score_conv']:
            return True
        else:
            return False

    def next_gen(self, gen: Generation) -> list[Element]:
        """Pair all elements, keep the one with the best score,
        and create a new element from the loser.

        Args:
            gen (Generation): previous generation

        Returns:
            list[Element]: list of elements of the new generation.
        """
        next_gen: list[Element] = []
        random.shuffle(gen.elements)
        for idx, el1 in enumerate(gen.elements[1::2]):
            el2: Element = gen.elements[idx*2]
            if el1.score < el2.score:
                winner: Element = el1
                loser: Element = el2
            else:
                winner: Element = el2
                loser: Element = el1
            # The winner has nothing to calculate
            # But its id must be changed so that each id is unique
            next_gen.append(winner)
            winner.id = idx*2
            next_gen.append(
                Element(sop=self.pert.perturb(sop=loser.sop),
                        id=idx*2+1))
        return next_gen
