from game.well import Well

class Bimolecular:
    """A well is a minima on the PES.
    It must have a name and an energy."""
    def __init__(self, name: str) -> None:
        self.name: str = name
        self.fragments: list = []

    @property
    def fragments(self, index) -> Well:
        return self.fragments[index]
    
    @fragments.setter
    def fragments(self, frags: list[Well]) -> None:
        self.fragments = frags

    def add_new_frag(self, name: str, *args) -> None:
        self.fragments.append(Well(name, *args))

    def frag_names(self) -> list[str]:
        names: list = []
        for frag in self.fragments:
            names.append(frag.name)
        return names
    
