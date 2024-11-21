ctjobtpl = """import cantera as ct
from game.cantera.customrate import MessData, MessRate
from game.database.game_db import Game_db
import numpy as np
from numpy import float32
from pandas import MultiIndex, DataFrame, RangeIndex
import pickle
import os
import time
import cantera.with_units as ctu
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity

db = Game_db(name='{db.name}',
             path='{db.path}')

i = 0
#Wait for the creation of the pickle file
while not os.path.isfile('{sim_name}.pkl'):
    time.sleep(5)
    i += 1
    if i > 3:
        exit()
try:
    with open('{sim_name}.pkl', 'rb') as pkl_file:
        wf_gas = pickle.load(pkl_file)
except EOFError:
    raise KeyError('Unsuccesful opening of {sim_name}.pkl.')

gas = ct.Solution(name=wf_gas.name,
                       thermo='ideal-gas',
                       kinetics='gas',
                       species=wf_gas.species(),
                       reactions=wf_gas.reactions())
gas.X = {initial_X}
gas.TP = wf_gas.T, Q_(f"{{wf_gas.P}} torr").to("Pa").magnitude

reactor = ct.ConstPressureMoleReactor(contents=gas, name='r1', energy='off')
net = ct.ReactorNet([reactor])

sim_time = 0.0
# In seconds
time = {time}
# tot_time = {sim_time} #in seconds
# mystep = {tstep} #in seconds
# tot_steps = int((tot_time - sim_time)/mystep)+1
all_tsteps = np.array({all_tsteps})
block_size = np.sum(all_tsteps)
start_idx = np.sum(all_tsteps[:{sim_id}])
tot_steps = all_tsteps[{sim_id}]

to_watch = {to_watch}
traces = {{}}
traces['P'] = np.full(tot_steps, gas.P)
traces['T'] = np.full(tot_steps, gas.T)
traces['sim_id'] = np.full(tot_steps, {sim_id})
traces['time'] = np.array(time)

names = []

# Arrays to hold the datas
spec = gas.species()
for idx, i in enumerate(spec):
    if i.name in to_watch:
        traces[i.name] = np.full(tot_steps, gas.X[idx])
        names.append(i.name)

for idx, t in enumerate(time):
    if idx == 0:
        # First time should be 0, hence initial concentration
        continue
    net.advance(t)
    for snum, i in enumerate(spec):
        if i.name in to_watch:
            traces[i.name][idx] = gas.X[snum]
row_ids = [i for i in range({el_num}*block_size+start_idx,
                            {el_num}*block_size+start_idx+len(time),
                            1)]
for id in row_ids:
    row_dict = {{}}
    for col in traces:
        row_dict[col] = traces[col][id]
    db.prepare_batch_upsert(table='G{gen}',
                            id=id,
                            values=row_dict)
db.batch_upsert(mode='manual')

"""
