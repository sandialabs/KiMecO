import sys
import os
from telnetlib import EL
from game.GeneticAlgo.ga import GeneticAlgorythm
from game.GeneticAlgo.tournament import Tournament
from game.element import Element
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

    pert = Perturbator(settings=settings)


    if not os.path.isdir(settings['project_name']):
        os.mkdir(settings['project_name'])
    os.chdir(settings['project_name'])
    location: str = os.getcwd()

    sop_db = Game_db(name='GAME_DB_SOP')
    kin_db = Game_db(name='GAME_DB_KIN')
    sim_db = Game_db(name='GAME_DB_SIM')

    first_gen = Generation(elements=[Element(sop=init_SOP, id=0)],
                           set=settings,
                           rc_tpl=input_tpl,
                           loc=location,
                           sop_db=sop_db,
                           kin_db=kin_db,
                           sim_db=sim_db)

    first_gen.run()

    converged = False

    new_elements: list[Element] = [
        Element(sop=pert.perturb(sop=init_SOP), id=id)
        for id in range(settings['n_elem'])]

    ga = Tournament(settings=settings)

    # Passed to new generations in the loop
    # in case an element fails and needs to be reset.
    prev_gen: dict[int, Element] = {}
    for id in range(settings['n_elem']):
        prev_gen[id] = first_gen.elements[0]

    while not converged or Generation.__id < settings['max_gen']:
        new_gen = Generation(elements=new_elements,
                             set=settings,
                             rc_tpl=input_tpl,
                             loc=location,
                             sop_db=sop_db,
                             kin_db=kin_db,
                             sim_db=sim_db,
                             previous_el=prev_gen)
        new_gen.run()
        if not ga.converged(gen=new_gen):
            prev_gen, new_elements = ga.next_gen(gen=new_gen)
        else:
            converged = True
    print(f'Run Sucessful. Termination at generation {new_gen.id}')
