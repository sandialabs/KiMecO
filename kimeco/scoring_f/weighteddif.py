from kimeco.scoring_f.scoring import Scoring
from kimeco.simulation import SIM
import numpy as np
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
        score: NDArray = np.array([0.0 for sp in sim.sc_species])
        for p in range(len(self.settings['rc_pres'])):
            for t in range(len(self.settings['rc_temp'])):
                sim_index: int = p*len(self.settings['rc_temp']) + t
                sim_prof: NDArray = sim.profiles[sim_index]
                exp_prof: NDArray = self.settings['exp_profiles'][sim_index][1:]
                exp_errs: NDArray = self.settings['exp_errors'][sim_index][1:]
                sp_weight: NDArray = self.settings['weights'][sim_index]
                dif: NDArray = np.average(
                    np.abs(
                        ((exp_prof - sim_prof)**2)/(exp_errs**2)
                        ),
                    axis=1
                    )
                # Accumulate and normalize the x
                score += dif * sp_weight
        return score.tolist()
