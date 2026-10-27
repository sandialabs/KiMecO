from typing import Any

from ase import Atoms
from kimeco.rotors.hrotor import HinRotor
from kimeco.rotors.mrotor import MultiRotor
from kimeco.rotors.internalrotation import InternalRotation
from ase.symbols import Symbols
import numpy as np
from numpy.typing import NDArray
from kimeco.logger_config import KMOLogger, create_logger
from kimeco.enums import Ptype
from kimeco.database.kimeco_db import dbs
from kimeco.enums import FreqMode


def _same_multirotor(first: MultiRotor, second: MultiRotor) -> bool:
    """Tell whether two MultiRotor objects hold the same input data.

    Args:
        first (MultiRotor): first rotor.
        second (MultiRotor): second rotor.

    Returns:
        bool: True when symmetry factor, energies, potential file and
        internal rotations are identical.
    """
    return (first._sf == second._sf
            and first.iem == second.iem
            and first.file == second.file
            and first.qlem == second.qlem
            and len(first.internal_rot) == len(second.internal_rot)
            and all(ir_a == ir_b for ir_a, ir_b
                    in zip(first.internal_rot, second.internal_rot)))


class Well:
    """Well object.
    Has a single species name used in MESS and mechanism.
    It also has a structure (ASE Atoms), and can have an energy.
    """
    def __init__(self,
                 name: str,
                 pes_ids: list[int],
                 pert_e: bool = True,
                 freq_mode: FreqMode = FreqMode.BATCH
                 ) -> None:

        self.name: str = name
        self._freq: NDArray
        self.m_rotors: list[MultiRotor] = []
        self.h_rotors: list[HinRotor] = []
        self.in_multiple_pes: bool = False
        # Original energy in inputs
        self._energy: float = 0.0
        # Perturbation of the energy
        self.dE: float = 0.0
        self.structure: Atoms
        # batch frequency coefficient
        self.bfc = 1.0
        # Individual frequency coefficient
        self.ifc: list[float]
        self.pert_e: bool = pert_e
        self.dummy: bool = False
        self.freq_mode: FreqMode = freq_mode
        self.uncertainties: dict[str, float] = {}
        self.pes_ids: list[int] = pes_ids
        # MESS SymmetryFactor of the rigid-rotor core
        self.sym_factor: float = 1.0
        # MESS ``Atom`` fragment (a single atom described only by its mass
        # and electronic levels): set by ``set_atom``.
        self.is_atom: bool = False
        # Mass[amu] line of an ``Atom`` block (None for a molecule)
        self.atom_mass: float | None = None

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
                klog: KMOLogger = create_logger(name='Well.log')
                klog.debug(str(e), exc_info=True)
                raise AttributeError(
                    f'Well does not have the attribute {name}')
        else:
            self.__getattribute__(name)

    @property
    def energy(self) -> float:
        return self._energy + self.dE

    @property
    def frequencies(self) -> NDArray[Any]:
        if self.freq_mode == FreqMode.BATCH:
            return self._freq * self.bfc ** (100/self._freq)
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
        rotor: HinRotor = self.h_rotors[rot_num]
        # PotentialSpline energies keep the 4 decimals of the AutoMech
        # inputs; Potential[kcal/mol] grids keep the historical format.
        fmt = ' 9.4f' if rotor.is_spline else ' 7.3f'
        scan = ''
        for val in rotor.scan:
            scan += f'{val:{fmt}}'
        scan += '\n'
        return scan

    def set_atom(self,
                 element: str,
                 mass: float) -> None:
        """Describe this item as a MESS ``Atom`` (mass and electronic
        levels only, no geometry block, no frequency).

        A one-atom structure at the origin is stored so that the
        composition, the PST stoichiometry and the automech serializer keep
        working.

        Args:
            element (str): chemical symbol of the atom.
            mass (float): ``Mass[amu]`` value read from the input.
        """
        self.is_atom = True
        self.atom_mass = float(mass)
        self.structure = Atoms(symbols=[element], positions=[[0.0, 0.0, 0.0]])
        self.set_frequencies([])

    def differing_fields(self, other: 'Well') -> list[str]:
        """List the input data that differ between this item and ``other``.

        Used when the same label is read again (another file, or another
        bimolecular for a fragment): the two readings must describe the same
        species. Energies are not compared here (they are aligned between
        files separately).

        Args:
            other (Well): item read again under the same label.

        Returns:
            list[str]: names of the differing fields (empty when identical).
        """
        fields: list[str] = []
        mine = getattr(self, 'structure', None)
        theirs = getattr(other, 'structure', None)
        if (mine is None) != (theirs is None) or (
                mine is not None and mine != theirs):
            fields.append('geometry')
        mine_freq = getattr(self, '_freq', None)
        their_freq = getattr(other, '_freq', None)
        if (mine_freq is None) != (their_freq is None) or (
                mine_freq is not None
                and not np.array_equal(mine_freq, their_freq)):
            fields.append('frequencies')
        if (getattr(self, 'elec_levels', None)
                != getattr(other, 'elec_levels', None)):
            fields.append('electronic levels')
        if self.sym_factor != other.sym_factor:
            fields.append('symmetry factor')
        if len(self.h_rotors) != len(other.h_rotors) or not all(
                mine_hr.same_definition(their_hr)
                for mine_hr, their_hr in zip(self.h_rotors, other.h_rotors)):
            fields.append('hindered rotors')
        if len(self.m_rotors) != len(other.m_rotors) or not all(
                _same_multirotor(mine_mr, their_mr)
                for mine_mr, their_mr in zip(self.m_rotors, other.m_rotors)):
            fields.append('multirotors')
        if self.dummy != other.dummy:
            fields.append('dummy')
        if (self.is_atom != other.is_atom
                or self.atom_mass != other.atom_mass):
            fields.append('atom')
        return fields

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
        general_uncertainties: dict[str, float] = {
            k: v for k, v in settings.items() if k.startswith('std_')
        }
        for unctt, val in general_uncertainties.items():
            try:
                ptype = Ptype(unctt.split('std_')[-1])
            except Exception as e:
                msg = 'Unknown parameter in setting uncertainties'
                klog: KMOLogger = create_logger(name='Well.log')
                klog.debug(str(e), exc_info=True)
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
                      symbols: str | list[str],
                      positions: list[list]) -> None:
        """Set the structure (atoms + geom) of the well.

        Args:
            symbols (str | list[str]): Chemical models
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
                   fcoef: list[float],
                   geo=None,
                   spline_angles: list[float] | None = None) -> int:
        """Add a new rotor object to the well

        Args:
            thermalpowermax (float): thermalpowermax
            group (list[int]): group
            axis (list[int]): axis
            symmetry (int): symmetry
            scan (list[float]): scan
            spline_angles (list[float] | None): angles (degrees) of a
                ``PotentialSpline`` rotor, None for ``Potential[kcal/mol]``.

        Returns:
            int: index of the rotor in ``h_rotors``.
        """
        new_rotor = HinRotor(
            ThermalPowerMax=thermalpowermax,
            group=group,
            axis=axis,
            symmetry=symmetry,
            scan=scan,
            fexp=fexp,
            fcoef=fcoef,
            geo=geo,
            spline_angles=spline_angles)
        for idx, hr in enumerate(self.h_rotors):
            if hr.group == group and hr.axis == axis:
                if hr.same_definition(new_rotor):
                    # Same rotor declared again: keep a single copy.
                    return idx
                else:
                    msg = f"Well {self.name} already has a rotor with:"
                    msg += "\n"
                    msg += f"Group: {group}, Axis: {axis}."
                    msg += "\n"
                    msg += "make the inputs consistents"
                    raise ValueError(msg)
        self.h_rotors.append(new_rotor)
        return len(self.h_rotors) - 1

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
        for mr in self.m_rotors:
            for ir, irs_ir in zip(irs, mr.internal_rot):
                if ir.group == irs_ir.group and ir.axis == irs_ir.axis:
                    if (mr.sfc == sf and
                        mr.iem == iem and
                        mr.file == pes and
                        mr.qlem == qlem and
                        ir == irs_ir):
                        break
                    else:
                        msg = f"Well {self.name} already has a rotor with:"
                        msg += "\n"
                        msg += f"Group: {ir.group}, Axis: {ir.axis}."
                        msg += "\n"
                        msg += "make the inputs consistents"
                        raise ValueError(msg)
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
