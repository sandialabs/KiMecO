from typing import Any
from game.structure import Structure
from game.rotor import Rotor

class Well:
    """The name is used as identifier."""
    def __init__(self,
                 name: str) -> None:
        
        self.name: str = name
        self.frequencies: list[float] = []
        self.rotors: list[Rotor] = []

    def __getattr__(self, name: str) -> Any:
        if "r_scan" in name:
            try:
                idx = int(name.split('(')[1].split(')')[0])
                return self.r_scan(idx)
            except:
                raise AttributeError(f'Well does not have the attribute {name}')
        else:
            self.__getattribute__(name)

    @property
    def r_name(self) -> str:
        return self.name
    
    @property
    def r_energy(self) -> float:
        return self.structure.energy
    
    @property
    def energy(self) -> float:
        return self.structure.energy
    
    def set_energy(self, value: float) -> None:
        self.structure.energy = value

    @property
    def r_struct(self) -> str:
        struct = ''
        for idx in range(len(self.structure)):
            atm: str = self.structure.symbols[idx]
            x: float = self.structure.positions[idx][0]
            y: float = self.structure.positions[idx][1]
            z: float = self.structure.positions[idx][2]
            struct += f'{atm} {x} {y} {z}' + '\n'
        return struct
    
    @property
    def r_freq(self) -> str:
        freq = ''
        freq_in_line = 0
        for val in self.frequencies:
            freq += f'{val: 9.3f}'
            freq_in_line += 1
            if freq_in_line == 4:
                freq += '\n'
                freq_in_line = 0
        freq += '\n'
        return freq
    
    def r_scan(self, rot_num) -> str:
        scan = ''
        for val in self.rotors[rot_num].scan:
            scan += f'{val: 7.3f}'
        scan += '\n'
        return scan
    
    
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