from abc import ABC, abstractmethod
from typing import Any
from game.element import Element
from game.generation import Generation
from game.perturbator import Perturbator


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
                 **kwargs
                 ) -> None:
        self.settings: dict[str, Any] = settings
        self.kwargs: dict[str, Any] = kwargs
        self.pert = Perturbator(settings=settings)

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
    def next_gen(self,
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
