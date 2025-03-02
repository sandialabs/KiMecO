from game.GeneticAlgo.ga import GeneticAlgorithm
from game.element import Element
from game.generation import Generation
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
        next_gen: list[Element] = []
        prev_gen: dict[int, Element] = {}
        random.shuffle(gen.elements)
        for idx, el1 in enumerate(gen.elements[1::2]):
            el2: Element = gen.elements[idx*2]
            if el1.score < el2.score:
                winner: Element = el1
            else:
                winner: Element = el2
            # The winner has nothing to calculate
            # But its id must be changed so that each id is unique
            next_gen.append(winner)
            winner.id = idx*2  # Change the ID of the winner to keep it unique
            prev_gen[idx*2+1] = winner
            next_gen.append(
                Element(sop=self.pert.perturb(sop=winner.sop),
                        id=idx*2+1,
                        sf=self.sf))
        return prev_gen, next_gen
