from kimeco.logger_config import KMOLogger
from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.model import Model
from kimeco.generation import Generation
import random
import numpy as np
from numpy.typing import NDArray
from typing import Any
from kimeco.scoring_f.scoring import Scoring
import time
from copy import deepcopy


class Exponential(GeneticAlgorithm):
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
        super().__init__(
            settings=settings,
            sf=sf,
            pert=pert,
            input_tpls=input_tpls,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            f_mdl=f_mdl,
            klog=klog)
        self.name = 'Exponential'

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
        scores: NDArray = np.array([mdl.score for mdl in gen.models])
        child_prob: NDArray = np.exp(
            (np.min(scores) - scores)/np.median(scores)
            )
        idxs = range(gen_len)
        # Always keep the best model
        best_idx: int = int(np.where(max(child_prob) == child_prob)[0][0])
        to_perturb: dict[int, int] = {best_idx: 1}
        idx: int = random.choice(idxs)
        selected = 2  # Best model already in to_perturb
        # Switch focus on good score as gen.id increases
        std: float = np.exp(1-(np.sqrt(gen.id)/2))/2
        # Select the source of all models for next gen
        while selected < gen_len:
            rng: float = np.random.normal(1, std)
            # Add the model from previous gen and one perturbed version
            if rng < child_prob[idx]:
                if idx not in to_perturb:
                    if selected < gen_len - 1:
                        to_perturb[idx] = 1
                        selected += 2
                    idx = random.choice(idxs)
                # Then perturb it if selected again
                else:
                    to_perturb[idx] += 1
                    selected += 1
                    idx = random.choice(idxs)
                # otherwise try another
            else:
                idx = random.choice(idxs)
        next_gen: list[Model] = list(gen.models)
        prev_gen: dict[int, Model] = {}
        # Remove the selected models from the available ids
        for mdl_id in to_perturb:
            if mdl_id in available_ids:
                available_ids.pop(available_ids.index(mdl_id))
                prev_gen[mdl_id] = next_gen[mdl_id]
        # Perturb n times the selected models
        for mdl_id, n_perturb in to_perturb.items():
            for i in range(n_perturb):
                new_mdl_id: int = available_ids.pop(-1)
                prev_gen[new_mdl_id] = next_gen[mdl_id]
                next_gen[new_mdl_id] = Model(
                    sop=self.pert.perturb(sop=deepcopy(next_gen[mdl_id].sop)),
                    id=new_mdl_id,
                    gen=gen.id+1)
                new_mdls += 1
        msg: str = f'{new_mdls} new models created.'
        self.klog.info(msg)
        end_time: float = time.time()
        runtime: float = end_time - start_time
        message: str = f'Time to create next generation: {runtime:.2f}s'
        self.klog.info(message)
        return prev_gen, next_gen
