from game.bimolecular import Bimolecular
from game.well import Well


class Barrier(Well):
    """A barrier connect a well to
    a bimolecular prod, or another well"""
    def __init__(self, name: str,
                 lside: Well | Bimolecular,
                 rside: Well | Bimolecular) -> None:

        super().__init__(name)
        self.connected: list[Well | Bimolecular] = [lside, rside]

    @property
    def r_energy(self) -> float:
        return self._energy

    @property
    def energy(self) -> float:
        return self._energy

    def set_energy(self, value: float) -> None:
        """Simple function to be coherent with other objects

        Args:
            value (float): energy of the object (kcal/mol)
        """
        self._energy = value

    def set_ifreq(self, value: float) -> None:
        """Set the imaginary frequency of this barrier

        Args:
            value (float): imaginary frequency (cm-1)
        """
        self.ifreq = value

    @property
    def r_ifreq(self) -> float:
        return self.ifreq

    @property
    def r_coff(self) -> float:
        return min(self.r_lenergy, self.r_renergy)

    @property
    def r_lenergy(self) -> float:
        return self.energy - self.connected[0].energy

    @property
    def r_renergy(self) -> float:
        return self.energy - self.connected[1].energy
