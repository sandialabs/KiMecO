from kimeco.logger_config import KMOLogger
from abc import ABC, abstractmethod
from typing import Any
from numpy.typing import NDArray

name_base = "exp"


class Experiment(ABC):
    """Experiment object with associated
    experimental conditions.
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
                 sim_file: str,
                 settings: dict[str, Any],
                 klog: KMOLogger,
                 species: list[str],
                 new_tpl: bool,
                 tpl_idx: int = 0,
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
        """
        self.id = Experiment.__id
        Experiment.__id += 1
        self.name = f"{name_base}_{self.id:03d}"
        self.T: float = temp
        self.P: float = pres
        self.X: dict[str, float] = composition
        self.sim_file: str = sim_file
        self.settings: dict[str, Any] = settings
        self.klog: KMOLogger = klog
        self.score: float = float('inf')
        self.weight: float = 1.0
        self.species: list[str] = species
        self.weight = weight
        self.data: NDArray | None = None
        self.error: NDArray | None = None
        self.new_tpl: bool = new_tpl
        self.tpl_idx: int = tpl_idx

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

