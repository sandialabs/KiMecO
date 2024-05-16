import cantera as ct
import numpy as np


# ct.add_directory('~/cantera/my_data_files')
# gas1 = ct.Solution('~/projects/ethylperoxy/me/testphase.yaml')
gas1 = ct.Solution(name = 'test')
gas1()

spec = ct.Species(['CH4','O2','CO2','H2O','N2'])
rxns = ct.Reaction.add_

Torr2Pa = 133.3223684  # Multiply torr by this to convert them into pascal

temp = 300 # Kelvin
pres: float = 7.6 * Torr2Pa  # Pa

gas1.TP = temp, pres

# Initial composition
gas1.X = {"fr_3": 1,
          "fr_4": 1}