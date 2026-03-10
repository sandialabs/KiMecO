from typing import Any
from kimeco.enums import FreqMode
from kimeco.well import Well
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Ptype


class Bimolecular:
    """A well is a minima on the PES.
    It must have a name and an energy."""
    def __init__(self,
                 name: str,
                 freq_mode: FreqMode = FreqMode.BATCH
                 ) -> None:
        self.freq_mode: FreqMode = freq_mode
        self.name: str = name
        self.fragments: list[Well] = []
        self.energy: float
        self.dummy = False
        self.uncertainties: dict[str, float] = {}

    def set_fragments(self, frags: list[Well]) -> None:
        """Save a pair of fragments.

        Args:
            frags (list[Well]): pair of fragments
        """
        self.fragments = frags

    def add_new_frag(self, name: str) -> None:
        """Save a new fragment.

        Args:
            name (str): fragment's name
        """
        frag = Well(name=name,
                    freq_mode=self.freq_mode,
                    pert_e=False)
        self.fragments.append(frag)

    @property
    def frag_names(self) -> list[str]:
        """Return the list of fragments' name for this bimol object

        Returns:
            list[str]: List of fragments' name
        """
        names: list = []
        for frag in self.fragments:
            names.append(frag.name)
        return names

    def set_uncertainties(self,
                          settings: dict[str, Any]) -> None:
        self.uncertainties[f"{self.name}{dbs}{Ptype.WE.value}"] = \
            settings[f'std_{Ptype.WE.value}']
        for frag in self.fragments:
            frag.set_uncertainties(settings=settings)
            self.uncertainties.update(frag.uncertainties)

    @property
    def db_dict(self) -> dict[str, Any]:
        db_dict: dict[str, float] = {
            f"{self.name}{dbs}{Ptype.WE.value}": float(self.energy)}
        for frag in self.fragments:
            db_dict.update(frag.db_dict)

        return db_dict
