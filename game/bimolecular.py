from typing import Any
from game.well import Well


class Bimolecular:
    """A well is a minima on the PES.
    It must have a name and an energy."""
    def __init__(self,
                 name: str,
                 ct_names: dict[str, str],
                 ) -> None:

        self.name: str = name
        self.fragments: list = []
        self.ct_names: dict[str, str] = ct_names

    @property
    def r_energy(self) -> float:
        return self.energy

    def set_energy(self, value: float) -> None:
        """Simple function to be coherent with other objects

        Args:
            value (float): energy of the object (kcal/mol)
        """
        self.energy: float = value

    def set_fragments(self, frags: list[Well]) -> None:
        """Save a pair of fragments.

        Args:
            frags (list[Well]): pair of fragments
        """
        self.fragments = frags

    def add_new_frag(self, name: str, *args) -> None:
        """Save a new fragment.

        Args:
            name (str): fragment's name
        """
        if name in self.ct_names:
            if self.ct_names[name] == "":
                ct_name: str = name
            else:
                ct_name: str = self.ct_names[name]
        else:
            ct_name: str = name
        frag = Well(name=name, ct_name=ct_name, *args)
        self.fragments.append(frag)

    def frag_names(self) -> list[str]:
        """Return the list of fragments' name for this bimol object

        Returns:
            list[str]: List of fragments' name
        """
        names: list = []
        for frag in self.fragments:
            names.append(frag.name)
        return names

    @property
    def db_dict(self) -> dict[str, Any]:
        db_dict = {
            f"{self.name}_e": self.energy
        }
        return db_dict
