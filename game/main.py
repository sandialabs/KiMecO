import sys
import os

from game.generation import Generation
from game.perturbator import Perturbator
from game.queue.q_sys import QueueingSystem
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

    q_sys = QueueingSystem(max_jobs=settings['max_jobs'],
                           max_cpu=settings['max_cpu'],
                           max_mem=settings['max_mem'],
                           cpu_job=settings['cpu_jop'],
                           mem_job=settings['mem_job'],
                           location=os.getcwd())

    mr = MessInputReader(settings=settings)
    init_SOP: SOP
    input_tpl: list[str]
    (init_SOP, input_tpl) = mr.read()

    pert = Perturbator(ptype='standard')

    first_gen = Generation(sop=init_SOP,
                           n=1,
                           pert=pert,
                           set=settings,
                           rc_tpl=input_tpl)

    first_gen.run(q_sys=q_sys)
