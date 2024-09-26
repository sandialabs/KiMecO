ctjobtpl = """import cantera as ct
from game.cantera.customrate import MessData, MessRate
from game.game_db import Game_db
import numpy as np
import pandas as pd
import pickle
import os
import time
import cantera.with_units as ctu
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity
ureg.default_format = '.5f'

db = Game_db(name='{db_name}')

i = 0
#Wait for the creation of the pickle file
while not os.path.isfile('{sim_id}.pkl'):
    time.sleep(5)
    i += 1
    if i > 3:
        exit()
try:
    with open('{sim_id}.pkl', 'rb') as pkl_file:
        wf_gas = pickle.load(pkl_file)
except EOFError:
    raise KeyError('Unsuccesful opening of {sim_id}.pkl.')

gas = ct.Solution(name=wf_gas.name,
                       thermo='ideal-gas',
                       kinetics='gas',
                       species=wf_gas.species(),
                       reactions=wf_gas.reactions())

gas.TP = wf_gas.T, Q_(f"{{wf_gas.P}} torr").to("Pa").magnitude

reactor = ct.ConstPressureMoleReactor(contents=gas, name='r1', energy='off')
net = ct.ReactorNet([reactor])

sim_time = 0.0
tot_time = {sim_time} #in seconds
mystep = {tstep} #in seconds
tot_steps = int((tot_time - sim_time)/mystep)+1

to_watch = {to_watch}

traces = {{'time': np.zeros(tot_steps)}}

names = []

# Arrays to hold the datas
spec = gas.species()
for idx, i in enumerate(spec):
    if i.name in to_watch:
        traces[i.name] = np.full(tot_steps, gas.X[idx])
        names.append(i.name)

times = np.zeros(tot_steps, dtype=float32)
# moleFrac = np.ndarray((tot_steps+1, gas.X.size))
# moleFrac[0] = gas.X

for n in range(tot_steps):
    sim_time += mystep
    net.advance(sim_time)
    traces['time'][n+1] = sim_time
    times[n+1] = sim_time
    for idx, i in enumerate(spec):
        if i.name in to_watch:
            traces[i.name][n+1] = gas.X[idx]

df = pd.DataFrame(traces)
df.index = {sim_id}

db.save_sim_data(df=df)
print('Sim {sim_id} finished successfully!')

"""