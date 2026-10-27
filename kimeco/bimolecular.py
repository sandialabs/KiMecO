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
        # One flag per fragment slot (same order as ``fragments``): True when
        # the MESS line reads ``Fragment <name> density``. The flag belongs to
        # this bimolecular, not to the fragment, because the same fragment
        # may carry the keyword in one bimolecular and not in another.
        self.fragment_density: list[bool] = []
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
                     name: str,
                     density: bool = False) -> None:
        """Save a new fragment.

        Args:
            name (str): fragment's name
            density (bool): True when the fragment line carries the MESS
                ``density`` keyword in this bimolecular.
        """
        # Fragments are shared molecular pieces and are not assigned to a PES.
        frag = Well(
            name=name,
            pes_ids=[],
            freq_mode=self.freq_mode,
            pert_e=True)
        self.attach_fragment(frag, density=density)

    def attach_fragment(self,
                        frag: Well,
                        density: bool = False) -> None:
        """Append an existing fragment object in the next fragment slot.

        Args:
            frag (Well): fragment object (possibly shared with other
                bimoleculars).
            density (bool): True when the fragment line carries the MESS
                ``density`` keyword in this bimolecular.
        """
        self.fragments.append(frag)
        self.fragment_density.append(bool(density))

    def density_of(self, slot: int) -> bool:
        """Return the ``density`` flag of one fragment slot.

        Args:
            slot (int): fragment slot (0 or 1).

        Returns:
            bool: the flag, False when the slot has none recorded.
        """
        if slot < len(self.fragment_density):
            return self.fragment_density[slot]
        return False

    def differing_fields(self, other: 'Bimolecular') -> list[str]:
        """List what differs between this bimolecular and the same
        bimolecular read again from another input file.

        Compares the fragment names slot by slot, the ``density`` flags and
        the ``Dummy`` flag. The data of each fragment is compared on the
        fragment itself (``Well.differing_fields``); the ground energy is
        aligned between files separately.

        Args:
            other (Bimolecular): bimolecular read again under the same label.

        Returns:
            list[str]: names of the differing fields (empty when identical).
        """
        fields: list[str] = []
        if self.frag_names != other.frag_names:
            fields.append('fragments')
        if self.fragment_density != other.fragment_density:
            fields.append('fragment density')
        if self.dummy != other.dummy:
            fields.append('dummy')
        return fields

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
