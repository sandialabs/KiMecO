from kimeco.database.kimeco_db import Kimeco_db
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP
from kimeco.rate_coef import RateCo
from kimeco.scoring_f.scoring import Scoring
from kimeco.simulation import SIM
from typing import Any
from pandas import DataFrame
import numpy as np
from enum import Enum
import logging
from kimeco.logger_config import setup_logger


setup_logger()
glog = logging.getLogger()


class ElementStatus(Enum):
    SOP = 'sop'
    KIN = 'kin'
    SIM = 'sim'
    SCORING = 'scoring'
    DONE = 'DONE'
    RESET = 'reset'


class Element:

    def __init__(self,
                 sop: SOP,
                 id: int,
                 sf: Scoring,
                 gen: int = 0) -> None:
        """An element is part of a generation and has
        different attributes, such as an id and a status.
        It is mainly a container object.

        Args:
            sop (SOP): perturbed set of parameters

        Attributes:
            status (ElementStatus): Status of the element.
            id (int): ID of the element.
        """
        self.sop: SOP = sop
        self.gen: int = gen
        self.status: ElementStatus = ElementStatus.SOP
        self.id: int = id
        self.sop.id = self.id
        self.rateCoef: RateCo
        self.sim: SIM
        self.sf: Scoring = sf
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
            table (str): Table name (GX)
        """
        df: DataFrame = self.rateCoef.recover_rslts()
        # Happens if the ME calculation didn't converge
        if len(df) == 0:
            self.status = ElementStatus.RESET
            return
        else:
            self.status = ElementStatus.KIN
        ids = [i for i in df.index]
        for db_id in ids:
            vals: dict[str, Any] = df.loc[[db_id]].to_dict()
            for k, v in vals.items():
                vals[k] = v[db_id]
            db.prepare_batch_upsert(table=table,
                                    id=db_id,
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

    def calc_score(self) -> None:
        """Calculate the score of the element
        using the user requested function.
        If the elif statement for a new scoring function
        is missing, also add the chosen string to
        the implemented_sf list in default_settings.py.

        Args:
            settings (dict[str, Any]): User input + default settings
        """
        try:
            scores = self.sf.score(sim=self.sim)
            for idx, k in enumerate(self.sop.scores):
                self.sop.scores[k] = scores[idx]
            self.status = ElementStatus.DONE
        except IndexError:
            # Occurs when a simulation didn't work so profiles were not saved
            self.status = ElementStatus.RESET
            glog.info(f'Resetting element {self.id}: error during scoring.')

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
