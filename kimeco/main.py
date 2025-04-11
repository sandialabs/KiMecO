import sys
import os
import math
import numpy as np
from typing import Any, Dict
from kimeco.GeneticAlgo.tournament import Tournament
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.generation import Generation
from kimeco.Perturbators.normal import Normal
from kimeco.Perturbators.lognormal import LogNormal
from kimeco.readers.mess_input import MessInputReader
from kimeco.sensitivity.linear import Linear
from kimeco.user_input import check_input
from kimeco.parameters import SOP
from kimeco.scoring_f.weighteddif import WeightedDif
import logging
from kimeco.logger_config import setup_logger


setup_logger()
glog = logging.getLogger()


def main() -> None:
    # if os.path.isfile('kimeco.log'):
    #     for i in range(50):
    #         if not os.path.isfile(f'kimeco.log_{i}'):
    #             os.remove('kimeco.log', f'kimeco.log_{i}')
    #             break
    # Call the setup function to configure logging
    if len(sys.argv) != 2:
        glog.info("""
    KIMECO needs various parameters to be set in a JSON input file.
    This JSON input file should be supplied as the first and only
    argument.

    Usage:  kmo path/to/JSON/input/file.json
    """)
        sys.exit()
    try:
        input_file: str = sys.argv[1]
    except IndexError as e:
        glog.debug(e)
        glog.info('To use KIMECO, supply the input file as argument.')
        sys.exit(-1)

    settings: dict = check_input(input_file=input_file)
    glog.info(f"{'Input reading...':<65}{'PASSED':>15}")
    mr = MessInputReader(settings=settings)
    init_SOP: SOP
    input_tpl: list[str]
    (init_SOP, input_tpl) = mr.read()

    if not os.path.isdir(settings['project_name']):
        os.mkdir(settings['project_name'])
    os.chdir(settings['project_name'])
    location: str = os.getcwd()

    sop_db = SOP_DB(sop=init_SOP,
                    name='KMO_DB_SOP')
    kin_db = KIN_DB(sop=init_SOP,
                    name='KMO_DB_KIN')
    sim_db = SIM_DB(sop=init_SOP,
                    name='KMO_DB_SIM')
    glog.info(f"{'Creating databases...':<65}{'PASSED':>15}")

    # Define which scoring function to use
    if settings['scoring_func'].casefold() == 'weighteddif':
        sf = WeightedDif(settings=settings)
    else:
        # Default scoring function
        sf = WeightedDif(settings=settings)
    glog.info(f"{'Scoring function:':<65}{sf.name:>15}")

    pert: Normal | LogNormal = set_pert(
        settings=settings,
        init_SOP=init_SOP)
    pert.set_gen_fact(0)
    glog.info(f"{'Perturbator:':<65}{pert.name:>15}")

    # Sensitivity analysis
    if len(settings['only_perturb']) == 0:
        glog.info(f"{'Running sensitivity analysis':<65}")
        sensitivity = Linear(
            elements=[Element(
                sop=init_SOP,
                id=0)],
            settings=settings,
            rc_tpl=input_tpl,
            loc=location,
            sf=sf,
            pert=pert)
        sensitivity.run()
        settings['only_perturb'] = sensitivity.selected
        f_el = sensitivity.elements[0]
    else:
        f_el = Element(
            sop=init_SOP,
            id=0)
    glog.info(f"{'Parameters selected for perturbation:':<65}")
    pp = ''
    for p in settings['only_perturb']:
        pp += f'{p} '
    glog.info(f"{pp:<65}")

    # Reinitialize the perturbator once the list of parameters to perturb
    # has been reduced
    pert: Normal | LogNormal = set_pert(
        settings=settings,
        init_SOP=init_SOP)
    glog.info(f"{'Selected parameters transmitted to perturbator':<65}")

    first_gen = Generation(
        elements=[f_el],
        settings=settings,
        rc_tpl=input_tpl,
        loc=location,
        sop_db=sop_db,
        kin_db=kin_db,
        sim_db=sim_db,
        sf=sf,
        pert=pert)
    first_gen.run()

    converged = False

    new_elements: list[Element] = [
        Element(
            sop=pert.perturb(sop=init_SOP),
            id=id,
            gen=1)
        for id in range(settings['n_elem'])]

    ga = Tournament(settings=settings,
                    sf=sf,
                    pert=pert)

    # Passed to new generations in the loop
    # in case an element fails and needs to be reset.
    prev_gen: dict[int, Element] = {}
    for id in range(settings['n_elem']):
        prev_gen[id] = first_gen.elements[0]

    median = np.median([
        el.score for el in first_gen.elements
        ])
    goat: list[Element] = [
        el for el in first_gen.elements if el.score <= median]
    old_means, old_stds = get_stats(
        elements=goat,
        settings=settings
        )
    goat_line = ''
    for el in goat:
        goat_line += f'{el.gen}_{el.id} '
    goat_line += '\n'

    with open(location + '/goat.txt', 'w') as f:
        f.write(goat_line)

    # Main loop
    while not converged and Generation.total() < settings['max_gen']:
        new_gen = Generation(elements=new_elements,
                             settings=settings,
                             rc_tpl=input_tpl,
                             loc=location,
                             sop_db=sop_db,
                             kin_db=kin_db,
                             sim_db=sim_db,
                             sf=sf,
                             pert=pert,
                             previous_el=prev_gen
                             )
        new_gen.run()

        # Change the number of elements in goats after the first generation
        if new_gen.id == 1:
            median = np.median([
                el.score for el in new_gen.elements
            ])
            goat: list[Element] = [
                el for el in new_gen.elements if el.score <= median]
        else:
            # Actualize the list of best elements accross all generations
            old_scores: list[float] = np.array([el.score for el in goat])
            low_new: list[Element] = [
                el for el in new_gen.elements
                if el.score < np.max(old_scores) and el not in goat]
            replaced = 0
            if len(low_new) == 0:
                converged = True

            while (len(low_new) != 0 and
                   min([i.score for i in low_new]) <
                   max([el.score for el in goat])):
                low_scores: list[float] = [i.score for i in low_new]
                low_idx: int = low_scores.index(min(low_scores))
                goat_scores: list[float] = [el.score for el in goat]
                goat_idx: int = goat_scores.index(max(goat_scores))
                goat[goat_idx] = low_new.pop(low_idx)
                replaced += 1
            goat_avrg = np.sum([el.score for el in goat])/len(goat)
            glog.info(f'Number of goat replaced: {replaced}')
            glog.info(f'GOAT AVERAGE SCORE: {goat_avrg:>60.3f}')

        # Add the new line in goat.txt
        goat_line = ''
        for el in goat:
            goat_line += '{:9}'.format(f'{el.gen}_{el.id}')
        goat_line += '\n'
        with open(location + '/goat.txt', 'a') as f:
            f.write(goat_line)

        means, stds = get_stats(
            elements=goat,
            settings=settings
            )
        line_tpl = "{name:<25}{mean:>20}{std:>20}"
        glog.info(line_tpl.format(name='PARAMETER',
                                  mean='MEAN',
                                  std='STD'))
        line_tpl = "{name:<25}{mean:>-20.3E}{std:>-20.3E}"
        for k in means:
            glog.info(line_tpl.format(name=k,
                                      mean=means[k],
                                      std=stds[k]))

        if not isconverged(
           threshold=settings['final_conv'],
           old_means=old_means,
           old_stds=old_stds,
           new_means=means,
           new_stds=stds):
            prev_gen, new_elements = ga.next_gen(gen=new_gen)
            old_means: Dict[str, float] = means
            old_stds: Dict[str, float] = stds
        else:
            converged = True
    glog.info('Run Sucessful.')
    glog.info(f'Termination at generation {new_gen.id}')
    glog.info(f'Final score: {new_gen.best_score}')


def isconverged(threshold: float,
                old_means: Dict[str, float],
                old_stds: Dict[str, float],
                new_means: Dict[str, float],
                new_stds: Dict[str, float]) -> bool:
    """Check if the means and standard deviations
    have converged within a user defined threshold.

    Args:
        old_means (Dict[str, float]):
            Old mean values for each key.
        old_stds (Dict[str, float]):
            Old standard deviation values for each key.
        new_means (Dict[str, float]):
            New mean values for each key.
        new_stds (Dict[str, float]):
            New standard deviation values for each key.

    Returns:
        bool: True if all ratios are within user defined %, False otherwise.
    """
    converged = True
    line_format = '   {type:<7}{param:<15}{status:>20}. CHANGE:{ratio:>7.3f}'
    # Check convergence for means
    for key in old_means:
        if key in new_means:
            old_mean: float = old_means[key]
            new_mean: float = new_means[key]
            if old_mean != 0:  # Avoid division by zero
                ratio_mean: float = abs(new_mean - old_mean) / abs(old_mean)
                if ratio_mean > threshold:
                    converged = False
                    glog.info(line_format.format(
                        type='MEAN',
                        param=key,
                        status='NOT CONVERGED',
                        ratio=ratio_mean
                    ))
                else:
                    glog.info(line_format.format(
                        type='MEAN',
                        param=key,
                        status='CONVERGED',
                        ratio=ratio_mean
                    ))
            else:
                glog.info(f'Warning: {key} skipped (div 0)')
                glog.info(f'Mean old: {old_mean}')
                glog.info(f'Mean new: {new_mean}')

    # Check convergence for standard deviations
    for key in old_stds:
        if key in new_stds:
            old_std: float = old_stds[key]
            new_std: float = new_stds[key]
            if old_std != 0:  # Avoid division by zero
                ratio_std: float = abs(new_std - old_std) / abs(old_std)
                if ratio_std > threshold:
                    converged = False
                    glog.info(line_format.format(
                        type='STD',
                        param=key,
                        status='NOT CONVERGED',
                        ratio=ratio_std
                    ))
                else:
                    glog.info(line_format.format(
                        type='STD',
                        param=key,
                        status='CONVERGED',
                        ratio=ratio_std
                    ))
            else:
                glog.info(f'Warning: {key} skipped (div 0)')
                glog.info(f'StdD old: {old_std}')
                glog.info(f'StdD new: {new_std}')

    return converged


def set_pert(settings,
             init_SOP: SOP) -> Normal | LogNormal:
    if settings['pert'] == 'normal':
        pert = Normal(settings=settings,
                      initial_SOP=init_SOP)
    elif settings['pert'] == 'lognormal':
        pert = LogNormal(settings=settings,
                         initial_SOP=init_SOP)
    else:
        raise NotImplementedError('Unknown type of perturbator.')
    return pert


def get_stats(elements: list[Element],
              settings: dict[str, Any]
              ) -> tuple[Dict[str, float], Dict[str, float]]:
    """Calculate the standard deviation of each key in the
    parameters_names dictionary across all SOP objects.

    Returns:
        Dict[str, float]: Dictionary with the mean values for each key.
        Dict[str, float]:
            Dictionary with the standard deviation for each key.
    """

    sop_list: list[SOP] = [
        el.sop for el in elements
        ]

    # Initialize dictionaries to hold the sum of values,
    # sum of squared values, and a count of SOPs
    sum_values: Dict[str, float] = {}
    sum_squared_values: Dict[str, float] = {}
    count: int = len(sop_list)

    # Iterate through each SOP object
    for sop in sop_list:
        parameters = sop.parameters_names
        for key, value in parameters.items():
            if key not in settings['only_perturb']:
                continue
            if key not in sum_values:
                sum_values[key] = 0.0
                sum_squared_values[key] = 0.0
            sum_values[key] += value
            sum_squared_values[key] += value ** 2

    # Calculate the standard deviation for each key
    stddev_values: Dict[str, float] = {}
    mean_values: Dict[str, float] = {}
    for key in sum_values:
        mean: float = sum_values[key] / count
        mean_values[key] = mean
        variance: float = (sum_squared_values[key] / count) - (mean ** 2)
        stddev_values[key] = math.sqrt(variance) if variance > 0 else 0.0

    return mean_values, stddev_values
