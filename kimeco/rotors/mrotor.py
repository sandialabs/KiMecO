from kimeco.rotors.internalrotation import InternalRotation


class MultiRotor:
    """Multiple coupled rotors object:
    describe atoms involved in rotor"""
    def __init__(self,
                 symmetryFactor: float,
                 interpolationEnergyMax: float,
                 potentialEnergySurface: str,
                 quantumLevelEnergyMax: float,
                 internal_rot: list[InternalRotation]) -> None:

        self._sf: float = symmetryFactor
        self.sfc: float = 1.0
        self.iem: float = interpolationEnergyMax
        self.file: str = potentialEnergySurface
        self.qlem: float = quantumLevelEnergyMax
        self.internal_rot: list[InternalRotation] = internal_rot

    @property
    def symFact(self):
        return self._sf * self.sfc
