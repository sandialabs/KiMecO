from game.bimolecular import Bimolecular
from game.well import Well
from game.structure import Structure

class Barrier(Well):
    """A barrier connect a well to
    a bimolecular prod, or another well"""
    def __init__(self, name: str,
                 lside: Well|Bimolecular,
                 rside: Well|Bimolecular) -> None:
        
        super().__init__(name)
        self.connected: list[Well|Bimolecular] = [lside, rside]
