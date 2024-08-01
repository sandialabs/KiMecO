ct_tpl = """import cantera as ct
from game.customrate import MessData, MessRate

sim_id = {sim_id}
gas = ct.Solution('{sim_id}.yaml')

gas.X = {compo}
gas.TP = {T}, {P}

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