from kimeco.scoring_f.scoring import Scoring
from kimeco.logger_config import KMOLogger
from abc import ABC, abstractmethod
from typing import Any
from numpy.typing import NDArray


class Experiment(ABC):
    """Experiment object with associated
    experimental conditions and scoring function.
    """
    __id = 0

    @classmethod
    def total(cls) -> int:
        """Return the total number of Generation instances."""
        return cls.__id

    def __init__(self,
                 temp: float,
                 pres: float,
                 composition: dict[str, float],
                 scoring: Scoring,
                 sim_file: str,
                 settings: dict[str, Any],
                 klog: KMOLogger,
                 species: list[str],
                 weight: float = 1.0) -> None:
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
        self.id = Experiment.__id
        Experiment.__id += 1
        self.T: float = temp
        self.P: float = pres
        self.X: dict[str, float] = composition
        self.sf: Scoring = scoring
        self.sim_file: str = sim_file
        self.settings: dict[str, Any] = settings
        self.klog: KMOLogger = klog
        self.score: float = float('inf')
        self.weight: float = 1.0
        self.species: list[str] = species
        self.weight = weight
        self.sp_weights: NDArray | None = None
        self.data: NDArray | None = None
        self.error: NDArray | None = None
        self.sf: Scoring = scoring

    @staticmethod
    @abstractmethod
    def read_data(file: str) -> tuple[list[str], NDArray]:
        """Read experimental data from file

        Args:
            file (str): path to experimental data file
        """
        pass

    def check_template(self,
                       keywords: list[str]) -> None:
        """Check if the template contains the required keywords

        Args:
            keywords (list[str]): List of required keywords
        """
        kdict: dict[str, str] = {key: 'val' for key in keywords}
        try:
            _ = self.sim_file.format(**kdict)
        except Exception as e:
            self.klog.error(f"Error checking template {self.sim_file}")
            self.klog.error(f"Necessary keywords: {keywords}")
            self.klog.error(f"Exception: {e}")
            raise e

    def compute_score(self,
                      sim_profile: NDArray) -> float:
        """Compute score for this experiment only.

        Args:
            sim_profile (NDArray): Simulated profile with row 0 = time and
                subsequent rows = species concentrations.

        Returns:
            float: scalar score for this experiment.
        """
        if hasattr(self.sf, 'score_experiment'):
            return float(self.sf.score_experiment(sim_profile, self))
        raise NotImplementedError(
            "Scoring function does not implement per-experiment scoring"
        )
# End of file
