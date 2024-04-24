from game.readers.mess import MessReader
from game.parameters import SOP

me = MessReader('/home/csoulie/projects/ethylperoxy/me/mess_0000.inp')
[init_SOP, mess_tpl]= me.read()
for line in mess_tpl:
    print(line[:-1])