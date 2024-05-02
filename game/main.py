import copy
import sys

print(sys.path)
if '/home/csoulie/GAME/game' in sys.path:
    sys.path.pop(sys.path.index('/home/csoulie/GAME/game'))
    sys.path.append('/home/csoulie/GAME')

from game.readers.mess import MessReader
from game.writers.mess import MessWriter


mr = MessReader('/home/csoulie/projects/ethylperoxy/me/mess_0000.inp')
[init_SOP, mess_tpl]= mr.read()
mw = MessWriter(init_SOP, copy.copy(mess_tpl))
for line in mess_tpl:
    print(line[:-1])

mw.write()

