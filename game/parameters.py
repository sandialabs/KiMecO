import copy
from typing import Any

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
        self.barriers: list[Barrier] = []
        self.id: int = copy.copy(SOP._id)
        self.items: dict = {}
        self.power: float
        self.factor: float
        self.sigmas: list[float] = []
        self.rc_temp: list[float]
        self.rc_pres: list[float]
        self.ct_names: dict[str, str]
        self.epsilons: list[float] = []
        SOP._id += 1

    def __repr__(self) -> str:
        table_repr: str = "<SOP("
        for v in self.parameters_names.values():
            table_repr += f"'{v}',"
        return table_repr[:-1] + ")>"

    @property
    def r_epsilons(self) -> str:
        eps = ''
        for ep in self.epsilons:
            eps += f" {ep: 7.4f}"
        eps += '\n'
        return eps

    @property
    def r_sigmas(self) -> str:
        sigs = ''
        for sig in self.sigmas:
            sigs += f" {sig: 7.4f}"
        sigs += '\n'
        return sigs

    @property
    def r_rc_temp(self) -> str:
        temps = ""
        for temp in self.rc_temp:
            temps += f" {temp: 8.2f}"
        temps += '\n'
        return temps

    @property
    def r_rc_pres(self) -> str:
        press = ""
        for pres in self.rc_pres:
            press += f" {pres: 8.2f}"
        press += '\n'
        return press

    @property
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
        if name in self.ct_names:
            if self.ct_names[name] == "":
                self.ct_names[name] = name
        else:
            self.ct_names[name] = name
        ct_name: str = self.ct_names[name]
        self.items[name] = Well(name=name, ct_name=ct_name)
        self.wells.append(self.items[name])

    @property
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
        self.items[name] = Bimolecular(name, self.ct_names)
        self.bimolecular.append(self.items[name])

    @property
    def barriers_names(self) -> list:
        """Returns the names of all barrier objects in the SOP

        Returns:
            list: list of names of all barrier objects in the SOP
        """
        names: list = []
        for bar in self.barriers:
            names.append(bar.name)
        return names

    @property
    def parameters_names(self) -> dict[str, Any]:
        pn: dict[str, Any] = {}
        for well in self.wells:
            pn.update(well.db_dict)
        for bar in self.barriers:
            pn.update(bar.db_dict)
        for bim in self.bimolecular:
            pn.update(bim.db_dict)

        return pn

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
        self.items[name] = Barrier(name=name,
                                   lside=self.items[lside],
                                   rside=self.items[rside])
        self.barriers.append(self.items[name])

    def set_freqs(self,
                  name: str,
                  freqs: list[float]) -> None:
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

    def update(self,
               key: str,
               value: float) -> None:
        """Update the parameter key (name as in db)
        by the value from the db.

        Args:
            key (str): parameter name
            value (float): value in db
        """
        item_name: str = '_'.join(key.split('_')[:-1])
        param_name: str = key.split('_')[-1]
        # Energies
        if param_name == 'e':
            self.items[item_name].energy = value
        # Imaginary frequencies
        elif 'if' in param_name:
            self.items[item_name].ifreq = value
        # Frequencies
        elif 'f' in param_name:
            idx = int(param_name.split('f')[-1])
            self.items[item_name].frequencies[idx] = value
        elif 'r' in param_name:
            idx = int(param_name.split('r')[-1])
            # Reset the rotor's scan
            self.items[item_name].rotors[idx].pert = value
        else:
            raise KeyError('Trying to restore unknown parameter.')

