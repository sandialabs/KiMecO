from kimeco.database.kimeco_db import Kimeco_db
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from typing import Any
import numpy as np
from kimeco.enums import ModelStatus
from kimeco.q_sys import JobStatus
import pyarrow as pa
import pyarrow.feather as feather
from io import BytesIO
from kimeco.parameter_scoring import (
    get_parameter_uncertainty_scale,
    normalize_score_weights,
)


class Model:
    _score_reference_values: dict[str, float] = {}
    _score_reference_uncertainties: dict[str, float] = {}
    _score_active_params: list[str] = []
    _score_weight_theory: float = 0.5
    _score_weight_experiments: float = 0.5

    def __init__(self,
                 sop: SOP,
                 id: int,
                 gen: int = 0,
                 status: str = ModelStatus.SOP.value) -> None:
        """An model is part of a generation and has
        different attributes, such as an id and a status.
        It is mainly a container object.

        Args:
            sop (SOP): perturbed set of parameters

        Attributes:
            status (ModelStatus): Status of the model.
            id (int): ID of the model.
            gen (int): ID of the generation of origin
        """
        self.sop: SOP = sop
        self.pres: list[float] = sop.pres
        self.temp: list[float] = sop.temp
        self.gen: int = gen
        self.status: ModelStatus = ModelStatus(status)
        self.id: int = id
        self.rateCoef: RateCo
        self.sim: SIM
        # Purely for debugging
        self.reset: int = 0
        self.name: str = f'E{self.id:04d}'
        self.n_exp: int
        self.thread_id: int

    @classmethod
    def configure_scoring(
        cls,
        reference_sop: SOP,
        settings: dict[str, Any],
    ) -> None:
        cls._score_reference_values = {
            key: float(value)
            for key, value in reference_sop.parameters_names.items()
        }
        cls._score_reference_uncertainties = {
            key: float(value)
            for key, value in reference_sop.uncertainties.items()
        }
        cls._score_active_params = list(settings.get('active_p', []))
        (
            cls._score_weight_theory,
            cls._score_weight_experiments,
        ) = normalize_score_weights(settings)

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
        # Only advance to KIN when all MESS outputs were recovered.
        # Keep waiting in SOP when outputs are still incomplete.
        if len(rows) == 0:
            if self.rateCoef.status == JobStatus.FAILED:
                self.status = ModelStatus.RESET
            return
        # avoid changing the status in sensitivity.linear
        if self.status == ModelStatus.SOP:
            self.status = ModelStatus.KIN

        for row in rows:
            vals: dict[str, Any] = {}
            for idx, col in enumerate(db.columns):
                vals[col] = row[idx+1]  # Skip the row_id
            db.prepare_batch_upsert(table=table,
                                    id=row[0],
                                    values=vals)

    def request_sim_profiles(self,
                             sim_db: SIM_DB,
                             table) -> None:
        n_exp: int = len(self.sim.profiles)
        for exp_id in range(n_exp):
            if self.sim.profiles[exp_id] is None:
                sim_db.prepare_batch_select(
                    table=table,
                    mdl_id=self.id,
                    experiment_id=exp_id)

    def get_p_val(self,
                  param: str) -> float:
        """Return the value of the given parameter in the SOP.

        Args:
            param (str): parameter name

        Returns:
            float: value of the parameter
        """
        return self.sop.parameters_names[param]

    @property
    def scores(self) -> list[float]:
        return [v for v in self.sop.scores.values()]

    @property
    def experiment_score(self) -> float:
        return float(np.average(self.scores))

    @property
    def theory_score(self) -> float:
        if len(self._score_active_params) == 0:
            return 0.0
        if len(self._score_reference_values) == 0:
            return 0.0

        score = 0.0
        current_values = self.sop.parameters_names
        normalization_factor = 1/len(self._score_active_params)
        for param in self._score_active_params:
            scale = get_parameter_uncertainty_scale(
                reference_values=self._score_reference_values,
                reference_uncertainties=self._score_reference_uncertainties,
                param=param,
            )
            delta = float(current_values[param]) - self._score_reference_values[param]
            score += (delta ** 2) / (scale ** 2)
        return float(score)*normalization_factor

    @property
    def score(self) -> float:
        """Return the score of the selected species.

        Returns:
            float:
                Weighted total of theory and experiment scores.
        """
        if (len(self._score_active_params) == 0 or
                len(self._score_reference_values) == 0):
            return self.experiment_score
        return float(
            self._score_weight_theory * self.theory_score
            + self._score_weight_experiments * self.experiment_score
        )

    def prepare_upsert(self,
                       db: Kimeco_db,
                       table: str) -> None:
        """Save the SOP of this model in the given database.

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
            sim_num (int): index of the simulation for this model
        """

        exp = self.sim.settings['experiments'][sim_num]
        to_watch: list[str] = exp.species

        sim_prof = self.sim.profiles[sim_num]
        if sim_prof is None:
            raise ValueError(f'Missing simulation profile {sim_num}')
        if sim_prof.shape[0] == len(to_watch) + 1:
            sim_prof = sim_prof[1:]
        traces: dict[str, Any] = {
            'time': exp.data[0].tolist(),
        }
        for idx, sp_name in enumerate(to_watch):
            traces[sp_name] = sim_prof[idx].tolist()

        table_obj = pa.table(traces)
        buf = BytesIO()
        feather.write_feather(table_obj, buf)
        db.prepare_batch_upsert(
            table=table,
            mdl_id=self.id,
            experiment_id=sim_num,
            result=buf.getvalue(),
        )
