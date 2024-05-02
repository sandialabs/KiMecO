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
    def energy(self) -> float:
        e = 0.0
        for frag in self.fragments:
            e += frag.energy
        return e
    
    def set_fragments(self, frags: list[Well]) -> None:
        self.fragments = frags

    def add_new_frag(self, name: str, *args) -> None:
        frag = Well(name, *args)
        self.fragments.append(frag)

    def frag_names(self) -> list[str]:
        names: list = []
        for frag in self.fragments:
            names.append(frag.name)
        return names
    
