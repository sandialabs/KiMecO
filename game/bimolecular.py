from game.well import Well


class Bimolecular:
    """A well is a minima on the PES.
    It must have a name and an energy."""
    def __init__(self, name: str) -> None:
        self.name: str = name
        self.fragments: list = []

    @property
    def r_name(self) -> str:
        return self.name

    @property
    def r_energy(self) -> float:
        return self.energy

    def set_energy(self, value: float) -> None:
        """Simple function to be coherent with other objects

        Args:
            value (float): energy of the object (kcal/mol)
        """
        self.energy = value

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
        frag = Well(name, *args)
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
