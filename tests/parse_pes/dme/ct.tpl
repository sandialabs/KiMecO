import sys
import json
import cantera as ct
from kimeco.cantera.customrate import MessData, MessRate
import numpy as np
from scipy.constants import gas_constant
import os
import copy
import time
import cantera.with_units as ctu
import pyarrow as pa
import pyarrow.feather as feather
from kimeco.kinmec import KiMec
from kimeco._kimeco import KiMecO
ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity

R = Q_(gas_constant, 'J mol^-1 K^-1')
Vol = Q_(1, 'cm^3')

kmo = KiMecO(input_file='{input_file}',
             init_loc='{init_loc}',
             name='E{mdl_id:04d}_sims',
             sim_job=True)
kmo.initialize_workdir()
scratchdir = '{scratchdir}'
os.chdir(scratchdir)


exp_id = int(sys.argv[1])
mdl_id = {mdl_id}
experiment = kmo.settings['experiments'][exp_id]
kmo.mech.prepare_mech()
tbl_map_by_pes = {tbl_map_by_pes}
rates_by_pes = {rates_by_pes}
gas = kmo.mech.get_updated_mech(
    rates_by_pes=rates_by_pes,
    tbl_map_by_pes=tbl_map_by_pes)

p = experiment.P
t = experiment.T

gas.X = experiment.X
pres = Q_(f"{{p}} {{experiment['pres_unit']}}")
temp = Q_(f"{{t}} K")

# Total number of molecules
gas.TP = temp.magnitude, np.round(pres.to("Pa").magnitude, 5)
# number of mol of gas in 1 cm^3


import cantera as ct

ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity

R = Q_(gas_constant, 'J mol^-1 K^-1')
Vol = Q_(1, 'cm^3')

ntot = (pres*Vol/(R*temp)).to('molecule')

reactor = ct.ConstPressureMoleReactor(contents=gas, name='r1', energy='off')
net = ct.ReactorNet([reactor])
# Higher values make the simulation less accurate but easier to converge
net.atol = 1e-15
net.rtol = 1e-15

sim_time = 0.0
# In seconds
times = experiment.data[0].tolist()
all_tsteps = np.array({all_tsteps})
tot_steps = all_tsteps[exp_id]

to_watch = experiment.species
traces = {{}}
traces['time'] = np.array(times)

names = []

# Arrays to hold the datas
spec = gas.species()
for idx, i in enumerate(spec):
    if i.name in to_watch:
        traces[i.name] = np.full(tot_steps, gas.X[idx])
        names.append(i.name)

# For instrument response function
current_time = -10

n_micro = 10  # number of micro-steps for instrument response function

for idx, t in enumerate(times):
    # Instrument response function  # Uncoment if response on
    if idx < len(times)-1: # avoid error for last time, uses last dt
        dt = times[idx+1] - times[idx]

    for micro_step in np.linspace(t-dt/2, t+dt/2, n_micro):
        if micro_step <= 0:
            continue
        if micro_step > current_time:
            current_time = micro_step
            net.advance(current_time)
        for snum, i in enumerate(spec):
            if i.name in to_watch:
                traces[i.name][idx] += (gas.X[snum] * ntot.magnitude)/n_micro
    # net.advance(t) # Remove if response on
    # for snum, i in enumerate(spec):
    #     if i.name in to_watch:
            # density (molecules/cm^3)
            # traces[i.name][idx] = gas.X[snum] * ntot.magnitude
            # Remove if response on
traces_serializable = \
    {{key: value.tolist() if isinstance(value, np.ndarray)
    else value for key, value in traces.items()}}
# Serializing json
json_object = json.dumps(traces_serializable, indent=4)
# Writing to sample.json
with open(
    f"{gen_name}E{mdl_id:04d}S{{exp_id:02d}}.json", "w"
    ) as outfile:
    outfile.write(json_object)
while not os.path.exists(f"{gen_name}E{mdl_id:04d}S{{exp_id:02d}}.json"):
    time.sleep(3)


