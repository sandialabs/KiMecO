import sys
import os
from game.generation import Generation
from game.perturbator import Perturbator
from game.readers.mess_input import MessInputReader
from game.database.game_db import Game_db
from game.user_input import check_input
from game.parameters import SOP


def main() -> None:
    try:
        input_file: str = sys.argv[1]
    except IndexError:
        print('To use GAME, supply one argument being the input file!')
        sys.exit(-1)

    settings: dict = check_input(input_file=input_file)

    mr = MessInputReader(settings=settings)
    init_SOP: SOP
    input_tpl: list[str]
    (init_SOP, input_tpl) = mr.read()

    pert = Perturbator(ptype='nominal',
                       settings=settings)


    if not os.path.isdir(settings['project_name']):
        os.mkdir(settings['project_name'])
    os.chdir(settings['project_name'])
    location: str = os.getcwd()

    sop_db = Game_db(name=f'GAME_DB_SOP')
    kin_db = Game_db(name=f'GAME_DB_KIN')
    sim_db = Game_db(name=f'GAME_DB_SIM')

    first_gen = Generation(sop=init_SOP,
                           n=1,
                           pert=pert,
                           set=settings,
                           rc_tpl=input_tpl,
                           loc=location,
                           sop_db=sop_db,
                           kin_db=kin_db,
                           sim_db=sim_db,)

    first_gen.run()
