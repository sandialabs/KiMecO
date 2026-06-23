from kimeco.logger_config import KMOLogger
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.model import Model
from kimeco.generation import Generation
import numpy as np
from numpy.typing import NDArray
from typing import Any
from kimeco.scoring_f.scoring import Scoring
import time
from copy import deepcopy


class BMCMC:
    @staticmethod
    def compute_weight_diagnostic(scores: NDArray) -> dict[str, Any]:
        """Compute normalized weights and ESS-based diversity diagnostics.

        Args:
            scores: Array of model scores (lower is better).

        Returns:
            dict[str, float]: Normalized weights, ESS, ESS/N ratio, and
            the maximum normalized weight.
        """
        scores = np.asarray(scores, dtype=float)
        if scores.size == 0:
            return {
                'weights': np.array([], dtype=float),
                'ess': 0.0,
                'ess_over_n': 0.0,
                'max_weight': 0.0,
            }

        raw_weights = np.exp(-scores / 10.0)

        total = float(np.sum(raw_weights))
        weights = raw_weights / total

        # Effective Sample Size (ESS) calculation
        ess = 1.0 / float(np.sum(weights**2))
        ess_over_n = ess / float(scores.size)

        return {
            'weights': weights,
            'ess': float(ess),
            'ess_over_n': float(ess_over_n),
            'max_weight': float(np.max(weights)),
        }

    def __init__(self,
                 settings: dict[str, Any],
                 sf: Scoring,
                 pert: Perturbator,
                 sop_db: SOP_DB,
                 sim_db: SIM_DB,
                 kin_db: KIN_DB,
                 f_mdl: Model,
                 input_tpls: list[list[str]],
                 klog: KMOLogger) -> None:
        self.settings = settings
        self.sf = sf
        self.pert = pert
        self.sop_db = sop_db
        self.sim_db = sim_db
        self.kin_db = kin_db
        self.f_mdl = f_mdl
        self.input_tpls = input_tpls
        self.klog = klog
        self.name = 'BMCMC'

    def create_next_gen(self,
                        gen: Generation
                        ) -> tuple[dict[int, Model], list[Model]]:
        """Pair all models, keep the one with the best score,
        and create a new model from the loser.

        Args:
            gen (Generation): previous generation

        Returns:
            list[Model]: list of models of the new generation.
        """
        start_time: float = time.time()
        new_mdls = 0
        gen_len: int = len(gen.models)
        available_ids: list[int] = [i for i in range(gen_len)]
        scores: NDArray = np.asarray(
            [mdl.score for mdl in gen.models], dtype=float
        )
        diagnostic = self.compute_weight_diagnostic(scores)
        child_prob = diagnostic['weights']
        self.klog.info(
            'BMCMC weight diagnostic: '
            f'ESS={diagnostic["ess"]:.2f}, '
            f'ESS/N={diagnostic["ess_over_n"]:.3f}, '
            f'max_weight={diagnostic["max_weight"]:.4f}'
        )

        # Resample parents from the normalized exponential weights.
        parent_indices = np.random.choice(
            np.arange(len(gen.models)),
            size=gen_len,
            replace=True,
            p=child_prob,
        )

        next_gen: list[Model] = list(gen.models)
        prev_gen: dict[int, Model] = {}

        # Create one child per sampled parent, using the parent as the
        # lineage source and perturbing its SOP to generate the next model.
        for new_mdl_id, parent_idx in enumerate(parent_indices):
            parent = gen.models[int(parent_idx)]
            child_id = available_ids.pop(-1)
            prev_gen[child_id] = parent
            next_gen[child_id] = Model(
                sop=self.pert.perturb(sop=deepcopy(parent.sop)),
                id=child_id,
                gen=gen.id + 1,
            )
            new_mdls += 1
        msg: str = f'{new_mdls} new models created.'
        self.klog.info(msg)
        end_time: float = time.time()
        runtime: float = end_time - start_time
        message: str = f'Time to create next generation: {runtime:.2f}s'
        self.klog.info(message)
        return prev_gen, next_gen
