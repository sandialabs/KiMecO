import sys
import os
from game.generation import Generation
from game.perturbator import Perturbator
from game.readers.mess_input import MessInputReader
# from game.rate_constants import RateCo
from game.user_input import check_input
from game.parameters import SOP
# from game.simulation import SIM
# from game.customrate import MessData, MessRate


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

    pert = Perturbator(ptype='default',
                       settings=settings)

    if not os.path.isdir(settings['project_name']):
        os.mkdir(settings['project_name'])
    os.chdir(settings['project_name'])
    location: str = os.getcwd()

    first_gen = Generation(sop=init_SOP,
                           n=1,
                           pert=pert,
                           set=settings,
                           rc_tpl=input_tpl,
                           loc=location)

    first_gen.run()
