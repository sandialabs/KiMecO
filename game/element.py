from game.database.game_db import Game_db
from game.parameters import SOP
from game.rate_coef import RateCo
from game.scoring_f.weighteddif import WeightedDif
from game.simulation import SIM
from typing import Any


class Element:
    __id = 0

    def __init__(self,
                 sop: SOP) -> None:
        """An element is part of a generation and has
        different attributes, such as an id and a status.
        It is mainly a container object.

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
        self.score: float

    def save_sop(self,
                 db: Game_db) -> None:
        self.sop.save_in_db(db=db)
    
    def calc_score(self,
                   settings:dict[str, Any]) -> None:
        """Calculate the score of the element
        using the user requested function.

        Args:
            settings (dict[str, Any]): User input + default settings
        """
        if settings['scoring_func'].casefold() == 'weighteddif':
            sf = WeightedDif(settings=settings)
        self.score = sf.score(sim=self.sim,
                              exp_profiles=settings['exp_profiles'])

