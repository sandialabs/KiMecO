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
        self._symFact: float
        self.sfc: float = 1.0  # Symmetry Factor Coefficient
        self.barrierless: bool = False
        # Only used to retroactively set energy of a side if dummy
        self._well_depth: list[float]
        self.pp: float  # PotentialPrefactor
        self.ppe: float  # PotentialPowerExponent
        self.file: str  # Rotd filename

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
