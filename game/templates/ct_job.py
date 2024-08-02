ctjobtpl = """import cantera as ct
from game.customrate import MessData, MessRate

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

spec = gas.species()

# Arrays to hold the datas
times = np.zeros(tot_steps)
moleFrac = np.ndarray((tot_steps+1, gas.X.size))
moleFrac[0] = gas.X

# Arrays to hold the datas
for idx, i in enumerate(spec):
    if i.name == 'c2h5':
        print(gas.X[idx])
        print(moleFrac[:,idx])"""