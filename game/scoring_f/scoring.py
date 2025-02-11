from abc import ABC, abstractmethod
from typing import Any
from game.simulation import SIM


class Scoring(ABC):
    """This class cannot be instanciated directly,
    unless all abstract methods are overwritten.
    It is the receipe for a scoring function object that
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

    @property
    @abstractmethod
    def default_score(self) -> None:
        """Default scores used to initialize sops
        """
        pass

    @abstractmethod
    def score(self,
              sim: SIM) -> list[float]:
        return [0.0]
