import copy
import sys

print(sys.path)
if '/home/csoulie/GAME/game' in sys.path:
    sys.path.pop(sys.path.index('/home/csoulie/GAME/game'))
    sys.path.append('/home/csoulie/GAME')

from game.readers.mess import MessReader
from game.writers.mess import MessWriter

def main():
    try:
        input_file = sys.argv[1]
    except IndexError:
        print('To use game, supply one argument being the input file!')
        sys.exit(-1)
    
    mr = MessReader(input_file)
    [init_SOP, mess_tpl]= mr.read()
    mw = MessWriter(init_SOP, copy.copy(mess_tpl))

    mw.write()

