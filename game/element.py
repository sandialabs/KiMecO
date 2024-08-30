from game.game_db import Game_db
from game.parameters import SOP
from game.rate_constants import RateCo
from game.simulation import SIM


class Element:
    __id = 0

    def __init__(self,
                 sop: SOP) -> None:
        """An element is part of a generation and has
        different attributes, such as an id and a status.

        Args:
            sop (SOP): perturbed set of parameters
        
        Attributes:
            status (int): Status of the element
                0 - initialized
                1 - Rate coefficients are submitted
                2 - Rate coefficients are calculated
                3 - Cantera simulations submitted
                4 - Cantera simulations finished
                5 - Scoring is finished for all P and T
            id (int): ID of the element.
        """
        self.sop: SOP = sop
        self.status: int = 0
        self.id: int = Element.__id
        Element.__id += 1
        self.rateCoef: RateCo
        self.sim: SIM

    def save_sop(self,
                 db: Game_db) -> None:
        self.sop.save_in_db(name=f"E{self.id}",
                            db=db)
