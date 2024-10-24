from numpy.typing import NDArray
import numpy as np


class Rotor:
    """Rorot object:
    describe atoms involved in rotor"""
    def __init__(self,
                 ThermalPowerMax: float,
                 group: list[int],
                 axis: list[int],
                 symmetry: int,
                 scan: list[float]) -> None:

        self.ThermalPowerMax: float = ThermalPowerMax
        self.group: list[int] = group
        self.axis: list[int] = axis
        self.symmetry: int = symmetry
        self._scan: NDArray = np.array(scan, dtype=np.float32)
        self.pert = 1.0

    @property
    def scan(self) -> NDArray[np.float32]:
        return self._scan * self.pert
