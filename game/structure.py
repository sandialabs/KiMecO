from ase.atoms import Atoms


class Structure(Atoms):
    """Base object of GAME. Can be a Well or a barrier."""
    def __init__(self, elements: str, geom: list[list[float]]) -> None:
        super().__init__(symbols=elements, positions=geom)
        self.energy: float = 0.0
