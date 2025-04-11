from typing import Any
from kimeco.bimolecular import Bimolecular
from kimeco.well import Well
import numpy as np
from numpy.typing import NDArray


class Barrier(Well):
    """A barrier connect a well to
    a bimolecular prod, or another well"""
    def __init__(self, name: str,
                 lside: Well | Bimolecular,
                 rside: Well | Bimolecular) -> None:

        super().__init__(name=name)
        self.connected: list[Well | Bimolecular] = [lside, rside]
        self._energy: float
        self.ifreq: float
        self._symFact: float
        self.sf_p: float = 1.0
        self.barrierless: bool = False

    @property
    def symFact(self):
        return self._symFact * self.sf_p

    @property
    def frequencies(self) -> NDArray[Any]:
        if not self.barrierless:
            freq: NDArray = super(Barrier, self).frequencies
        else:
            tmp = []
            for side in self.connected:
                if isinstance(side, Bimolecular):
                    tmp.extend(side.fragments[0].frequencies.tolist())
                    tmp.extend(side.fragments[1].frequencies.tolist())
                    break
            freq: NDArray = np.array(tmp)
        return freq

    @property
    def energy(self):
        if self.barrierless:
            return max(self.connected[0].energy,
                       self.connected[1].energy)
        else:
            return self._energy

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
        # barrierless are not perturbed
        if self.barrierless:
            return {f"{self.name}__sf_p": float(self.symFact)}
        db_dict: dict = super(Barrier, self).db_dict
        db_dict.update({f"{self.name}__if": float(self.ifreq)})

        return db_dict
