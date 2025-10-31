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
from kimeco.enums import Ptype
from kimeco.database.kimeco_db import dbs
from kimeco.enums import FreqMode


class Well:
    """Well object.
    Has a name (from MESS input), and a ct_name used in cantera.
    It also has a structure (ASE Atoms), and can have an energy.
    """
    def __init__(self,
                 name: str,
                 ct_name: str = "",
                 pert_e: bool = True,
                 freq_mode: FreqMode = FreqMode.BATCH
                 ) -> None:

        self.name: str = name
        self._freq: NDArray
        self.m_rotors: list[MultiRotor] = []
        self.h_rotors: list[HinRotor] = []
        self.ct_name: str = ct_name
        self.energy: float
        self.structure: Atoms
        # batch frequency coefficient
        self.bfc = 1.0
        # Individual frequency coefficient
        self.ifc: list[float]
        self.pert_e: bool = pert_e
        self.dummy: bool = False
        self.freq_mode: FreqMode = freq_mode
        self.uncertainties: dict[str, float] = {}

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
        if self.freq_mode == FreqMode.BATCH:
            if self.bfc == 1.0:
                return self._freq
            elif self.bfc < 1.0:
                return self._freq / ((1 / self._freq) * (1 - self.bfc) * 100 + 1)
            else:
                return self._freq * ((1 / self._freq) * (self.bfc - 1) * 100 + 1)
        elif self.freq_mode == FreqMode.INDIVIDUAL:
            return self._freq * self.ifc
        else:
            raise AttributeError('Unknown FreqMode')

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

    def set_uncertainties(self,
                          settings: dict[str, Any]) -> None:
        """Set the uncertainties of the well

        Args:
            settings (dict[str, Any]): User input

        Raises:
            TypeError: Unknown parameter
        """
        # Do not set the uncertainties for a well
        to_ignore: list[Ptype] = [
            Ptype.ETF,
            Ptype.ETP,
            Ptype.EPSI,
            Ptype.SIG,
            Ptype.IF,
            Ptype.SFC,
            Ptype.BE]
        if self.freq_mode == FreqMode.BATCH:
            to_ignore.append(Ptype.IFC)
        else:
            to_ignore.append(Ptype.BFC)
        if not self.pert_e:
            to_ignore.append(Ptype.WE)
        for unctt, val in settings.items():
            if not unctt.startswith('std_'):
                continue
            try:
                ptype = Ptype(unctt.split('std_')[-1])
            except Exception as e:
                msg = 'Unknown parameter in setting uncertainties'
                print(e)
                raise TypeError(msg)
            if ptype in to_ignore:
                continue
            elif ptype == Ptype.HRS:
                for idx in range(len(self.h_rotors)):
                    param_name: str = self.name + dbs + ptype.value + str(idx)
                    self.uncertainties[param_name] = val
            elif ptype == Ptype.MRC:
                for idx in range(len(self.m_rotors)):
                    param_name = self.name + dbs + ptype.value + str(idx)
                    self.uncertainties[param_name] = val
            elif ptype == Ptype.IFC:
                for idx in range(len(self._freq)):
                    param_name = self.name + dbs + ptype.value + f"{idx:02d}"
                    self.uncertainties[param_name] = val
            else:
                param_name = self.name + dbs + ptype.value
                self.uncertainties[param_name] = val

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
        self.ifc = [1.0 for i in range(len(self._freq))]

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
        self.m_rotors.append(MultiRotor(
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
                    f"{self.name}{dbs}{Ptype.WE.value}": float(self.energy)
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
        if self.freq_mode == FreqMode.BATCH:
            key: str = self.name + dbs + Ptype.BFC.value
            fd: dict[str, float] = {
                key: self.bfc
            }
        elif self.freq_mode == FreqMode.INDIVIDUAL:
            fd = {}
            for idx, fc in enumerate(self.ifc):
                key = self.name + dbs + Ptype.IFC.value + f"{idx:02d}"
                fd[key] = fc

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
            rd[f'{self.name}{dbs}{Ptype.HRS.value}{idx}'] = float(rot.pert)

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
            rd[f'{self.name}{dbs}{Ptype.MRC.value}{idx}'] = float(rot.sfc)

        return rd
