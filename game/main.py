import copy
import sys


from game.readers.mess import MessReader
from game.writers.mess import MessWriter
from game.templates import slurm_mess.tpl

def main():
    try:
        input_file = sys.argv[1]
    except IndexError:
        print('To use GAME, supply one argument being the input file!')
        sys.exit(-1)
    
    mr = MessReader(input_file)
    [init_SOP, mess_tpl]= mr.read()
    mw = MessWriter(init_SOP, copy.copy(mess_tpl))

    mw.write('initial_mess.inp')



