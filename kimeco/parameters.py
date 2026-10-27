import numpy as np
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterator
from collections.abc import Iterable

from ase.atoms import Atoms
from kimeco.well import Well
from kimeco.bimolecular import Bimolecular
from kimeco.barrier import Barrier
from kimeco.rotors.internalrotation import InternalRotation
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Ptype
from kimeco.logger_config import KMOLogger
from kimeco.experiments.experiment import name_base


@dataclass
class PesFileData:
    """Data of one MESS input file (one PES) that is not an optimised
    parameter.

    One instance per input file, keyed by the file index (= PES id) in
    ``SOP.pes_file_data``. Both MESS writers read it to write each file
    back with its own values.

    Attributes:
        energy_offset: kcal/mol added to the aligned SOP energies to get back
            the energies of this file's own zero (0.0 for the reference
            file of each group of files sharing items).
        masses: numbers of this file's ``Masses[amu]`` line (collider first,
            then the PES-specific mass); empty when absent.
        model_ene_limit: ``ModelEnergyLimit`` in kcal/mol, None when absent.
        well_extension: ``WellExtension`` value (0.0 for the bare keyword),
            None when absent.
        atom_distance_min: ``AtomDistanceMin`` as (value, unit), None when
            absent.
        ped_species: ``PEDSpecies`` entries (e.g. 'A+B=C+D'), None when
            absent.
        micro_ener: (``MicroEnerMin``, ``MicroEnerMax``, ``MicroEnerStep``)
            in kcal/mol, an entry is None when its line is absent; None when
            all three are absent.
    """
    energy_offset: float = 0.0
    masses: list[float] = field(default_factory=list)
    model_ene_limit: float | None = None
    well_extension: float | None = None
    atom_distance_min: tuple[float, str] | None = None
    ped_species: list[str] | None = None
    micro_ener: tuple[float | None, float | None, float | None] | None = None


class SOP:
    """Set Of Parameters.
    Main object of the KIMECO code, to be perturbed and optimized."""

    def __init__(self,
                 n_exp: int) -> None:
        self.n_exp: int = n_exp
        self.wells: list[Well] = []
        self.bimolecular: list[Bimolecular] = []
        self.barriers: list[Barrier] = []
        self.id: int
        self.items: dict[str, Well | Bimolecular | Barrier] = {}
        self.power: float
        self.factor: float
        # Lennard-Jones Sigmas and Epsilons: index 0 is the collider (bath
        # gas, same in every input file), index k+1 the second value of the
        # input file k (PES-specific). One input file: [collider, value].
        self.sigmas: list[float] = []
        self.temp: list[float]
        self.pres: list[float]
        self.pres_unit: str
        self.epsilons: list[float] = []
        # LennardJones Masses[amu] (collider first, as in the MESS manual;
        # the second value is PES-specific): the first file's list. Each
        # file's own list is in pes_file_data[pes_id].masses.
        self.masses: list[float] = []
        # Global MESS keywords (None when absent from the inputs). They hold
        # the same value in every input file, except model_ene_limit, which
        # is the first file's value (each file's own value is in
        # pes_file_data[pes_id].model_ene_limit).
        self.calculation_method: str | None = None
        self.model_ene_limit: float | None = None  # kcal/mol
        self.excess_ene_temp: float | None = None
        self.chem_eig_max: float | None = None
        self.ene_step_over_temp: float | None = None
        self.well_cutoff: float | None = None
        self.reduction_method: str | None = None
        self.well_reduction_threshold: float | None = None
        self.float_type: str | None = None
        self.exp_cutoff: float | None = None
        self.ground_ene_shift_max: float | None = None  # kcal/mol
        # Data of each input file that is not a parameter, keyed by PES id
        self.pes_file_data: dict[int, PesFileData] = {}
        self.files2copy: list[str] = []
        self._default_score = float('inf')
        self.scores: dict[str, float] = {
            f"{name_base}_{i:03d}": self._default_score for i in range(n_exp)
            }

    @classmethod
    def from_db_row(cls,
                    sop_tpl,
                    row: list[Any]):
        self = deepcopy(sop_tpl)
        n_params = len(self.parameters_names)
        # Strict check, before anything is updated: a row shorter or longer
        # than the template would shift every following value to the wrong
        # parameter name.
        if len(row) != n_params:
            raise ValueError(
                f"SOP DB row holds {len(row)} values but the SOP read "
                f"from the MESS inputs has {n_params} parameters. "
                "Projects whose SOP DB predates per-PES Lennard-Jones "
                "parameters (several MESS inputs) or the fix of duplicated "
                "hindered rotors cannot be restarted or postprocessed.")
        pos = 0
        for key, val in self.parameters_names.items():
            if val != row[pos]:
                self.update(key=key,
                            value=row[pos])
            pos += 1
        return self

    def __repr__(self) -> str:
        table_repr: str = "<SOP("
        for v in self.parameters_names.values():
            table_repr += f"'{v}',"
        return table_repr[:-1] + ")>"

    def __eq__(self, other) -> bool:
        if not isinstance(other, SOP):
            return NotImplemented
        return self.parameters_names == other.parameters_names

    def __hash__(self) -> int:
        return hash(frozenset(self.parameters_names.items()))

    @property
    def species(self) -> list[str]:
        species: list[str] = []
        for well in self.wells:
            species.append(well.name)
        for bm in self.bimolecular:
            if bm.dummy:
                continue
            if bm.fragments[0].name not in species:
                species.append(bm.fragments[0].name)
            if bm.fragments[1].name not in species:
                species.append(bm.fragments[1].name)
        return species

    @property
    def pes_ids(self) -> list[int]:
        """Return all PES identifiers present in the SOP.

        Returns:
            list[int]: sorted unique PES ids found on wells and bimoleculars.
        """
        ids: set[int] = set()
        for well in self.wells:
            ids.update(well.pes_ids)
        for bim in self.bimolecular:
            ids.update(bim.pes_ids)
        return sorted(ids)

    def wells_in(self,
                 pes_id: int) -> list[Well]:
        """Return well objects belonging to a specific PES."""
        return [well for well in self.wells if pes_id in well.pes_ids]

    def bimols_in(self,
                  pes_id: int) -> list[Bimolecular]:
        """Return bimolecular objects belonging to a specific PES."""
        return [bim for bim in self.bimolecular if pes_id in bim.pes_ids]

    def species_names_in_pes(self,
                             pes_id: int) -> list[str]:
        """Return sorted species names (wells + bimolecular) within one PES."""
        names: set[str] = set()
        names.update(well.name for well in self.wells_in(pes_id))
        names.update(
            bim.name for bim in self.bimols_in(pes_id) if not bim.dummy
        )
        return sorted(names)

    def reaction_iterator(self) -> "PESReactionIterator":
        """Return iterator yielding PES-scoped from/to combinations."""
        return PESReactionIterator(self)

    def iter_top_level_items(self) -> Iterator[Well | Bimolecular | Barrier]:
        """Iterate over PES-owning SOP items only.

        Fragments attached to bimoleculars are excluded because they are
        parser-internal objects with empty pes_ids.
        """
        for collection in (self.wells, self.bimolecular, self.barriers):
            for item in collection:
                if item.dummy:
                    continue
                yield item

    @staticmethod
    def normalize_pes_ids(pes_ids: Iterable[int]) -> tuple[int, ...]:
        """Return a deterministic pes_ids payload for persistence."""
        return tuple(sorted({int(pes_id) for pes_id in pes_ids}))

    @property
    def item_pes_ids(self) -> dict[str, tuple[int, ...]]:
        """Return normalized pes_ids for all top-level SOP items."""
        return {
            item.name: self.normalize_pes_ids(item.pes_ids)
            for item in self.iter_top_level_items()
        }

    @property
    def r_epsilons(self) -> str:
        eps = ''
        for ep in self.epsilons:
            eps += f" {ep: 7.4f}"
        return eps

    @property
    def r_sigmas(self) -> str:
        sigs = ''
        for sig in self.sigmas:
            sigs += f" {sig: 7.4f}"
        return sigs

    @staticmethod
    def _collider_pairs(values: list[float]) -> list[str]:
        """Format one ``collider value`` pair per input file.

        Entry k holds the collider (index 0) and the second value of input
        file k (index k+1), as written on that file's MESS line.

        Args:
            values (list[float]): [collider, file 0 value, file 1 value, ...]

        Returns:
            list[str]: one formatted pair per file, empty when fewer than two
            values are stored.
        """
        if len(values) < 2:
            return []
        return [f" {values[0]: 7.4f} {values[k + 1]: 7.4f}"
                for k in range(len(values) - 1)]

    @property
    def r_epsilons_pes(self) -> list[str]:
        """``Epsilons`` pair written into each input file (entry k = file k).

        Template placeholder: ``{SOP.r_epsilons_pes[k]}``. For one input file
        the only entry equals ``r_epsilons``.
        """
        return self._collider_pairs(self.epsilons)

    @property
    def r_sigmas_pes(self) -> list[str]:
        """``Sigmas`` pair written into each input file (entry k = file k).

        Template placeholder: ``{SOP.r_sigmas_pes[k]}``. For one input file
        the only entry equals ``r_sigmas``.
        """
        return self._collider_pairs(self.sigmas)

    def file_data(self, pes_id: int) -> PesFileData:
        """Return the per-file data of one PES, created empty on first use.

        Args:
            pes_id (int): PES id (= index of the MESS input file).

        Returns:
            PesFileData: the data of that input file.
        """
        return self.pes_file_data.setdefault(pes_id, PesFileData())

    @property
    def r_rc_temp(self) -> str:
        temps = ""
        for temp in self.temp:
            temps += f" {temp: 8.2f}"
        temps += '\n'
        return temps

    @property
    def r_rc_pres(self) -> str:
        press = ""
        for pres in self.pres:
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

    def _check_item_name(self,
                         name: str) -> None:
        """Check if the name of the item is valid.
        It should not contain some specific substrings.

        Args:
            name (str): Item name
        """
        if '.' in name:
            raise ValueError(
                f"Item name cannot contain a dot: {name}")
        elif dbs in name:
            raise ValueError(
                f"Item name cannot contain the db separator '{dbs}': {name}")

    def add_new_well(self,
                     name: str,
                     pes_id: int) -> None:
        """Procedure to create a new Well

        Args:
            name (str): Well's name
            pes_id (int): PES ID
        """
        self._check_item_name(name)
        self.wells.append(
            Well(name=name,
                 pes_ids=[pes_id]))
        self.items[name] = self.wells[-1]

    def check_well(self,
                   name: str,
                   pes_id: int) -> bool:
        """Procedure when a well might be in different PESs

        A well read from several input files is one object carrying the id
        of every file it appears in. A well first read as a bimolecular
        fragment (no PES id) becomes a PES well of the file declaring it.

        Args:
            name (str): Well's name
            pes_id (int): PES ID

        Returns:
            bool: True (error) when the well is already declared in this
            PES, False when the PES id was added.
        """
        item = self.items[name]
        if pes_id in item.pes_ids:
            return True
        item.pes_ids.append(pes_id)
        if len(item.pes_ids) > 1:
            item.in_multiple_pes = True
        if isinstance(item, Well) and not isinstance(item, Barrier) \
                and not any(well is item for well in self.wells):
            self.wells.append(item)
        return False

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
                      name: str,
                      pes_id: int) -> None:
        """Procedure to create a new bimolecular object

        Args:
            name (str): name of the bimolecular object
            pes_id (int): PES ID
        """
        self._check_item_name(name)
        if name in self.items.keys():
            self.items[name].in_multiple_pes = True
            if pes_id not in self.items[name].pes_ids:
                self.items[name].pes_ids.append(pes_id)
        else:
            self.bimolecular.append(
                Bimolecular(
                    name=name,
                    pes_ids=[pes_id]))
            self.items[name] = self.bimolecular[-1]

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
        pn: dict[str, Any] = {
            dbs + Ptype.ETF.value: self.factor,
            dbs + Ptype.ETP.value: self.power
            }
        for k, v in self.scores.items():
            pn[k + dbs + Ptype.SCORE.value] = float(v)
        for idx, ep in enumerate(self.epsilons):
            pn[dbs + Ptype.EPSI.value + f'{idx}'] = float(ep)
        for idx, sig in enumerate(self.sigmas):
            pn[dbs + Ptype.SIG.value + f'{idx}'] = float(sig)
        for well in self.wells:
            if well.dummy:
                continue
            pn.update(well.db_dict)
        for bar in self.barriers:
            if bar.dummy:
                continue
            pn.update(bar.db_dict)
        for bim in self.bimolecular:
            if bim.dummy:
                continue
            pn.update(bim.db_dict)

        return pn

    def add_new_barrier(self,
                        name: str,
                        lside: str,
                        rside: str,
                        pes_id: int) -> None:
        """Procedure to add a new barrier in the SOP

        Args:
            name (str): name of the Barrier object
            lside (str): name of the reactant
            rside (str): name of the product
            pes_id (int): PES ID
        """
        self._check_item_name(name)
        if name in self.items.keys():
            raise KeyError(
                f'Multiple barriers have the same name: {name}')
        self.barriers.append(
            Barrier(
                name=name,
                lside=self.items[lside],
                rside=self.items[rside],
                pes_id=pes_id))
        self.items[name] = self.barriers[-1]

    def check_barrier(self,
                      name: str,
                      pes_id: int) -> bool:
        """Add a PES to a barrier already read from another input file.

        A barrier shared by several input files is one object carrying the
        id of every file it appears in.

        Args:
            name (str): barrier's name
            pes_id (int): PES ID of the file declaring it again

        Returns:
            bool: True (error) when the barrier is already declared in this
            PES, False when the PES id was added.
        """
        item = self.items[name]
        if pes_id in item.pes_ids:
            return True
        item.pes_ids.append(pes_id)
        item.in_multiple_pes = True
        return False

    def set_freqs(self,
                  name: str,
                  freqs: list[float]) -> None:
        """Set the frequencies for the item name.

        Args:
            name (str): name of the object for which to set the frequencies
            freqs (list[float]): list of frequencies (cm-1)
        """
        item = self.items[name]
        if isinstance(item, Bimolecular):
            if hasattr(item.fragments[-1], '_freq'):
                f_arr = np.array(freqs)
                if not np.allclose(
                   item.fragments[-1]._freq, f_arr,
                   rtol=0.05, atol=0):
                    msg = f"Fragment {item.fragments[-1].name}"
                    msg += "\n"
                    msg += "was already set with different frequencies."
                    msg += "\n"
                    msg += "Make your inputs consistents."
                    raise ValueError(msg)
            item.fragments[-1].set_frequencies(freqs)
        else:
            if hasattr(item, '_freq'):
                f_arr = np.array(freqs)
                if not np.allclose(
                   item._freq, f_arr,
                   rtol=0.05, atol=0):
                    msg = f"Well {item.name}"
                    msg += "\n"
                    msg += "was already set with different frequencies."
                    msg += "\n"
                    msg += "Make your inputs consistents."
                    raise ValueError(msg)
            item.set_frequencies(freqs)

    def set_hrotor(self,
                   name: str,
                   thermalpowermax: float,
                   group: list[int],
                   axis: list[int],
                   symmetry: int,
                   scan: list[float],
                   fexp: list[int],
                   fcoef: list[float],
                   geo=None,
                   spline_angles: list[float] | None = None) -> int:
        """Create a new rotor object for a well

        Args:
            name (str): name of the well
            thermalpowermax (float): thermalpowermax
            group (list[int]): group
            axis (list[int]): axis
            symmetry (int): symmetry
            scan (list[float]): list of energies (kcal/mol) describing the
                                rotor's rotation
            fexp: (list[int]): list of exponents for fourrier expansion
            fcoef: (list[float]): list of coefficients for fourrier expansion
            spline_angles (list[float] | None): angles (degrees) of a
                ``PotentialSpline`` rotor, None for ``Potential[kcal/mol]``.

        Returns:
            int: Index of the rotor in the item's h_rotors
        """
        item = self.items[name]
        if isinstance(item, Bimolecular):
            return item.fragments[-1].add_hrotor(thermalpowermax,
                                                 group,
                                                 axis,
                                                 symmetry,
                                                 scan,
                                                 fexp,
                                                 fcoef,
                                                 geo=geo,
                                                 spline_angles=spline_angles)
        return item.add_hrotor(thermalpowermax,
                               group,
                               axis,
                               symmetry,
                               scan,
                               fexp,
                               fcoef,
                               geo=geo,
                               spline_angles=spline_angles)

    def set_mrotor(self,
                   name: str,
                   sf: float,
                   iem: float,
                   pes: str,
                   qlem: float,
                   irs: list[InternalRotation]) -> int:
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
        item = self.items[name]
        if isinstance(item, Bimolecular):
            item.fragments[-1].add_mrotor(
                sf,
                iem,
                pes,
                qlem,
                irs)
            return len(item.fragments[-1].m_rotors)-1
        else:
            item.add_mrotor(
                sf,
                iem,
                pes,
                qlem,
                irs)
            return len(item.m_rotors)-1

    def set_structure(self,
                      name: str,
                      symbols: str | list[str],
                      geom: list[list[float]],
                      logger: KMOLogger) -> None:
        """Set the structure for the item name.

        Args:
            name (str): name of the item
            symbols (str | list[str]): Chemical models
            geom (list[list[float]]): 3D geometry
        """
        item = self.items[name]
        if isinstance(item, Bimolecular):
            if hasattr(item.fragments[-1], 'structure'):
                atm = Atoms(symbols=symbols,
                            positions=geom)
                if item.fragments[-1].structure != atm:
                    msg = f"Fragment {item.fragments[-1].name}"
                    msg += "\n"
                    msg += "was already set with a different structure."
                    msg += "\n"
                    msg += "Make your inputs consistents"
                    msg += " to suppress this warning."
                    logger.warning(msg)
            item.fragments[-1].set_structure(symbols,
                                             geom)
        else:
            if hasattr(item, 'structure'):
                atm = Atoms(symbols=symbols,
                            positions=geom)
                if item.structure != atm:
                    msg = f"Well {item.name}"
                    msg += "\n"
                    msg += "was already set with a different structure."
                    msg += "\n"
                    msg += "Make your inputs consistents."
                    logger.warning(msg)
            item.set_structure(symbols,
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
        from kimeco.scoring_f.scoring import get_parameter_type
        ptype = get_parameter_type(key)

        if ptype == Ptype.SCORE:
            exp_name: str = key.split(dbs)[0]
            self.scores[exp_name] = float(value)
            return
        # Energy transfer probability, factor
        elif ptype == Ptype.ETF:
            self.factor = value
            return
        # Energy transfer probability, exponent
        elif ptype == Ptype.ETP:
            self.power = value
            return
        elif ptype == Ptype.EPSI:
            idx = int(key.split(Ptype.EPSI.value)[-1])
            self.epsilons[idx] = value
            return
        elif ptype == Ptype.SIG:
            idx = int(key.split(Ptype.SIG.value)[-1])
            self.sigmas[idx] = value
            return
        item_name: str = dbs.join(key.split(dbs)[:-1])
        param_name: str = key.split(dbs)[-1]
        # Energies
        if ptype == Ptype.WE:
            item = self.items[item_name]
            if isinstance(item, Well) and not isinstance(item, Barrier):
                item.dE = float(value) - float(item._energy)
            else:
                raise KeyError(
                    f"Unexpected WE parameter for non-well item: {item_name}"
                )
        elif ptype == Ptype.BE:
            self.items[item_name]._energy = value
        # Imaginary frequencies
        elif ptype == Ptype.IF:
            item = self.items[item_name]
            if not isinstance(item, Barrier):
                raise KeyError(f'Expected Barrier for IF parameter: {item_name}')
            item.ifreq = value
        # symmetry factor
        elif ptype == Ptype.SFC:
            item = self.items[item_name]
            if not isinstance(item, Barrier):
                raise KeyError(f'Expected Barrier for SFC parameter: {item_name}')
            item.sfc = value
        # Frequencies
        elif ptype == Ptype.BFC:
            item = self.items[item_name]
            if isinstance(item, Bimolecular):
                msg: str = f'Unexpected BFC parameter'
                msg += f' for bimolecular fragment: {item_name}'
                raise KeyError(msg)
            else:
                item.bfc = float(value)
        elif ptype == Ptype.IFC:
            idx = int(param_name.split(Ptype.IFC.value)[-1])
            item = self.items[item_name]
            if not isinstance(item, Barrier):
                msg = f'Unexpected IFC parameter for'
                msg += f' non-barrier item: {item_name}'
                raise KeyError(msg)
            else:
                item.ifc[idx] = float(value)
        # Hindered rotors
        elif ptype == Ptype.HRS:
            idx = int(param_name.split(Ptype.HRS.value)[-1])
            # Reset the rotor's scan
            item = self.items[item_name]
            if isinstance(item, Bimolecular):
                msg = f'Unexpected HRS parameter for'
                msg += f' bimolecular fragment: {item_name}'
                raise KeyError(msg)
            else:
                item.h_rotors[idx].pert = value
        # Multi rotors
        elif ptype == Ptype.MRC:
            idx = int(param_name.split(Ptype.MRC.value)[-1])
            # Reset the rotor's scan
            item = self.items[item_name]
            if isinstance(item, Bimolecular):
                item.fragments[-1].m_rotors[idx].sfc = value
            else:
                item.m_rotors[idx].sfc = value
        else:
            raise KeyError('Trying to restore unknown parameter.')

    def set_uncertainties(self,
                          settings: dict[str, Any]) -> None:
        """Set the uncertainties for all the parameters

        Args:
            settings (dict[str, Any]): user's input
        """
        self.uncertainties: dict[str, float] = {
            dbs+Ptype.ETF.value: settings[f'std_{Ptype.ETF.value}'],
            dbs+Ptype.ETP.value: settings[f'std_{Ptype.ETP.value}']
        }
        for idx in range(len(self.sigmas)):
            self.uncertainties[f'{dbs}{Ptype.SIG.value}{idx}'] = \
                settings[f'std_{Ptype.SIG.value}']
        for idx in range(len(self.epsilons)):
            self.uncertainties[f'{dbs}{Ptype.EPSI.value}{idx}'] = \
                settings[f'std_{Ptype.EPSI.value}']

        for sp in self.items.values():
            sp: Well | Barrier | Bimolecular
            sp.set_uncertainties(settings)
            self.uncertainties.update(sp.uncertainties)
        for pname in settings["specific_std"].keys():
            if pname not in self.uncertainties.keys():
                msg = f"The parameter {pname} is not recognized."
                msg += " Check your specific_std keys."
                raise KeyError(msg)
        self.uncertainties.update(settings["specific_std"])


class PESReactionIterator:
    """Iterator over all valid (pes_id, from_name, to_name) combinations."""

    def __init__(self,
                 sop: SOP) -> None:
        self.sop: SOP = sop

    @staticmethod
    def make_name(pes_id: int,
                  from_name: str,
                  to_name: str) -> str:
        return f"P{pes_id:02d}:{from_name}->{to_name}"

    def __iter__(self) -> Iterator[tuple[int, str, str]]:
        for pes_id in self.sop.pes_ids:
            species_names: list[str] = self.sop.species_names_in_pes(pes_id)
            for from_name in species_names:
                for to_name in species_names:
                    if from_name == to_name:
                        continue
                    yield (pes_id, from_name, to_name)
