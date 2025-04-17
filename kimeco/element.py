from kimeco.database.kimeco_db import Kimeco_db
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from typing import Any
import numpy as np
from enum import Enum


class ElementStatus(Enum):
    SOP = 'sop'
    KIN = 'kin'
    SIM = 'sim'
    SCORING = 'scoring'
    TO_SAVE = 'to_save'
    DONE = 'DONE'
    RESET = 'reset'


class Element:

    def __init__(self,
                 sop: SOP,
                 id: int,
                 gen: int = 0) -> None:
        """An element is part of a generation and has
        different attributes, such as an id and a status.
        It is mainly a container object.

        Args:
            sop (SOP): perturbed set of parameters

        Attributes:
            status (ElementStatus): Status of the element.
            id (int): ID of the element.
            gen (int): ID of the generation of origin
        """
        self.sop: SOP = sop
        self.gen: int = gen
        self.status: ElementStatus = ElementStatus.SOP
        self.id: int = id
        self.sop.id = self.id
        self.rateCoef: RateCo
        self.sim: SIM
        # Purely for debugging
        self.reset: int = 0
        self.name: str = f'E{self.id:04d}'

    def save_kin(self,
                 db: KIN_DB,
                 table: str) -> None:
        """Save the RateCoef in the database in the table
        of the generation

        Args:
            db (Kimeco_db): KIN Kimeco database
            table (str): Generation name
        """
        rows = np.array(self.rateCoef.recover_rslts())
        # Happens if the ME calculation didn't converge
        if len(rows) == 0:
            self.status = ElementStatus.RESET
            return
        else:
            self.status = ElementStatus.KIN
        for row in rows:
            vals: dict[str, Any] = {}
            for idx, col in enumerate(db.columns):
                vals[col] = row[idx+1]
            db.prepare_batch_upsert(table=table,
                                    id=row[0],
                                    values=vals)

    def request_sim_profiles(self,
                             db: SIM_DB,
                             table) -> None:

        for sim in range(len(self.sim.simulations)):
            sim_id: int = self.id * len(self.sim.simulations) + sim
            if self.sim.profiles[sim] is None:
                db.prepare_batch_select(
                    table=table,
                    sim_id=sim_id)

    @property
    def scores(self) -> list[float]:
        return [v for v in self.sop.scores.values()]

    @property
    def score(self) -> float:
        """Return the score of the selected species.

        Returns:
            float:
                Sum of the score selected by the user with score_sp.
        """
        return np.sum(self.scores)

    def prepare_upsert(self,
                       db: Kimeco_db,
                       table: str) -> None:
        db.prepare_batch_upsert(table=table,
                                id=self.id,
                                values=self.sop.parameters_names)
