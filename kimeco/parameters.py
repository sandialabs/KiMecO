import numpy as np
from copy import deepcopy
from typing import Any, Iterator
from collections.abc import Iterable

from ase.atoms import Atoms
from kimeco.enums import FreqMode
from kimeco.well import Well
from kimeco.bimolecular import Bimolecular
from kimeco.barrier import Barrier
from kimeco.rotors.internalrotation import InternalRotation
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Ptype
from kimeco.logger_config import KMOLogger


class SOP:
    """Set Of Parameters.
    Main object of the KIMECO code, to be perturbed and optimized."""

    def __init__(self,
                 score_species: list[str],
                 freq_mode: FreqMode = FreqMode.BATCH) -> None:
        self.freq_mode: FreqMode = freq_mode
        self.sc_species: list[str] = score_species
        self.wells: list[Well] = []
        self.bimolecular: list[Bimolecular] = []
        self.barriers: list[Barrier] = []
        self.id: int
        self.items: dict[str, Well | Bimolecular | Barrier] = {}
        self.power: float
        self.factor: float
        self.sigmas: list[float] = []
        self.temp: list[float]
        self.pres: list[float]
        self.pres_unit: str
        self.epsilons: list[float] = []
        self.files2copy: list[str] = []
        self._default_score = float('inf')
        self.scores: dict[str, float] = {
            sp: self._default_score for sp in self.sc_species
            }

    @classmethod
    def from_db_row(cls,
                    sop_tpl,
                    row: list[Any]):
        self = deepcopy(sop_tpl)
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

    def add_new_well(self,
                     name: str,
                     pes_id: int) -> None:
        """Procedure to create a new Well

        Args:
            name (str): Well's name
            pes_id (int): PES ID
        """
        self.wells.append(
            Well(name=name,
                 freq_mode=self.freq_mode,
                 pes_ids=[pes_id]))
        self.items[name] = self.wells[-1]

    def check_well(self,
                   name: str,
                   pes_id: int) -> bool:
        """Procedure when a well might be in different PESs

        Args:
            name (str): Well's name
            pes_id (int): PES ID
        """
        error = False
        if len(self.items[name].pes_ids) == 0:
            self.items[name].pes_ids.append(pes_id)
        elif pes_id in self.items[name].pes_ids:
            error = True
        else:
            # A well cannot belong to multiple PESs.
            error = True
        return error

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
        if name in self.items.keys():
            self.items[name].in_multiple_pes = True
        else:
            self.bimolecular.append(
                Bimolecular(
                    name=name,
                    pes_ids=[pes_id],
                    freq_mode=self.freq_mode))
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
        if name in self.items.keys():
            raise KeyError(
                f'Multiple barriers have the same name: {name}')
        self.barriers.append(
            Barrier(
                name=name,
                freq_mode=self.freq_mode,
                lside=self.items[lside],
                rside=self.items[rside],
                pes_id=pes_id))
        self.items[name] = self.barriers[-1]

    def set_freqs(self,
                  name: str,
                  freqs: list[float]) -> None:
        """Set the frequencies for the item name.

        Args:
            name (str): name of the object for which to set the frequencies
            freqs (list[float]): list of frequencies (cm-1)
        """
        if isinstance(self.items[name], Bimolecular):
            if hasattr(self.items[name].fragments[-1], '_freq'):
                f_arr = np.array(freqs)
                if not np.allclose(
                   self.items[name].fragments[-1]._freq, f_arr,
                   rtol=0.05, atol=0):
                    msg = f"Fragment {self.items[name].fragments[-1].name}"
                    msg += "\n"
                    msg += "was already set with different frequencies."
                    msg += "\n"
                    msg += "Make your inputs consistents."
                    raise ValueError(msg)
            self.items[name].fragments[-1].set_frequencies(freqs)
        else:
            if hasattr(self.items[name], '_freq'):
                f_arr = np.array(freqs)
                if not np.allclose(
                   self.items[name]._freq, f_arr,
                   rtol=0.05, atol=0):
                    msg = f"Well {self.items[name].name}"
                    msg += "\n"
                    msg += "was already set with different frequencies."
                    msg += "\n"
                    msg += "Make your inputs consistents."
                    raise ValueError(msg)
            self.items[name].set_frequencies(freqs)

    def set_hrotor(self,
                   name: str,
                   thermalpowermax: float,
                   group: list[int],
                   axis: list[int],
                   symmetry: int,
                   scan: list[float],
                   fexp: list[int],
                   fcoef: list[float]) -> None:
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

        Returns:
            int: Index of the last rotor of the well
        """
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].add_hrotor(thermalpowermax,
                                                      group,
                                                      axis,
                                                      symmetry,
                                                      scan,
                                                      fexp,
                                                      fcoef)
        else:
            self.items[name].add_hrotor(thermalpowermax,
                                        group,
                                        axis,
                                        symmetry,
                                        scan,
                                        fexp,
                                        fcoef)

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
        if isinstance(self.items[name], Bimolecular):
            self.items[name].fragments[-1].add_mrotor(
                sf,
                iem,
                pes,
                qlem,
                irs)
            return len(self.items[name].fragments[-1].m_rotors)-1
        else:
            self.items[name].add_mrotor(
                sf,
                iem,
                pes,
                qlem,
                irs)
            return len(self.items[name].m_rotors)-1

    def set_structure(self,
                      name: str,
                      symbols: str | list[str],
                      geom: list[list[float]],
                      logger: KMOLogger) -> None:
        """Set the structure for the item name.

        Args:
            name (str): name of the item
            symbols (str | list[str]): Chemical elements
            geom (list[list[float]]): 3D geometry
        """
        if isinstance(self.items[name], Bimolecular):
            if hasattr(self.items[name].fragments[-1], 'structure'):
                atm = Atoms(symbols=symbols,
                            positions=geom)
                if self.items[name].fragments[-1].structure != atm:
                    msg = f"Fragment {self.items[name].fragments[-1].name}"
                    msg += "\n"
                    msg += "was already set with a different structure."
                    msg += "\n"
                    msg += "Make your inputs consistents"
                    msg += " to suppress this warning."
                    logger.warning(msg)
            self.items[name].fragments[-1].set_structure(symbols,
                                                         geom)
        else:
            if hasattr(self.items[name], 'structure'):
                atm = Atoms(symbols=symbols,
                            positions=geom)
                if self.items[name].structure != atm:
                    msg = f"Well {self.items[name].name}"
                    msg += "\n"
                    msg += "was already set with a different structure."
                    msg += "\n"
                    msg += "Make your inputs consistents."
                    logger.warning(msg)
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

        if Ptype.SCORE.value in key:
            specie: str = key.split(dbs)[0]
            self.scores[specie] = float(value)
            return
        # Energy transfer probability, factor
        elif Ptype.ETF.value in key:
            self.factor = value
            return
        # Energy transfer probability, exponent
        elif Ptype.ETP.value in key:
            self.power = value
            return
        elif Ptype.EPSI.value in key:
            idx = int(key.split(Ptype.EPSI.value)[-1])
            self.epsilons[idx] = value
            return
        elif Ptype.SIG.value in key:
            idx = int(key.split(Ptype.SIG.value)[-1])
            self.sigmas[idx] = value
            return
        item_name: str = dbs.join(key.split(dbs)[:-1])
        param_name: str = key.split(dbs)[-1]
        # Energies
        if param_name == Ptype.WE.value:
            item = self.items[item_name]
            if isinstance(item, Well) and not isinstance(item, Barrier):
                item.dE = float(value) - float(item._energy)
            else:
                raise KeyError(
                    f"Unexpected WE parameter for non-well item: {item_name}"
                )
        elif param_name == Ptype.BE.value:
            self.items[item_name]._energy = value
        # Imaginary frequencies
        elif Ptype.IF.value in param_name:
            self.items[item_name].ifreq = value
        # symmetry factor
        elif Ptype.SFC.value in param_name:
            self.items[item_name].sfc = value
        # Frequencies
        elif Ptype.BFC.value in param_name:
            self.items[item_name].bfc = float(value)
        elif Ptype.IFC.value in param_name:
            idx = int(param_name.split(Ptype.IFC.value)[-1])
            self.items[item_name].ifc[idx] = float(value)
        # Hindered rotors
        elif Ptype.HRS.value in param_name:
            idx = int(param_name.split(Ptype.HRS.value)[-1])
            # Reset the rotor's scan
            self.items[item_name].h_rotors[idx].pert = value
        # Multi rotors
        elif Ptype.MRC.value in param_name:
            idx = int(param_name.split(Ptype.MRC.value)[-1])
            # Reset the rotor's scan
            self.items[item_name].m_rotors[idx].sfc = value
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
