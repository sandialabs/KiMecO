from game.structure import Structure
from game.rotor import Rotor

class Well:
    """The name is used as identifier."""
    def __init__(self,
                 name: str) -> None:
        
        self.name: str = name
        self.frequencies: list[float] = []
        self.rotors: list[Rotor] = []
    
    def set_structure(self,
                      symbols: str,
                      positions: list) -> None:
        self.structure = Structure(symbols, positions)
    
    def set_frequencies(self,
                        freqs: list[float]) -> None:
        self.frequencies = freqs

    def add_rotor(self,
                  thermalpowermax: float,
                  group: list[int],
                  axis: list[int],
                  symmetry: int,
                  scan: list[float]) -> None:
        
        self.rotors.append(Rotor(thermalpowermax, group, axis, symmetry, scan))