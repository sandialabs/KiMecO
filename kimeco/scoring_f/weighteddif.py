from kimeco.scoring_f.scoring import Scoring
from kimeco.simulation import SIM
import numpy as np
from numpy import float64
from numpy.typing import NDArray
from typing import Any


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
            float: the score of the element
        """

        exp_prof: list[NDArray] = self.settings['exp_profiles']
        exp_errs: list[NDArray] = self.settings['exp_errors']

        score = np.array([0.0 for sp in sim.sc_species])
        for p in range(len(self.settings['rc_pres'])):
            for t in range(len(self.settings['rc_temp'])):
                sim_index: int = p*len(self.settings['rc_temp']) + t
                exp_sp_weight: NDArray[float64] = \
                    self.settings['weights'][sim_index]
                dif = np.sum(
                    np.abs(
                        (((1/exp_errs[sim_index][1:])**2)
                         / len(exp_prof[sim_index][0])) *
                        (sim.profiles[sim_index].T[2:] -
                         exp_prof[sim_index][1:])**2
                        ),  # Normalize time
                    axis=1
                    )
                # Accumulate and normalize the x
                score += dif * exp_sp_weight
        return score.tolist()
