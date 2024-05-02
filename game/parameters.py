import copy
from game.well import Well
from game.bimolecular import Bimolecular
from game.barrier import Barrier

class SOP:
    """Set Of Parameters.
    Main object of the GAME code, to be perturbed and optimized."""
    _id = 0
    def __init__(self) -> None:
        self.set_wells([])
        self.set_bimols([])
        self.set_barriers([])
        self.items: dict = {}
        self.id: int = copy.copy(SOP._id)
        self.sigmas = []
        self.epsilons = []
        SOP._id +=1

    @property
    def r_epsilons(self) -> str:
        eps = ''
        for ep in self.epsilons:
            eps += f" {ep: 5.2f}"
        eps += '\n'
        return eps
    
    @property
    def r_sigmas(self) -> str:
        sigs = ''
        for sig in self.sigmas:
            sigs += f" {sig: 5.2f}"
        sigs += '\n'
        return sigs

    def wells(self) -> list[Well]:
        return self.wells
    
    def set_wells(self,
                  values: list) -> None:
        self.wells = values

    def wells_names(self) -> list:
        names: list = []
        for well in self.wells:
            names.append(well.name)
        return names
            
    def add_new_well(self,
                     name: str) -> None:
        self.items[name] = Well(name)
        self.wells.append(self.items[name])
    
    def bimols(self) -> list[Bimolecular]:
        return self.bimolecular
    
    def set_bimols(self,
                   values: list[Bimolecular]) -> None:
        self.bimolecular = values

    def bimols_names(self) -> list[str]:
        names: list = []
        for bimol in self.bimolecular:
            names.append(bimol.name)
        return names

    def add_new_bimol(self,
                      name: str) -> None:
        self.items[name] = Bimolecular(name)
        self.bimolecular.append(self.items[name])
    
    def barriers(self) -> list[Bimolecular]:
        return self.barriers
    

    def set_barriers(self,
                     values: list[Barrier]) -> None:
        self.barriers = values

    def barriers_names(self) -> list:
        names: list = []
        for bar in self.barriers:
            names.append(bar.name)
        return names
    
    def add_new_barrier(self,
                        name: str,
                        lside: str,
                        rside: str) -> None:
        self.items[name] = Barrier(name,
                                   self.items[lside],
                                   self.items[rside])
        self.barriers.append(self.items[name])

    def set_freqs(self,
                  name: str,
                  freqs: list[float]):
        """Set the frequencies for the item name."""
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].set_frequencies(freqs)
        else:
            self.items[name].set_frequencies(freqs)

    def set_rotor(self,
                  name: str,
                  thermalpowermax: float,
                  group: list[int],
                  axis: list[int],
                  symmetry: int,
                  scan: list[float]) -> int:
        """Set the frequencies for the item name."""
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].add_rotor(thermalpowermax,
                                                     group,
                                                     axis,
                                                     symmetry,
                                                     scan)
            return len(self.items[name].fragments[-1].rotors)-1
        else:
            self.items[name].add_rotor(thermalpowermax,
                                       group,
                                       axis,
                                       symmetry,
                                       scan)
            return len(self.items[name].rotors)-1
            
    def set_structure(self,
                      name: str,
                      symbols: str,
                      geom: list[list[float]]) -> None:
        """Set the structure for the item name."""
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].set_structure(symbols,
                                                     geom)
        else:
            self.items[name].set_structure(symbols,
                                       geom)
            
    def set_energy(self,
                   name: str,
                   energy: float):
        """Set the energy of the structure associated with name"""
        self.items[name].set_energy(energy)

    def save_tunnelling(self, name, ifreq, coff, well_depth):
        pass
        



    