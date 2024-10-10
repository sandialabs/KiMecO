from typing import Any
from game.scoring_f.scoring import Scoring
from game.simulation import SIM


class WeightedDif(Scoring):

    def score(self,
              sim: SIM,
              exp_profiles: dict[str, list[float]]) -> float:
        n_exp: int = len(self.settings['rc_temp']) *\
                     len(self.settings['rc_pres'])
        w_exp: list[float] = self.settings['w_exp']

        score = 0.0
        for p in range(len(self.settings['rc_pres'])):
            for t in range(len(self.settings['rc_temp'])):
                sim_index: int = p*len(self.settings['rc_temp']) + t
                w_exp_i: float = w_exp[p*t]
                for specie in sim.species:
                    w_specie = self.settings['w_species'][specie]
                    for t in len(sim.profiles[sim_index]['time']):
                        score += (w_exp_i * w_specie *
                                  sim.profiles[sim_index][specie][t] -
                                  exp_profiles[specie][t])
