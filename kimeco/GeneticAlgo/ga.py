from abc import ABC, abstractmethod
from typing import Any
from kimeco.generation import Generation
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.scoring_f.scoring import Scoring
from kimeco.database.sop_db import SOP_DB
from kimeco.parameters import SOP
import numpy as np
from numpy.typing import NDArray
from kimeco.element import Element, ElementStatus


class GeneticAlgorithm(ABC):
    """This class cannot be instanciated directly,
    unless all abstract methods are overwritten.
    It is the receipe for a GA object that
    should be inherited by those.

    Args:
        ABC (metaclass): Make the Scoring class abstract.
    """
    def __init__(self,
                 settings: dict[str, Any],
                 sf: Scoring,
                 pert: Perturbator,
                 sop_db: SOP_DB
                 ) -> None:
        self.settings: dict[str, Any] = settings
        self.pert: Perturbator = pert
        self.sf: Scoring = sf
        self.sop_db = sop_db
        self.losers: NDArray = np.zeros(
            shape=(
                self.settings['n_elem'],
                len(self.sop_db.columns)+1))

    @abstractmethod
    def converged(self,
                  gen: Generation
                  ) -> bool:
        """Decide if a generation is converged or no
        depending on the algorythm criteria.

        Args:
            gen (Generation): Previous generation

        Returns:
            bool: whether is converged
        """
        pass

    @abstractmethod
    def create_next_gen(self,
                        gen: Generation
                        ) -> tuple[dict[int, Element], list[Element]]:
        """Return the list of elements of the next generation.
        Important: reset the Element.__id before creating
        the elements.

        Args:
            gen (Generation): previous generation

        Returns:
            list[Element]: Elements for the next generation
        """
        pass

    def get_next_gen(self,
                     gen: Generation
                     ) -> tuple[dict[int, Element], list[Element]]:
        """Returns the elements of the next generation.
        If they are already in db, does not trigger the GA.

        Args:
            gen (Generation): Kimeco generation object

        Returns:
            _type_: _description_
        """
        rows = self.sop_db.get_table(table=f"G{gen.id+1:04d}")
        if len(rows) == int(self.settings['nelem']/2) and\
           self.settings['restart'] == 'default':
            next_gen: list[Element] = []
            prev_gen: dict[int, Element] = {}
            self.losers = np.array(rows)
            for el in gen.elements:
                if el.id in self.losers[:, 0]:
                    next_gen.append(Element(
                        sop=SOP.from_db_row(
                            sop_tpl=gen.elements[0].sop,
                            row=self.losers[[self.losers[:, 0] == el.id], 1:])
                            )
                            )
                    next_gen[-1].status = ElementStatus.DONE
                else:
                    next_gen.append(el)
        else:
            prev_gen, next_gen = self.create_next_gen(gen)
        return prev_gen, next_gen
