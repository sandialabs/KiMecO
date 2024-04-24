from game.structure import Structure
from game.rotor import Rotor

class Well:
    """The name is used as identifier."""
    def __init__(self,
                 name: str) -> None:
        
        self.name: str = name
        self.frequencies: list[float] = []
        self.rotors: list[Rotor] = []

    @property
    def structure(self) -> Structure:
        return self.structure
    
    @structure.setter
    def structure(self,
                  symbols: str,
                  positions: list) -> None:
        self.structure = Structure(symbols, positions)

    @property
    def energy(self) -> float:
        return self.structure.energy
    
    @energy.setter
    def energy(self,
               value: float) -> None:
        self.structure.energy = value

    @property
    def frequencies(self) -> list:
        return self.frequencies
    
    @frequencies.setter
    def frequencies(self,
                    freqs: list[float]) -> None:
        self.frequencies = freqs

    def add_rotor(self,
                  thermalpowermax: float,
                  group: list[int],
                  axis: list[int],
                  symmetry: int,
                  scan: list[float]) -> None:
        
        self.rotors.append(Rotor(thermalpowermax, group, axis, symmetry, scan))