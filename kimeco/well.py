from copy import deepcopy
from typing import Any

from ase import Atoms
from kimeco.rotors.hrotor import HinRotor
from kimeco.rotors.mrotor import MultiRotor
from kimeco.rotors.internalrotation import InternalRotation
from ase.symbols import Symbols
import numpy as np
from numpy.typing import NDArray
from logging import Logger
from kimeco.logger_config import setup_logger


class Well:
    """Well object.
    Has a name (from MESS input), and a ct_name used in cantera.
    It also has a structure (ASE Atoms), and can have an energy.
    """
    def __init__(self,
                 name: str,
                 ct_name: str = "",
                 pert_e: bool = True
                 ) -> None:

        self.name: str = name
        self._freq: NDArray
        self.m_rotors: list[MultiRotor] = []
        self.h_rotors: list[HinRotor] = []
        self.ct_name: str = ct_name
        self.energy: float
        self.structure: Atoms
        # low frequencies perturbation
        self.lf_p = 1.0
        # high frequencies perturbation
        self.hf_p = 1.0
        # Set to False for fragments
        self.pert_e = pert_e
        self.dummy = False

    def __getattr__(self, name: str) -> Any:
        """Modification of the internal __getattr__ method
        to call the rotor writer.

        Args:
            name (str): name of method

        Returns:
            Any: whatever the method returns
        """
        if "r_scan" in name:
            try:
                idx = int(name.split('(')[1].split(')')[0])
                return self.r_scan(idx)
            except AttributeError as e:
                klog: Logger = setup_logger(name='Well.log')
                klog.debug(e)
                raise AttributeError(
                    f'Well does not have the attribute {name}')
        else:
            self.__getattribute__(name)

    @property
    def frequencies(self) -> NDArray[Any]:
        freq = deepcopy(self._freq)

        if len(freq[self._freq <= 500.0]) > 0:
            if self.lf_p >= 1:
                freq[self._freq <= 500.0] *= \
                    (1 / freq[self._freq <= 500.0] * (self.lf_p - 1) * 100 + 1)
            else:
                freq[self._freq <= 500.0] /= \
                    (1 / freq[self._freq <= 500.0] * (1 - self.lf_p) * 100 + 1)
        if len(freq[self._freq > 500.0]) > 0:
            if self.lf_p >= 1:
                freq[self._freq > 500.0] *= \
                    (1 / freq[self._freq > 500.0] * (self.hf_p - 1) * 100 + 1)
            else:
                freq[self._freq > 500.0] /= \
                    (1 / freq[self._freq > 500.0] * (1 - self.hf_p) * 100 + 1)
        return freq

    @property
    def r_struct(self) -> str:
        struct = ''
        for idx in range(len(self.structure)):
            atm: Symbols | str = self.structure.symbols[idx]
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

    @property
    def compo(self) -> dict[str, int]:
        comp: dict[str, int] = {}
        for atm in self.structure.symbols:
            if atm not in comp:
                comp[atm] = 1
            else:
                comp[atm] += 1
        return comp

    def r_scan(self, rot_num: int) -> str:
        """Representation of the rotor's scan.

        Args:
            rot_num (int): index of the rotor

        Returns:
            str: list of energies describing the rotor's rotation
        """
        scan = ''
        for val in self.h_rotors[rot_num].scan:
            scan += f'{val: 7.3f}'
        scan += '\n'
        return scan

    def set_structure(self,
                      symbols: str,
                      positions: list[list]) -> None:
        """Set the structure (atoms + geom) of the well.

        Args:
            symbols (str): Chemical elements
            positions (list[list]): 3D geometry
        """
        self.structure = Atoms(symbols=symbols,
                               positions=positions)

    def set_frequencies(self,
                        freqs: list[float]) -> None:
        """Save a list of frequencies.

        Args:
            freqs (list[float]): list of frequencies
        """
        self._freq = np.array(freqs)

    def add_hrotor(self,
                   thermalpowermax: float,
                   group: list[int],
                   axis: list[int],
                   symmetry: int,
                   scan: list[float],
                   fexp: list[int],
                   fcoef: list[float]) -> None:
        """Add a new rotor object to the well

        Args:
            thermalpowermax (float): thermalpowermax
            group (list[int]): group
            axis (list[int]): axis
            symmetry (int): symmetry
            scan (list[float]): scan
        """
        self.h_rotors.append(HinRotor(
            ThermalPowerMax=thermalpowermax,
            group=group,
            axis=axis,
            symmetry=symmetry,
            scan=scan,
            fexp=fexp,
            fcoef=fcoef))

    def add_mrotor(self,
                   sf: float,
                   iem: float,
                   pes: str,
                   qlem: float,
                   irs: list[InternalRotation]) -> None:
        """Add a new MultiRotor object to the well

        Args:
            sf: float: symmetryFactor
            iem: float: interpolationEnergyMax
            pes: str: filename containing the pes
            qlem: float: quantumLevelEnergyMax
            irs: list[InternalRotation]
        """
        self.h_rotors.append(MultiRotor(
            symmetryFactor=sf,
            interpolationEnergyMax=iem,
            potentialEnergySurface=pes,
            quantumLevelEnergyMax=qlem,
            internal_rot=irs))

    @property
    def db_dict(self) -> dict[str, float]:
        """Return a dictionary of all the pertubable parameters.

        Returns:
            dict[str, float]:
                key (str): parameter name
                value (float): parameter value
        """
        if self.pert_e:
            db_dict: dict = {
                    f"{self.name}__e": float(self.energy)
                }
        else:
            db_dict = {}
        if len(self.frequencies) != 0:
            db_dict.update(self.freq_dict)
        if len(self.h_rotors) > 0:
            db_dict.update(self.h_rotors_dict)
        if len(self.m_rotors) > 0:
            db_dict.update(self.m_rotors_dict)
        return db_dict

    @property
    def freq_dict(self) -> dict[str, float]:
        """Return the frequencies in a dictionary format.
        fd: frequencies dictionary
        f:  frequency
        Returns:
            dict[str, float]: dictionary of frequencies.
        """
        fd: dict[str, float] = {
            f"{self.name}__lf_p": float(self.lf_p),
            f"{self.name}__hf_p": float(self.hf_p),
        }

        # to save all freqs in db
        # for num, f in enumerate(self.frequencies):
        #     fd[f"{self.name}__f{num}"] = float(f)

        return fd

    @property
    def h_rotors_dict(self) -> dict[str, float]:
        """Return the rotors perturbations in a dictionary format.
        rd: rotor dictionary
        rp: rotor perturbation
        Returns:
            dict[str, float]: dictionary of perturbation intensities.
        """
        rd: dict[str, float] = {}
        for idx, rot in enumerate(self.h_rotors):
            # Do not perturb fourier expansion based hindered rotors
            if rot.fourier:
                continue
            rd[f"{self.name}__hr{idx}"] = float(rot.pert)

        return rd

    @property
    def m_rotors_dict(self) -> dict[str, float]:
        """Return the rotors perturbations in a dictionary format.
        rd: rotor dictionary
        rp: rotor perturbation
        Returns:
            dict[str, float]: dictionary of perturbation intensities.
        """
        rd: dict[str, float] = {}
        for idx, rot in enumerate(self.m_rotors):
            rd[f"{self.name}__mr{idx}"] = float(rot.sf_p)

        return rd
