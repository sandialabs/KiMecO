from typing import Any
from game.scoring_f.scoring import Scoring
from game.simulation import SIM


class WeightedDif(Scoring):

    def score(self,
              sim: SIM,
              exp_profiles: dict[str, list[float]]) -> float:
        """Calculate the score of a sim as the cumulated difference.
        Weights can be given to 

        Args:
            sim (SIM): _description_
            exp_profiles (dict[str, list[float]]): _description_

        Returns:
            float: _description_
        """
        n_exp: int = len(self.settings['rc_temp']) *\
                     len(self.settings['rc_pres'])
        w_exp: list[float] = self.settings['w_exp']

        score = 0.0
        for p in range(len(self.settings['rc_pres'])):
            for t in range(len(self.settings['rc_temp'])):
                sim_index: int = p*len(self.settings['rc_temp']) + t
                w_exp_i: float = w_exp[sim_index]
                for specie in sim.species:
                    w_specie: float = self.settings['w_species'][specie]
                    for timestep in range(len(sim.profiles[sim_index]['time'])):
                        score += (w_exp_i * w_specie *
                                  sim.profiles[sim_index][specie][timestep] -
                                  exp_profiles[sim_index][specie][timestep])
        return score
