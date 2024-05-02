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
    def r_name(self):
        return self.name
    
    @property
    def r_struct(self):
        struct = ''
        for idx in range(len(self.structure)):
            atm = self.structure.symbols[idx]
            x = self.structure.positions[idx][0]
            y = self.structure.positions[idx][1]
            z = self.structure.positions[idx][2]
            struct += f'{atm} {x} {y} {z}' + '\n'
        return struct
    
    @property
    def r_freq(self):
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
    
    def r_scan(self, rot_num):
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