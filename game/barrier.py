from typing import Any
from game.bimolecular import Bimolecular
from game.well import Well
import numpy as np


class Barrier(Well):
    """A barrier connect a well to
    a bimolecular prod, or another well"""
    def __init__(self, name: str,
                 lside: Well | Bimolecular,
                 rside: Well | Bimolecular) -> None:

        super().__init__(name=name)
        self.connected: list[Well | Bimolecular] = [lside, rside]
        self.energy: float
        self.ifreq: float
        self.barrierless: bool = False

    @property
    def r_coff(self) -> float:
        return min(self.r_lenergy, self.r_renergy)

    @property
    def r_lenergy(self) -> float:
        return self.energy - self.connected[0].energy

    @property
    def r_renergy(self) -> float:
        return self.energy - self.connected[1].energy

    @property
    def db_dict(self) -> dict[str, Any]:
        db_dict: dict = {
            f"{self.name}_e": self.energy,
            f"{self.name}_f": np.array(self.frequencies, dtype=np.float32),
            f"{self.name}_r": np.array(self.rotors_pert, dtype=np.float16),
            f"{self.name}_if": self.ifreq
        }
        return db_dict
