import copy
from game.well import Well
from game.bimolecular import Bimolecular
from game.barrier import Barrier

class SOP:
    """Set Of Parameters.
    Main object of the GAME code, to be perturbed and optimized."""
    _id = 0
    def __init__(self) -> None:
        self.wells: list[Well] = []
        self.bimolecular: list[Bimolecular] = []
        self.barrier: list[Barrier] = []
        self.items: dict = {}
        SOP._id +=1

    @property
    def wells(self) -> list[Well]:
        return self.wells
    
    @wells.setter
    def wells(self, values: list) -> None:
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
    
    @property
    def bimols(self) -> list[Bimolecular]:
        return self.bimolecular
    
    @bimols.setter
    def bimols(self,
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
    
    @property
    def barriers(self) -> list[Bimolecular]:
        return self.barriers
    
    @barriers.setter
    def barriers(self,
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
                                   copy.deepcopy(self.items[lside]),
                                   copy.deepcopy(self.items[rside]))
        self.barriers.append(self.items[name])

    def set_freqs(self,
                  name: str,
                  freqs: list[float]):
        """Set the frequencies for the item name."""
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].frequencies(freqs)
        else:
            self.items[name].frequencies(freqs)

    def set_rotor(self,
                  name: str,
                  thermalpowermax: float,
                  group: list[int],
                  axis: list[int],
                  symmetry: int,
                  scan: list[float]) -> None:
        """Set the frequencies for the item name."""
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].add_rotor(thermalpowermax,
                                                     group,
                                                     axis,
                                                     symmetry,
                                                     scan)
        else:
            self.items[name].add_rotor(thermalpowermax,
                                       group,
                                       axis,
                                       symmetry,
                                       scan)
            
    def set_structure(self,
                      name: str,
                      symbols: str,
                      geom: list[list[float]]) -> None:
        """Set the structure for the item name."""
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].structure(symbols,
                                                     geom)
        else:
            self.items[name].structure(symbols,
                                       geom)


    