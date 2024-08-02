import cantera as ct
from game.cantera.customrate import MessData, MessRate
import os
import numpy as np

gas = ct.Solution('~/projects/ethylperoxy/me/sim1.yaml')
gas.TP = 300, 101325
start_compo = {
    'c2h5':0.00000005,
    'c2h6':0.000001,
    'o2':0.1
}
n2 = 1
x = ""
for key, value in start_compo.items():
    x += f"{key}:{value},"
    n2 -= value
x += f"n2: {n2}"
gas.X = x
gas.TP = 300, 1013.25
reactor = ct.ConstPressureMoleReactor(contents=gas, name='r1', energy='off')
net = ct.ReactorNet([reactor])
time = 0.0
# Arrays to hold the datas
times = np.zeros(200)
data = np.zeros((200, 4))
for n in range(20):
    time += 0.0005
    net.advance(time)
    print(gas.X)
    times[n] = time  # time in s
    data[n, 0] = reactor.T

print(data)
