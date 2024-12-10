import sys
import os
from game.GeneticAlgo.tournament import Tournament
from game.element import Element
from game.generation import Generation
from game.perturbator import Perturbator
from game.readers.mess_input import MessInputReader
from game.database.game_db import Game_db
from game.user_input import check_input
from game.parameters import SOP
from game.scoring_f.weighteddif import WeightedDif


def main() -> None:
    if len(sys.argv) != 1:
        print("""
    GAME needs various parameters to be set in a JSON input file.
    This JSON input file should be supplied as the first and only
    argument.

    Usage:  game path/to/JSON/input/file.json
    """)
        sys.exit()
    try:
        input_file: str = sys.argv[1]
    except IndexError:
        print('To use GAME, supply the input file as argument.')
        sys.exit(-1)

    settings: dict = check_input(input_file=input_file)

    mr = MessInputReader(settings=settings)
    init_SOP: SOP
    input_tpl: list[str]
    (init_SOP, input_tpl) = mr.read()

    if not os.path.isdir(settings['project_name']):
        os.mkdir(settings['project_name'])
    os.chdir(settings['project_name'])
    location: str = os.getcwd()

    sop_db = Game_db(name='GAME_DB_SOP')
    kin_db = Game_db(name='GAME_DB_KIN')
    sim_db = Game_db(name='GAME_DB_SIM')

    # Define which scoring function to use
    if settings['scoring_func'].casefold() == 'weighteddif':
        sf = WeightedDif(settings=settings)
    else:
        # Default scoring function
        sf = WeightedDif(settings=settings)

    first_gen = Generation(elements=[Element(sop=init_SOP, id=0, sf=sf)],
                           set=settings,
                           rc_tpl=input_tpl,
                           loc=location,
                           sop_db=sop_db,
                           kin_db=kin_db,
                           sim_db=sim_db,
                           sf=sf)
    first_gen.run()

    converged = False

    pert = Perturbator(settings=settings)

    new_elements: list[Element] = [
        Element(sop=pert.perturb(sop=init_SOP), id=id, sf=sf)
        for id in range(settings['n_elem'])]

    ga = Tournament(settings=settings, sf=sf)

    # Passed to new generations in the loop
    # in case an element fails and needs to be reset.
    prev_gen: dict[int, Element] = {}
    for id in range(settings['n_elem']):
        prev_gen[id] = first_gen.elements[0]

    while not converged and Generation.total() < settings['max_gen']:
        new_gen = Generation(elements=new_elements,
                             set=settings,
                             rc_tpl=input_tpl,
                             loc=location,
                             sop_db=sop_db,
                             kin_db=kin_db,
                             sim_db=sim_db,
                             sf=sf,
                             previous_el=prev_gen)
        new_gen.run()
        if not ga.converged(gen=new_gen):
            print(f'Generation {new_gen.id} finished.')
            print(f'Best score: {new_gen.best_score}')
            prev_gen, new_elements = ga.next_gen(gen=new_gen)
        else:
            converged = True

    print(f'Run Sucessful. Termination at generation {new_gen.id} with score {new_gen.best_score}')
