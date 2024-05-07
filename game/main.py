import copy
import sys

from game.readers.mess import MessReader
from game.kinetic_constants import KinCon

def main():
    try:
        input_file = sys.argv[1]
    except IndexError:
        print('To use GAME, supply one argument being the input file!')
        sys.exit(-1)
    
    mr = MessReader(input_file)
    [init_SOP, input_tpl]= mr.read()

    init_KinCon = KinCon(init_SOP,
                         software='mess',
                         software_tpl=input_tpl,
                         id='init')
    
    init_KinCon.calculate()
    init_KinCon.recover_rslts()





