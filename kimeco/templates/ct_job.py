ctjobtpl = """import cantera as ct
from kimeco.cantera.customrate import MessData, MessRate
from kimeco.database.sim_db import SIM_DB
import numpy as np
from scipy.constants import gas_constant
import pickle
import os
import copy
import time
import cantera.with_units as ctu
import json
import psutil
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity

R = Q_(gas_constant, 'J mol^-1 K^-1')
Vol = Q_(1, 'cm^3')

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
            time.sleep(1)
        else:
            break
    with open('{sim_name}.pkl', 'rb') as pkl_file:
        time.sleep(1)
        wf_gas = pickle.load(pkl_file)
except EOFError as e:
    print(e)
    raise KeyError('Unsuccesful opening of {sim_name}.pkl.')

gas = ct.Solution(name=wf_gas.name,
                       thermo='ideal-gas',
                       kinetics='gas',
                       species=wf_gas.species(),
                       reactions=wf_gas.reactions())
gas.X = {initial_X}
pres = Q_(f"{{wf_gas.P}} {pres_unit}")
temp = Q_(f"{{wf_gas.T}} K")
# Total number of molecules
ntot = (pres*Vol/(R*temp)).to('molecule')
gas.TP = wf_gas.T, np.round(pres.to("Pa").magnitude, 5)
# number of mol of gas in 1 cm^3

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

# For instrument response function
cumul_zero = copy.deepcopy(traces)
cumul = copy.deepcopy(cumul_zero)
current_time = -10

# Get the current process
process = psutil.Process()

# Get memory info
memory_info = process.memory_info()

# Print memory usage in bytes
print(f"RSS: {{memory_info.rss / (1024 ** 2):.2f}} MB")  # Resident Set Size in MB
print(f"VMS: {{memory_info.vms / (1024 ** 2):.2f}} MB")  # Virtual Memory Size in MB
for idx, t in enumerate(times):
    # # Instrument response function  # Uncoment if response on
    # if idx < len(times)-1:
    #     # avoid error for last time
    #     dt = times[idx+1] - times[idx]
    # cumul = copy.deepcopy(cumul_zero)
    # count = 0
    # for micro_step in np.arange(t-dt/2, t+dt/2, dt/10):
    #     if micro_step <= 0:
    #         continue
    #     count += 1
    #     if micro_step > current_time:
    #         current_time = micro_step
    #         net.advance(current_time)
    #     for snum, i in enumerate(spec):
    #         if i.name in to_watch:
    #             cumul[i.name][idx] += gas.X[snum] * ntot.magnitude
    net.advance(t) # Remove if response on
    for snum, i in enumerate(spec):
        if i.name in to_watch:
            # density (molecules/cm^3)
            traces[i.name][idx] = gas.X[snum] * ntot.magnitude  # Remove if response on
            # traces[i.name][idx] = cumul[i.name][idx]/count  # Uncoment if response on
# unique ids of rows in the DB
row_ids = [i for i in range({el_num}*block_size+start_idx,
                            {el_num}*block_size+start_idx+len(times),
                            1)]
for idx, id in enumerate(row_ids):
    row_dict = {{}}
    for col in traces:
        row_dict[col] = traces[col][idx]

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
while not os.path.exists(f"{gen_name}E{el_num:04d}S{{sim_in_element:02d}}.json"):
    time.sleep(3)
# Get the current process
process = psutil.Process()

# Get memory info
memory_info = process.memory_info()

# Print memory usage in bytes
print(f"RSS: {{memory_info.rss / (1024 ** 2):.2f}} MB")  # Resident Set Size in MB
print(f"VMS: {{memory_info.vms / (1024 ** 2):.2f}} MB")  # Virtual Memory Size in MB
"""
