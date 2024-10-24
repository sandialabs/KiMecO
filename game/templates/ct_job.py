ctjobtpl = """import cantera as ct
from game.cantera.customrate import MessData, MessRate
from game.database.game_db import Game_db
import numpy as np
import sqlalchemy
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

for n in range(tot_steps-1):
    sim_time = mystep*(n+1)
    net.advance(sim_time)
    traces['time'][n+1] = sim_time
    for idx, i in enumerate(spec):
        if i.name in to_watch:
            traces[i.name][n+1] = gas.X[idx]

row_ids = [i for i in RangeIndex(start={sim_id}*len(df),
                                 stop={sim_id}*len(df)+len(df),
                                 step=1)]
indexes: MultiIndex = MultiIndex.from_product([
    [{sim_id}],
    [gas.P],
    [gas.T],
    traces['time']],
    names=['P', 'T', 'sim_id', 'time'])
del traces['time']
df = DataFrame(traces,
               index=indexes,
               )

df: DataFrame = df.reset_index()
df.index = row_ids
df.index.name = 'id'
db.save_data(table='G{gen}',
             df=df,
             mode='append')

"""
