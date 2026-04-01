from typing import Any
from kimeco.enums import FreqMode
from kimeco.well import Well


class Bimolecular:
    """A well is a minima on the PES.
    It must have a name and an energy."""
    def __init__(self,
                 name: str,
                 pes_ids: list[int],
                 freq_mode: FreqMode = FreqMode.BATCH
                 ) -> None:
        self.freq_mode: FreqMode = freq_mode
        self.name: str = name
        self.fragments: list[Well] = []
        self.pes_ids: list[int] = pes_ids
        self.in_multiple_pes: bool = False
        self._energy: float
        self.dummy = False
        self.uncertainties: dict[str, float] = {}

    @property
    def energy(self) -> float:
        """Return the energy of the bimolecular.

        Returns:
            float: energy of the bimolecular
        """
        return self._energy + sum([frag.dE for frag in self.fragments])

    def set_fragments(self, frags: list[Well]) -> None:
        """Save a pair of fragments.

        Args:
            frags (list[Well]): pair of fragments
        """
        self.fragments = frags

    def add_new_frag(self,
                     name: str) -> None:
        """Save a new fragment.

        Args:
            name (str): fragment's name
            pes_id (int): PES identifier owning this fragment
        """
        # Fragments are shared molecular pieces and are not assigned to a PES.
        frag = Well(
            name=name,
            pes_ids=[],
            freq_mode=self.freq_mode,
            pert_e=True)
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
        for frag in self.fragments:
            frag.set_uncertainties(settings=settings)
            self.uncertainties.update(frag.uncertainties)

    @property
    def db_dict(self) -> dict[str, Any]:
        db_dict: dict[str, float] = {}
        # Old implementation. bimolecular shouldn't be perturbed anymore
        # f"{self.name}{dbs}{Ptype.WE.value}": float(self.energy)
        for frag in self.fragments:
            db_dict.update(frag.db_dict)

        return db_dict
