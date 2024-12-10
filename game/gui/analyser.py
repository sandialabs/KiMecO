from abc import ABC, abstractmethod

from game.database.game_db import Game_db


class Analyser(ABC):
    """Analysers are special classes used by GAME
    graphical interface. Each analyser have methods
    specific to analyse the data corresponding to the
    database attached to them.
    """
    def __init__(self,
                 db: Game_db) -> None:
        self.db: Game_db = db

    @abstractmethod
    def layout(self) -> None:
        """Every Analyser must have a layout method
        that will be called by the dash app.
        """
        pass
