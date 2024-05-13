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
        SOP._id += 1

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

    @property
    def r_rc_temp(self) -> str:
        temps = ""
        for temp in self.rc_temp:
            temps += f" {temp: 7.1f}"
        temps += '\n'
        return temps

    @property
    def r_rc_pres(self) -> str:
        press = ""
        for pres in self.rc_pres:
            press += f" {pres: 7.1f}"
        press += '\n'
        return press

    def set_wells(self,
                  values: list[Well]) -> None:
        """Save a list of wells object for the SOP

        Args:
            values (list[Well]): list of wells object
        """
        self.wells = values

    def wells_names(self) -> list[str]:
        """Return the names of all the wells

        Returns:
            list[str]: list of wells' name
        """
        names: list = []
        for well in self.wells:
            names.append(well.name)
        return names

    def add_new_well(self,
                     name: str) -> None:
        """Procedure to create a new Well

        Args:
            name (str): Well's name
        """
        self.items[name] = Well(name)
        self.wells.append(self.items[name])

    # def bimols(self) -> list[Bimolecular]:
    #     """list of all Bimolecular objects in the SOP

    #     Returns:
    #         list[Bimolecular]: list of all Bimolecular objects in the SOP
    #     """
    #     return self.bimolecular

    def set_bimols(self,
                   values: list[Bimolecular]) -> None:
        """Save a list of Bimolecular objects in the SOP

        Args:
            values (list[Bimolecular]): list of Bimolecular objects
        """
        self.bimolecular = values

    def bimols_names(self) -> list[str]:
        """List of names of all the bimolecular objects

        Returns:
            list[str]: List of names of all the bimolecular objects
        """
        names: list = []
        for bimol in self.bimolecular:
            names.append(bimol.name)
        return names

    def add_new_bimol(self,
                      name: str) -> None:
        """Procedure to create a new bimolecular object

        Args:
            name (str): name of the bimolecular object
        """
        self.items[name] = Bimolecular(name)
        self.bimolecular.append(self.items[name])

    # def barriers(self) -> list[Bimolecular]:
    #     return self.barriers

    def set_barriers(self,
                     values: list[Barrier]) -> None:
        """Set the list of Barrier objects of the SOP

        Args:
            values (list[Barrier]): list of barrier objects
        """
        self.barriers = values

    def barriers_names(self) -> list:
        """Returns the names of all barrier objects in the SOP

        Returns:
            list: list of names of all barrier objects in the SOP
        """
        names: list = []
        for bar in self.barriers:
            names.append(bar.name)
        return names

    def add_new_barrier(self,
                        name: str,
                        lside: str,
                        rside: str) -> None:
        """Procedure to add a new barrier in the SOP

        Args:
            name (str): name of the Barrier object
            lside (str): name of the reactant
            rside (str): name of the product
        """
        self.items[name] = Barrier(name,
                                   self.items[lside],
                                   self.items[rside])
        self.barriers.append(self.items[name])

    def set_freqs(self,
                  name: str,
                  freqs: list[float]):
        """Set the frequencies for the item name.

        Args:
            name (str): name of the object for which to set the frequencies
            freqs (list[float]): list of frequencies (cm-1)
        """
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
        """Create a new rotor object for a well

        Args:
            name (str): name of the well
            thermalpowermax (float): thermalpowermax
            group (list[int]): group
            axis (list[int]): axis
            symmetry (int): symmetry
            scan (list[float]): list of energies (kcal/mol) describing the
                                rotor's rotation

        Returns:
            int: Index of the last rotor of the well
        """
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
        """Set the structure for the item name.

        Args:
            name (str): name of the item
            symbols (str): Chemical elements
            geom (list[list[float]]): 3D geometry
        """
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].set_structure(symbols,
                                                         geom)
        else:
            self.items[name].set_structure(symbols,
                                           geom)

    def set_energy(self,
                   name: str,
                   energy: float):
        """Call the set energy method of the relevant object

        Args:
            name (str): name of the object
            energy (float): energy (kcal/mol)
        """
        self.items[name].set_energy(energy)

    def save_tunnelling(self, name, ifreq, coff, well_depth):
        pass
