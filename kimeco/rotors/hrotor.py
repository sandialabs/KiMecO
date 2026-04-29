from numpy.typing import NDArray
import numpy as np


class HinRotor:
    """Hindered Rotor object:
    describe atoms involved in rotor"""
    def __init__(self,
                 ThermalPowerMax: float,
                 group: list[int],
                 axis: list[int],
                 symmetry: int,
                 scan: list[float],
                 fexp: list[int],
                 fcoef: list[float]) -> None:

        self.ThermalPowerMax: float = ThermalPowerMax
        self.group: list[int] = group
        self.axis: list[int] = axis
        self.symmetry: int = symmetry
        self._scan: NDArray = np.array(scan, dtype=np.float32)
        self.pert = 1.0
        self.fexp: list[int] = fexp
        self.fcoef: list[float] = fcoef
        self.fourier = False
        if len(self._scan) == 0:
            self.fourier = True

    @property
    def scan(self) -> NDArray[np.float32]:
        return (self._scan * self.pert).astype(np.float32)
