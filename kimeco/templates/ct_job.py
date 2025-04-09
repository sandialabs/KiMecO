ctjobtpl = """import cantera as ct
from kimeco.cantera.customrate import MessData, MessRate
from kimeco.database.sim_db import SIM_DB
import numpy as np
from numpy import float32
from pandas import MultiIndex, DataFrame, RangeIndex
from scipy.constants import Avogadro
import pickle
import os
import time
import cantera.with_units as ctu
import sqlalchemy
import json
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity

db = SIM_DB(name='{db.name}',
             path='{db.path}')

i = 0
#Wait for the creation of the pickle file
while not os.path.isfile('{sim_name}.pkl'):
    time.sleep(5)
    i += 1
    if i > 3:
        exit()
try:
    # Happens if the file is being written
    while True:
        if os.path.getsize('{sim_name}.pkl') == 0:
            time.sleep(0.2)
        else:
            break
    with open('{sim_name}.pkl', 'rb') as pkl_file:
        wf_gas = pickle.load(pkl_file)
except EOFError as e:
    raise KeyError('Unsuccesful opening of {sim_name}.pkl.')

gas = ct.Solution(name=wf_gas.name,
                       thermo='ideal-gas',
                       kinetics='gas',
                       species=wf_gas.species(),
                       reactions=wf_gas.reactions())
gas.X = {initial_X}
gas.TP = wf_gas.T, np.round(Q_(f"{{wf_gas.P}} torr").to("Pa").magnitude, 5)
# number of mol of gas in 1 cm^3
ntot = wf_gas.P*0.001/(62.363577*wf_gas.T)

reactor = ct.ConstPressureMoleReactor(contents=gas, name='r1', energy='off')
net = ct.ReactorNet([reactor])
# Higher values make the simulation less accurate but easier to converge
net.atol = 1e-15
net.rtol = 1e-15

sim_time = 0.0
# In seconds
times = {time}
all_tsteps = np.array({all_tsteps})
block_size = np.sum(all_tsteps)
sim_in_element = {sim_id} % len(all_tsteps)
start_idx = np.sum(all_tsteps[:sim_in_element])
tot_steps = all_tsteps[sim_in_element]

to_watch = {to_watch}
traces = {{}}
traces['P'] = np.full(tot_steps, gas.P)
traces['T'] = np.full(tot_steps, gas.T)
traces['sim_id'] = np.full(tot_steps, {sim_id})
traces['time'] = np.array(times)

names = []

# Arrays to hold the datas
spec = gas.species()
for idx, i in enumerate(spec):
    if i.name in to_watch:
        traces[i.name] = np.full(tot_steps, gas.X[idx])
        names.append(i.name)

for idx, t in enumerate(times):
    if idx == 0:
        # First time should be 0, hence initial concentration
        continue
    net.advance(t)
    for snum, i in enumerate(spec):
        if i.name in to_watch:
            # density (molecules/cm^3)
            traces[i.name][idx] = gas.X[snum] * ntot * Avogadro
# unique ids of rows in the DB
row_ids = [i for i in range({el_num}*block_size+start_idx,
                            {el_num}*block_size+start_idx+len(times),
                            1)]
for idx, id in enumerate(row_ids):
    row_dict = {{}}
    for col in traces:
        row_dict[col] = traces[col][idx]
#     db.prepare_batch_upsert(table={gen_name},
#                             id=id,
#                             values=row_dict)
# db_wait = np.random.lognormal(mean=np.log(1), sigma=1)
# time.sleep(db_wait)

# try:
#     db.batch_upsert()
# # Happens when db is occupied/locked
# except sqlalchemy.exc.OperationalError:
traces['row_ids'] = row_ids
traces_serializable = \
    {{key: value.tolist() if isinstance(value, np.ndarray)
    else value for key, value in traces.items()}}
# Serializing json
json_object = json.dumps(traces_serializable, indent=4)

# Writing to sample.json
with open(
    f"{gen_name}E{el_num:04d}S{{sim_in_element:02d}}.json", "w"
    ) as outfile:
    outfile.write(json_object)

"""
