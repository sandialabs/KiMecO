from game.bimolecular import Bimolecular
from game.well import Well
from game.structure import Structure


class Barrier(Well):
    """A barrier connect a well to
    a bimolecular prod, or another well"""
    def __init__(self, name: str,
                 lside: Well|Bimolecular,
                 rside: Well|Bimolecular) -> None:
        
        super().__init__(name)
        self.connected: list[Well|Bimolecular] = [lside, rside]
    
    @property
    def r_energy(self) -> float:
        return self._energy
    
    @property
    def energy(self) -> float:
        return self._energy

    def set_energy(self, value: float) -> None:
        self._energy = value

    def set_ifreq(self, value: float) -> None:
        self.ifreq = value

    @property
    def r_ifreq(self) -> float:
        return self.ifreq
    
    @property
    def r_coff(self) -> float:
        return min(self.connected[0].energy, self.connected[1].energy)
    
    @property
    def r_lenergy(self) -> float:
        return self.energy - self.connected[0].energy
    
    @property
    def r_renergy(self) -> float:
        return self.energy - self.connected[1].energy
    
