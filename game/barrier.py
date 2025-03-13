from typing import Any
from game.bimolecular import Bimolecular
from game.well import Well


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
        return 0.01

    @property
    def r_lenergy(self) -> float:
        le: float = self.energy - self.connected[0].energy
        re: float = self.energy - self.connected[1].energy
        return (le - min(le, re) + 0.01)

    @property
    def r_renergy(self) -> float:
        le: float = self.energy - self.connected[0].energy
        re: float = self.energy - self.connected[1].energy
        return (re - min(le, re) + 0.01)

    @property
    def db_dict(self) -> dict[str, Any]:
        db_dict: dict = super(Barrier, self).db_dict
        # Not true for barrierless reactions
        if hasattr(self, 'ifreq'):
            db_dict.update({f"{self.name}__if": float(self.ifreq)})
        return db_dict
