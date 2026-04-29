from kimeco.scoring_f.scoring import Scoring
from kimeco.simulation import SIM
import numpy as np
from numpy.typing import NDArray
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kimeco.experiments.experiment import Experiment


class WeightedDif(Scoring):
    def __init__(self,
                 settings: dict[str, Any],
                 **kwargs) -> None:
        super().__init__(settings, **kwargs)
        self.name = 'W-difference'

    @property
    def default_score(self) -> float:
        return 9999999.9

    def score(self,
              sim: SIM) -> list[float]:
        """Calculate the score of a sim as the cumulated difference.
        Weights can be given to species and TP conditions

        Args:
            sim (SIM): SIM object

        Returns:
            float: the score of the model
        """
        exp_scores: list[float] = []
        for idx, exp in enumerate(self.settings['experiments']):
            sim_prof = sim.profiles[idx]
            if sim_prof is None:
                raise IndexError(
                    f'Missing simulation profile for exp {idx}'
                )
            exp_scores.append(self.score_experiment(sim_prof, exp))
        return exp_scores

    def score_experiment(self,
                         sim_profile: NDArray,
                         exp: 'Experiment') -> float:
        """Score a single experiment.

        Args:
            sim_profile (NDArray): Row-oriented profile with row 0 as time.
            exp (Experiment): Experiment containing reference data, errors,
                per-species weights and experiment weight.

        Returns:
            float: scalar score of the experiment.
        """
        if exp.data is None or exp.error is None or exp.sp_weights is None:
            raise ValueError('Experiment is missing data/error/weights')
        if sim_profile.shape[0] == exp.data.shape[0]:
            sim_conc = sim_profile[1:]
        else:
            # Legacy SIM stores concentration-only arrays.
            sim_conc = sim_profile
        exp_conc: NDArray = exp.data[1:]
        exp_err: NDArray = exp.error[1:]
        dif: NDArray = np.average(
            np.abs(((exp_conc - sim_conc)**2)/(exp_err**2)),
            axis=1
        )
        return float(np.average(dif * exp.sp_weights) * exp.weight)
