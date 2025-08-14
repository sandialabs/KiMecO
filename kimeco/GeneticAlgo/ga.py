from abc import ABC, abstractmethod
from typing import Any
from kimeco.generation import Generation
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.scoring_f.scoring import Scoring
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
import numpy as np
from numpy.typing import NDArray


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
        self.sop_db: SOP_DB = sop_db
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

