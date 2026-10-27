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
                 fcoef: list[float],
                 geo=None,
                 spline_angles: list[float] | None = None) -> None:

        self.ThermalPowerMax: float = ThermalPowerMax
        # Optional rotor-specific geometry (angstrom rows [sym, x, y, z])
        self.geo = geo
        self.group: list[int] = group
        self.axis: list[int] = axis
        self.symmetry: int = symmetry
        self._scan: NDArray = np.array(scan, dtype=np.float32)
        self.pert = 1.0
        self.fexp: list[int] = fexp
        self.fcoef: list[float] = fcoef
        # Torsion angles (degrees) of a MESS ``PotentialSpline`` rotor, one
        # per energy of the scan. None for a ``Potential[kcal/mol]`` rotor,
        # whose energies lie on an implicit, equally spaced angle grid.
        self.spline_angles: list[float] | None = (
            [float(angle) for angle in spline_angles]
            if spline_angles is not None else None)
        self.fourier = False
        if len(self._scan) == 0:
            self.fourier = True

    @property
    def scan(self) -> NDArray[np.float32]:
        return (self._scan * self.pert).astype(np.float32)

    @property
    def is_spline(self) -> bool:
        """True when the rotor was read from a ``PotentialSpline`` block."""
        return self.spline_angles is not None

    def same_definition(self, other: 'HinRotor') -> bool:
        """Tell whether ``other`` describes exactly the same rotor.

        Every value read from the MESS input is compared (thermal power,
        group, axis, symmetry, scan energies, Fourier expansion, rotor
        geometry and spline angles); the perturbation ``pert`` is not, as it
        is not read from the input.

        Args:
            other (HinRotor): rotor to compare with.

        Returns:
            bool: True when both rotors have the same definition.
        """
        return (self.ThermalPowerMax == other.ThermalPowerMax
                and self.group == other.group
                and self.axis == other.axis
                and self.symmetry == other.symmetry
                and np.array_equal(self._scan, other._scan)
                and self.fexp == other.fexp
                and self.fcoef == other.fcoef
                and self.geo == other.geo
                and self.spline_angles == other.spline_angles)
