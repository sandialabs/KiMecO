from flask.config import T
from kimeco.database.kimeco_db import Kimeco_db
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.parameters import SOP
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from kimeco.q_sys import JobStatus
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
                             sim_db: SIM_DB,
                             table) -> None:
        for sim in range(len(self.sim.simulations)):
            sim_id: int = self.id * len(self.sim.simulations) + sim
            if self.sim.profiles[sim] is None:
                sim_db.prepare_batch_select(
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
        """Save the SOP of this element in the given database.

        Args:
            db (Kimeco_db): SOP_DB
            table (str): table name
        """
        db.prepare_batch_upsert(table=table,
                                id=self.id,
                                values=self.sop.parameters_names)
    
    def save_sim(self,
                 db: SIM_DB,
                 table: str,
                 sim_num: int) -> None:
        """Save the given simulation in the corresponding db

        Args:
            db (SIM_DB): Kimeco SIM database object
            sim_num (int): index of the simulation for this element
        """

        sim_id: int = sim_num + self.id * len(self.sim.simulations)
        all_tsteps = np.array(
            [len(i[0]) for i in self.sim.settings['exp_profiles']])
        block_size = np.sum(all_tsteps)
        start_idx = np.sum(all_tsteps[:sim_num])
        tot_steps = all_tsteps[sim_num]

        p: float = self.sop.rc_pres[sim_id // len(self.sop.rc_temp)]
        t: float = self.sop.rc_temp[sim_id % len(self.sop.rc_temp)]

        to_watch: list[str] = self.sim.sv_species
        traces: dict[str, Any] = {}
        traces['P'] = np.full(tot_steps, p)
        traces['T'] = np.full(tot_steps, t)
        traces['sim_id'] = np.full(tot_steps, sim_id)
        traces['time'] = self.sim.settings['exp_profiles'][sim_num][0]
        row_ids: list[int] = [i for i in range(self.id*block_size+start_idx,
                              self.id*block_size+start_idx+len(traces['time']),
                              1)]
        names = []

        # Arrays to hold the datas
        for idx, i in enumerate(to_watch):
            traces[i] = np.full(tot_steps, self.sim.profiles[sim_num][:, idx+2])
            names.append(i)
        for idx, id in enumerate(row_ids):
            row_dict = {}
            for col in traces:
                row_dict[col] = traces[col][idx]
            db.prepare_batch_upsert(table=table,
                                    id=id,
                                    values=row_dict)