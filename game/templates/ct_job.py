ctjobtpl = """import cantera as ct
from game.customrate import MessData, MessRate
from game.game_db import Game_db
import numpy as np
import pandas as pd

db = Game_db(db_name={db_name},
             db_path={db_path},
             host_name={host_name})

#Wait for the creation of the pickle file
while not os.path.isfile(os.path.join(here, '{sim_id}.pkl')):
    time.sleep(5)
    i += 1
    if i > 3:
        exit()
try:
    with open(os.path.join(here, '{sim_id}.pkl'), 'rb') as pkl_file:
        gas = pickle.load(pkl_file)
except EOFError:
    raise KeyError('Unsuccesful opening of {sim_id}.pkl'.pkl, retrying...')

reactor = ct.ConstPressureMoleReactor(contents=gas, name='r1', energy='off')
net = ct.ReactorNet([reactor])

time = 0.0
tot_time = {sim_time} #in seconds
mystep = {tstep} #in seconds
tot_steps = int((tot_time - time)/mystep)

to_watch = ['c2h5', 'o2', 'c2h6']

traces = {{}}

names = []

# Arrays to hold the datas
spec = gas.species()
for idx, i in enumerate(spec):
    if i.name in to_watch:
        traces[i.name] = np.full(tot_steps, gas.X[idx])
        names.append(i.name)

times = np.zeros(tot_steps)
moleFrac = np.ndarray((tot_steps+1, gas.X.size))
moleFrac[0] = gas.X

for n in range(tot_steps):
    time += mystep
    net.advance(time)
    times[n+1] = time
    for idx, i in enumerate(spec):
        if i.name in to_watch:
            traces[i.name][n+1] = gas.X[idx]

df = pd.DataFrame.from_dict(traces)
df.index = times

db.save_data(name={sim_id},
             df=df)

"""