import cantera as ct
from cantera import Solution
import numpy as np
from game.parameters import SOP
from game.rate_constants import RateCon


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCon,
                 ct_sim: str) -> None:
        """Cantera simulation object. 
        Modify the cantera simulation provided by the user
        depending on the set of parameters and the rate coefficiecients.

        Args:
            sop (SOP): Set Of Parameters objects
            kin (RateCon): Rate Constants object
            ct_sim (str): Path to the YAML file provided by the user
        """
        self.SOP: SOP = sop
        self.ct_sim: str = ct_sim
        self.sim: Solution = ct.Solution(ct_sim)

    def show_info(self):
        self.sim()

# gas1.TP = 1200, 101325

# gas2 = ct.Solution('cant.yaml', 'game_0d')
# diamond = ct.Solution('diamond.yaml', 'diamond')
# diamond_surf = ct.Interface('diamond.yaml' , 'diamond_100',
#                             [gas2, diamond])

# spec = ct.Species(['CH4','O2','CO2','H2O','N2'])
# rxns = ct.Reaction.add_

# Torr2Pa = 133.3223684  # Multiply torr by this to convert them into pascal

# temp = 300 # Kelvin
# pres: float = 7.6 * Torr2Pa  # Pa

# gas1.TP = temp, pres

# # Initial composition
# gas1.X = {"fr_3": 1,
#           "fr_4": 1}