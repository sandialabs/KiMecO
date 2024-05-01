from game.readers.mess import MessReader
from game.writers.mess import MessWriter
from game.parameters import SOP

mr = MessReader('/home/csoulie/projects/ethylperoxy/me/mess_0000.inp')
[init_SOP, mess_tpl]= mr.read()
mw = MessWriter(init_SOP, copy.copy(mess_tpl))
for line in mess_tpl:
    print(line[:-1])

