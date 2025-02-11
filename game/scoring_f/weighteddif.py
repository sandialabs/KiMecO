from game.scoring_f.scoring import Scoring
from game.simulation import SIM
import numpy as np
from numpy import float64
from numpy.typing import NDArray


class WeightedDif(Scoring):

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
        n_exp: int = len(self.settings['rc_temp']) *\
            len(self.settings['rc_pres'])

        sp_weight: NDArray[float64] = np.array(
            [sim.settings['w_species'][sp] for sp in sim.species])
        score = np.array([0.0 for sp in sim.species])
        for p in range(len(self.settings['rc_pres'])):
            for t in range(len(self.settings['rc_temp'])):
                sim_index: int = p*len(self.settings['rc_temp']) + t
                w_exp_i = self.settings['w_exp'][sim_index]
                # dtype of sim_prof and exp_prof[sim_index] should be the same
                dif = w_exp_i * np.sum(
                    np.abs(
                        sim.profiles[sim_index].T - exp_prof[sim_index]
                        )/len(exp_prof[sim_index][0]),  # Normalize time
                    axis=1
                    )
                # Accumulate and normalize the x
                score += dif[1:]
        score *= sp_weight/len(sp_weight)/n_exp
        return score.tolist()
