from game.scoring_f.scoring import Scoring
from game.simulation import SIM
import numpy as np
from numpy import float64
from numpy.typing import NDArray


class WeightedDif(Scoring):

    @property
    def default_score(self):
        return 9999999.9

    def score(self,
              sim: SIM) -> float:
        """Calculate the score of a sim as the cumulated difference.
        Weights can be given to species and TP conditions

        Args:
            sim (SIM): SIM object

        Returns:
            float: the score of the element
        """

        exp_profiles: dict[str, list[float]] = self.settings['exp_profiles']
        n_exp: int = len(self.settings['rc_temp']) *\
            len(self.settings['rc_pres'])

        score = 0.0
        sp_weight: NDArray[float64] = np.array(
            [sim.settings['w_species'][sp] for sp in sim.species])
        for p in range(len(self.settings['rc_pres'])):
            for t in range(len(self.settings['rc_temp'])):
                sim_index: int = p*len(self.settings['rc_temp']) + t
                w_exp_i = self.settings['w_exp'][sim_index]
                ordered_profiles: NDArray[float64] = np.zeros((
                    len(sim.species),
                    len(exp_profiles[sim_index][sim.species[0]])))
                cur_sim_profile = sim.profiles[sim_index][:, 5:].T
                for idx, specie in enumerate(sim.species):
                    ordered_profiles[idx] = exp_profiles[sim_index][specie]
                score += (w_exp_i * np.sum(
                          np.sum(np.abs(cur_sim_profile -
                          ordered_profiles)/n_exp, axis=1) * sp_weight/len(sim.species)))
        return score
