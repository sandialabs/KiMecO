ctjobtpl = """import sys
import cantera as ct
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
from kimeco._kimeco import KiMecO
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity

R = Q_(gas_constant, 'J mol^-1 K^-1')
Vol = Q_(1, 'cm^3')

kmo = KiMecO(input_file='{input_file}',
             init_loc='{init_loc}',
             name='E{el_num:04d}_sims',
             sim_job=True)
kmo.initialize_workdir()
kmo.initialize_databases()

scratchdir = kmo.settings['scratch_base'] +\
             kmo.settings["project_name"] + '/' +\
             '{gen_name}E{el_num:04d}S'
os.chdir(scratchdir)

exp_id = int(sys.argv[1])
el_num = {el_num}
sim_id = len(kmo.settings['exp_profiles']) * el_num + exp_id

kin_mech = KiMec(file=f"{{kmo.init_loc}}/{{kmo.settings['initial_mess']}}",
                 settings=kmo.settings,
                 sop_tpl=kmo.init_SOP)
tbl_map = {tbl_map}
rates = {rates}
initial_X = {initial_X}
exp_num = 0
for p in kmo.settings['rc_pres']:
    for t in kmo.settings['rc_temp']:
        if exp_num == exp_id:
            break
        else:
            exp_num += 1

gas = kin_mech.get_updated_mech(
    rates=rates,
    tbl_map=tbl_map)
gas.X = initial_X[exp_id]
pres = Q_(f"{{p}} {pres_unit}")
temp = Q_(f"{{t}} K")

# Total number of molecules
ntot = (pres*Vol/(R*temp)).to('molecule')
gas.TP = temp.magnitude, np.round(pres.to("Pa").magnitude, 5)
# number of mol of gas in 1 cm^3

reactor = ct.ConstPressureMoleReactor(contents=gas, name='r1', energy='off')
net = ct.ReactorNet([reactor])
# Higher values make the simulation less accurate but easier to converge
net.atol = 1e-15
net.rtol = 1e-15

sim_time = 0.0
# In seconds
times = {time}[exp_id]
all_tsteps = np.array({all_tsteps})
block_size = np.sum(all_tsteps)
start_idx = np.sum(all_tsteps[:exp_id])
tot_steps = all_tsteps[exp_id]

to_watch = {to_watch}
traces = {{}}
traces['P'] = np.full(tot_steps, gas.P)
traces['T'] = np.full(tot_steps, gas.T)
traces['sim_id'] = np.full(tot_steps, sim_id)
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

for idx, t in enumerate(times):
    # Instrument response function  # Uncoment if response on
    if idx < len(times)-1:
        # avoid error for last time
        dt = times[idx+1] - times[idx]
    cumul = copy.deepcopy(cumul_zero)
    count = 0
    for micro_step in np.linspace(t-dt/2, t+dt/2, 10):
        if micro_step <= 0:
            continue
        count += 1
        if micro_step > current_time:
            current_time = micro_step
            net.advance(current_time)
        for snum, i in enumerate(spec):
            if i.name in to_watch:
                cumul[i.name][idx] += gas.X[snum] * ntot.magnitude
    # net.advance(t) # Remove if response on
    for snum, i in enumerate(spec):
        if i.name in to_watch:
            # density (molecules/cm^3)
            # traces[i.name][idx] = gas.X[snum] * ntot.magnitude  # Remove if response on
            traces[i.name][idx] = cumul[i.name][idx]/count  # Uncoment if response on
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
    f"{gen_name}E{el_num:04d}S{{exp_id:02d}}.json", "w"
    ) as outfile:
    outfile.write(json_object)
while not os.path.exists(f"{gen_name}E{el_num:04d}S{{exp_id:02d}}.json"):
    time.sleep(3)


"""
