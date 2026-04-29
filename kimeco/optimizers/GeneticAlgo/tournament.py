import time
from copy import deepcopy

from kimeco.logger_config import KMOLogger
from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.model import Model
from kimeco.generation import Generation
import random
from typing import Any
from kimeco.scoring_f.scoring import Scoring


class Tournament(GeneticAlgorithm):
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
        self.name = 'Tournament'

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
        # Change the intensity of the perturbation
        # Work on a new list to avoid mutating the previous generation.
        next_gen: list[Model] = list(gen.models)
        # shuffled: list[Model] = copy.copy(gen.models)
        shuffled: list[int] = [i for i in range(len(next_gen))]
        # Safe guard
        for i in shuffled:
            if i != next_gen[i].id:
                raise AttributeError(
                    f'The models of Generation {gen.id} are not ordered!')
        random.shuffle(shuffled)
        prev_gen: dict[int, Model] = {}
        half = int(len(shuffled)/2)
        for idx in range(len(shuffled[:half])):
            el1: Model = next_gen[shuffled[idx]]
            el2: Model = next_gen[shuffled[idx+half]]
            if el1.score < el2.score:
                winner: Model = el1
                loser: Model = el2
            else:
                winner: Model = el2
                loser: Model = el1
            # Prev gen saves the winners from which a new model is created.
            prev_gen[loser.id] = next_gen[winner.id]
            next_gen[loser.id] = Model(
                sop=self.pert.perturb(sop=deepcopy(winner.sop)),
                id=loser.id,
                gen=gen.id+1)
            end_time: float = time.time()
            runtime: float = end_time - start_time
            message: str = f'Time to create next generation: {runtime:.2f}s'
            self.klog.info(message)
        return prev_gen, next_gen
