from abc import ABC, abstractmethod
from typing import Any
from kimeco.simulation import SIM
from numpy.typing import NDArray


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

    def score_experiment(self,
                         sim_profile: NDArray,
                         exp: Any) -> float:
        """Score a single experiment profile.

        Implementations can override this to support per-experiment scoring
        while legacy callers continue using `score(sim=...)`.
        """
        raise NotImplementedError
