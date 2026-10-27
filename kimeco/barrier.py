from typing import Any
from kimeco.bimolecular import Bimolecular
from kimeco.enums import FreqMode
from kimeco.well import Well
import numpy as np
from numpy.typing import NDArray
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Ptype


class Barrier(Well):
    """A barrier connect a well to
    a bimolecular prod, or another well"""
    def __init__(self, name: str,
                 lside: Well | Bimolecular,
                 rside: Well | Bimolecular,
                 pes_id: int,
                 freq_mode: FreqMode = FreqMode.BATCH) -> None:

        super().__init__(name=name,
                         pes_ids=[pes_id],
                         freq_mode=freq_mode)
        self.connected: list[Well | Bimolecular] = [lside, rside]
        self._energy: float
        self.ifreq: float
        # Barrierless parameters
        self._symFact: float = 1.0
        self.sfc: float = 1.0  # Symmetry Factor Coefficient
        self.barrierless: bool = False
        # Only used to retroactively set energy of a side if dummy
        self._well_depth: list[float]
        self.pp: float  # PotentialPrefactor
        self.ppe: float  # PotentialPowerExponent
        self.file: str  # Rotd filename
        # TSTLevel of a PhaseSpaceTheory core as written in the input
        # (e.g. 'EJ'); None when the core has no TSTLevel line.
        self.tst_level: str | None = None

    @property
    def symFact(self) -> float:
        return self._symFact * self.sfc

    @property
    def frequencies(self) -> NDArray[Any]:
        if not self.barrierless:
            freq: NDArray = super(Barrier, self).frequencies
        else:
            tmp = []
            for side in self.connected:
                if isinstance(side, Bimolecular):
                    tmp.extend(side.fragments[0].frequencies.tolist())
                    tmp.extend(side.fragments[1].frequencies.tolist())
                    break
            freq: NDArray = np.array(tmp)
        return freq

    @property
    def energy(self) -> float:
        if self.barrierless:
            return max(self.connected[0].energy,
                       self.connected[1].energy)
        else:
            return self._energy

    @property
    def r_coff(self) -> float:
        return float(f"{min(self.r_lenergy, self.r_renergy):.3f}")

    @property
    def r_lenergy(self) -> float:
        return float(f"{self.energy - self.connected[0].energy:.3f}")

    @property
    def r_renergy(self) -> float:
        return float(f"{self.energy - self.connected[1].energy:.3f}")

    @property
    def db_dict(self) -> dict[str, Any]:
        if self.barrierless:
            key: str = self.name + dbs + Ptype.SFC.value
            return {key: float(self.sfc)}
        db_dict: dict = super(Barrier, self).db_dict
        db_dict.pop(f"{self.name}{dbs}{Ptype.WE.value}", None)
        db_dict[f"{self.name}{dbs}{Ptype.BE.value}"] = float(self._energy)
        db_dict.update(
            {f"{self.name}{dbs}{Ptype.IF.value}": float(self.ifreq)}
            )

        return db_dict

    def differing_fields(self, other: Well) -> list[str]:
        """List the input data that differ between this barrier and the
        same barrier read again from another file.

        Adds the barrier-specific data (barrierless core, symmetry factor,
        PST potential, TSTLevel, imaginary frequency, rotd file) to the
        species data compared by ``Well.differing_fields``.

        Args:
            other (Well): barrier read again under the same label.

        Returns:
            list[str]: names of the differing fields (empty when identical).
        """
        fields: list[str] = super().differing_fields(other)
        for label, attr in (('barrierless core', 'barrierless'),
                            ('symmetry factor (core)', '_symFact'),
                            ('PotentialPrefactor', 'pp'),
                            ('PotentialPowerExponent', 'ppe'),
                            ('TSTLevel', 'tst_level'),
                            ('imaginary frequency', 'ifreq'),
                            ('rotd file', 'file')):
            if getattr(self, attr, None) != getattr(other, attr, None):
                fields.append(label)
        return fields

    def set_uncertainties(self, settings: dict[str, Any]):
        super().set_uncertainties(settings)
        self.uncertainties.pop(f'{self.name}{dbs}{Ptype.WE.value}', None)
        barrier_specific: list[Ptype] = [Ptype.BE]
        if self.barrierless:
            barrier_specific.append(Ptype.SFC)
        else:
            barrier_specific.append(Ptype.IF)
        for ptype in barrier_specific:
            param_name: str = self.name + dbs + ptype.value
            self.uncertainties[param_name] = settings[f'std_{ptype.value}']
