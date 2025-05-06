from numpy.typing import NDArray
import numpy as np


class InternalRotation:
    """Hindered Rotor object:
    describe atoms involved in rotor"""
    def __init__(self,
                 group: list[int],
                 axis: list[int],
                 symmetry: int,
                 massexpansionsize: int,
                 potentialexpansionsize: int,
                 hamiltonsizemin: int,
                 hamiltonsizemax: int,
                 gridsize: int) -> None:
        self.group: list[int] = group
        self.axis: list[int] = axis
        self.symmetry: int = symmetry
        # MassExpansionSize
        self.mes: int = massexpansionsize
        # PotentialExpansionSize
        self.pes: int = potentialexpansionsize
        self.hamiltonsizemin: int = hamiltonsizemin
        self.hamiltonsizemax: int = hamiltonsizemax
        self.gridsize: int = gridsize
