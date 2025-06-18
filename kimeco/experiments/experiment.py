from kimeco.scoring_f.scoring import Scoring
from abc import ABC, abstractmethod
from typing import Any


class Experiment(ABC):
    """Experiment object with associated
    experimental conditions and scoring function.
    """
    def __init__(self,
                 temp: float,
                 pres: float,
                 composition: dict[str, float],
                 scoring: Scoring,
                 sim_file: str,
                 settings: dict[str, Any]) -> None:
        """Experiments need conditions,
        composition and scoring method.
        The files for the data should depend on the experiment.

        Args:
            temp (float): Temperature (K)
            pres (float): Pressure (Pa)
            composition (dict[str, float]):
                str: Species name
                float: Initial molar fraction
            scoring (Scoring): Scoring
        """
        self.T: float = temp
        self.P: float = pres
        self.X: dict[str, float] = composition
        self.sf: Scoring = scoring
        self.sim_file: str = sim_file
        self.settings: dict[str, Any] = settings

    @abstractmethod
    def read_data(self,
                  file: str) -> None:
        """Read experimental data from file

        Args:
            file (str): path to experimental data file
        """
        pass
