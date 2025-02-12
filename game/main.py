import sys
import os
from typing import Dict
from game.GeneticAlgo.tournament import Tournament
from game.database.kin_db import KIN_DB
from game.database.sim_db import SIM_DB
from game.database.sop_db import SOP_DB
from game.element import Element
from game.generation import Generation
from game.Perturbators.normal import Normal
from game.readers.mess_input import MessInputReader
from game.user_input import check_input
from game.parameters import SOP
from game.scoring_f.weighteddif import WeightedDif


def main() -> None:
    if len(sys.argv) != 2:
        print("""
    ROCKME needs various parameters to be set in a JSON input file.
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

    sop_db = SOP_DB(sop=init_SOP,
                    name='GAME_DB_SOP')
    kin_db = KIN_DB(sop=init_SOP,
                    name='GAME_DB_KIN')
    sim_db = SIM_DB(sop=init_SOP,
                    name='GAME_DB_SIM')

    # Define which scoring function to use
    if settings['scoring_func'].casefold() == 'weighteddif':
        sf = WeightedDif(settings=settings)
    else:
        # Default scoring function
        sf = WeightedDif(settings=settings)

    if settings['pert'] == 'normal':
        pert = Normal(settings=settings,
                      initial_SOP=init_SOP)
    else:
        raise NotImplementedError('Currently, the only type of perturbator\
                                   implemented is <normal>')
    pert.set_get_fact(0)

    first_gen = Generation(elements=[Element(sop=init_SOP, id=0, sf=sf)],
                           set=settings,
                           rc_tpl=input_tpl,
                           loc=location,
                           sop_db=sop_db,
                           kin_db=kin_db,
                           sim_db=sim_db,
                           sf=sf,
                           pert=pert)
    first_gen.run()
    old_means, old_stds = first_gen.get_stats()

    converged = False

    new_elements: list[Element] = [
        Element(sop=pert.perturb(sop=init_SOP), id=id, sf=sf)
        for id in range(settings['n_elem'])]

    ga = Tournament(settings=settings,
                    sf=sf,
                    pert=pert)

    # Passed to new generations in the loop
    # in case an element fails and needs to be reset.
    prev_gen: dict[int, Element] = {}
    for id in range(settings['n_elem']):
        prev_gen[id] = first_gen.elements[0]

    while not converged and Generation.total() < settings['max_gen']:
        # init_t_start = time()
        new_gen = Generation(elements=new_elements,
                             set=settings,
                             rc_tpl=input_tpl,
                             loc=location,
                             sop_db=sop_db,
                             kin_db=kin_db,
                             sim_db=sim_db,
                             sf=sf,
                             pert=pert,
                             previous_el=prev_gen)
        # init_t_end = time()
        # gen_init_time = init_t_end - init_t_start
        # print('Initialization of generation')
        new_gen.run()
        means, stds = new_gen.get_stats()
        if not rockme_converged(threshold = settings['rockme_conv'],
                                old_means=old_means,
                                old_stds=old_stds,
                                new_means=means,
                                new_stds=stds):
            print(f'Generation {new_gen.id} finished.')
            print(f'Best score: {new_gen.best_score}')
            print('Statistics:')
            print('{:16s} {:10s} {:10s}'.format(
                'Parameter name',
                'Mean',
                '2 STD dev'
            ))
            for k in means:
                print('{:16s} {:-10.2e} {:-10.2e}'.format(
                    k,
                    means[k],
                    stds[k]
                ))
            prev_gen, new_elements = ga.next_gen(gen=new_gen)
            old_means: Dict[str, float] = means
            old_stds: Dict[str, float] = stds
        else:
            converged = True

    print('Run Sucessful.')
    print(f'Termination at generation {new_gen.id} with score {new_gen.best_score}')


def rockme_converged(threshold: float,
                     old_means: Dict[str, float],
                     old_stds: Dict[str, float],
                     new_means: Dict[str, float],
                     new_stds: Dict[str, float]) -> bool:
    """Check if the means and standard deviations
    have converged within a user defined threshold.

    Args:
        old_means (Dict[str, float]): Old mean values for each key.
        old_stds (Dict[str, float]): Old standard deviation values for each key.
        new_means (Dict[str, float]): New mean values for each key.
        new_stds (Dict[str, float]): New standard deviation values for each key.

    Returns:
        bool: True if all ratios are within 5%, False otherwise.
    """

    # Check convergence for means
    for key in old_means:
        if key in new_means:
            old_mean = old_means[key]
            new_mean = new_means[key]
            if old_mean != 0:  # Avoid division by zero
                ratio_mean = abs(new_mean - old_mean) / abs(old_mean)
                if ratio_mean > threshold:
                    return False
            else:
                print(f'Warning: {key} skipped (div 0)')
                print(f'Mean old: {old_mean}')
                print(f'Mean new: {new_mean}')

    # Check convergence for standard deviations
    for key in old_stds:
        if key in new_stds:
            old_std = old_stds[key]
            new_std = new_stds[key]
            if old_std != 0:  # Avoid division by zero
                ratio_std = abs(new_std - old_std) / abs(old_std)
                if ratio_std > threshold:
                    return False
            else:
                print(f'Warning: {key} skipped (div 0)')
                print(f'StdD old: {old_std}')
                print(f'StdD new: {new_std}')

    return True
