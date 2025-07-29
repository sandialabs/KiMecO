import sys
import os
import math
import numpy as np
import shutil
from typing import Any, Dict
from kimeco.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.GeneticAlgo.tournament import Tournament
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element, ElementStatus
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.generation import Generation
from kimeco.readers.mess_input import MessInputReader
from kimeco.sensitivity.linear import Linear
from kimeco.user_input import check_input
from kimeco.parameters import SOP
from kimeco.scoring_f.weighteddif import WeightedDif
from kimeco.logger_config import setup_logger
from logging import Logger


klog: Logger = setup_logger('KiMecO.log')


def main() -> None:
    # if os.path.isfile('kimeco.log'):
    #     for i in range(50):
    #         if not os.path.isfile(f'kimeco.log_{i}'):
    #             os.remove('kimeco.log', f'kimeco.log_{i}')
    #             break
    # Call the setup function to configure logging
    if len(sys.argv) != 2:
        klog.info("""
    KIMECO needs various parameters to be set in a JSON input file.
    This JSON input file should be supplied as the first and only
    argument.

    Usage:  kmo path/to/JSON/input/file.json
    """)
        sys.exit()
    try:
        input_file: str = sys.argv[1]
    except IndexError as e:
        klog.debug(e)
        klog.info('To use KIMECO, supply the input file as argument.')
        sys.exit(-1)

    # Initialize the settings and first SOP
    settings: dict = check_input(input_file=input_file,
                                 klog=klog)
    klog.info(f"{'Input reading...':<65}{'PASSED':>15}")

    mr = MessInputReader(settings=settings)
    init_SOP: SOP
    input_tpl: list[str]
    (init_SOP, input_tpl) = mr.read()
    init_SOP.set_uncertainties(settings=settings)

    # Create the workidir folder
    init_loc: str = os.getcwd()
    if not os.path.isdir(settings['project_name']):
        os.mkdir(settings['project_name'])
    os.chdir(settings['project_name'])
    location: str = os.getcwd()
    with open('mess_tpl', 'w') as f:
        f.writelines(input_tpl)

    # Copy files necessary for MESS calculation
    for file in init_SOP.files2copy:
        shutil.copyfile(f'{init_loc}/{file}', f'{location}/{file}')

    # Create the databases
    sop_db = SOP_DB(sop=init_SOP,
                    name='KMO_DB_SOP',
                    thread=settings['thread'])
    kin_db = KIN_DB(sop=init_SOP,
                    name='KMO_DB_KIN',
                    thread=settings['thread'])
    sim_db = SIM_DB(sop=init_SOP,
                    name='KMO_DB_SIM',
                    thread=settings['thread'])
    klog.info(f"{'Creating databases...':<65}{'PASSED':>15}")

    # Define which scoring function to use
    if settings['scoring_func'].casefold() == 'weighteddif':
        sf = WeightedDif(settings=settings)
    else:
        # Default scoring function
        sf = WeightedDif(settings=settings)
    klog.info(f"{'Scoring function:':<65}{sf.name:>15}")

    # Initialize the perturbator
    pert: Perturbator = Perturbator(
        settings=settings,
        initial_SOP=init_SOP,
        klog=klog
        )
    pert.print_pert_parameters()

    # Perform sensitivity analysis if requested
    first_sensi = False
    if len(settings['only_perturb']) == 0:
        first_sensi = True
        klog.info(f"{'Running sensitivity analysis':<65}")
        sensitivity = Linear(
            elements=[Element(
                sop=init_SOP,
                id=0)],
            settings=settings,
            rc_tpl=input_tpl,
            loc=location,
            sf=sf,
            pert=pert,
            klog=klog)
        sensitivity.run()
        settings['only_perturb'] = sensitivity.selected
        f_el: Element = sensitivity.elements[0]
    else:
        # Check DB for restart if not SA
        if sop_db.table_exists('G0000'):
            rows = sop_db.get_table(table='G0000')
            if len(rows) == 1:
                db_sop = SOP.from_db_row(
                    sop_tpl=init_SOP,
                    row=rows[0][1:]
                    )
                f_el = Element(
                    sop=db_sop,
                    id=0)
                f_el.status = ElementStatus.DONE
        # Otherwise initialize the first Element from scratch
            else:
                f_el = Element(
                    sop=init_SOP,
                    id=0)
        else:
            f_el = Element(
                sop=init_SOP,
                id=0)
    klog.info(f"{'Parameters selected for perturbation:':<65}")
    pp = ''
    for p in settings['only_perturb']:
        pp += f'{p} '
    klog.info(f"{pp:<65}")

    # Reinitialize the perturbator once the list of parameters to perturb
    # has been reduced
    pert: Perturbator = Perturbator(
        settings=settings,
        initial_SOP=init_SOP,
        klog=klog
        )
    klog.info(f"{'Selected parameters transmitted to perturbator':<65}")

    # Everything is initialized, create gen_0
    gen_0 = Generation(
        elements=[f_el],
        settings=settings,
        rc_tpl=input_tpl,
        loc=location,
        sop_db=sop_db,
        kin_db=kin_db,
        sim_db=sim_db,
        sf=sf,
        pert=pert,
        klog=klog)
    # If the sensitivity analysis was run,
    # copy results of unperturbed element for generation 0
    if first_sensi:
        sensitivity.save_initial_element(
            sop_db,
            kin_db,
            sim_db
        )
    gen_0.run()

    converged = False

    ga = Tournament(settings=settings,
                    sf=sf,
                    pert=pert,
                    sop_db=sop_db)

    median = np.median([
        el.score for el in gen_0.elements
        ])
    goat: list[Element] = [
        el for el in gen_0.elements if el.score <= median]
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

    score_line_tpl = '{gen_id:>10s}{best_score:>15s}{score_avrg:>15s}\n'
    with open(location + '/score_info.txt', 'w') as f:
        f.write(score_line_tpl.format(
                gen_id='GEN_ID',
                best_score='BEST SCORE',
                score_avrg='GOAT AVERAGE'))

    new_gen: Generation = gen_0
    # MAIN LOOP
    while not converged and Generation.total() < settings['max_gen']:
        prev_gen, new_elements = get_next_gen(gen=new_gen,
                                              sop_db=sop_db,
                                              settings=settings,
                                              ga=ga,
                                              pert=pert,
                                              )

        new_gen = Generation(elements=new_elements,
                             settings=settings,
                             rc_tpl=input_tpl,
                             loc=location,
                             sop_db=sop_db,
                             kin_db=kin_db,
                             sim_db=sim_db,
                             sf=sf,
                             pert=pert,
                             klog=klog,
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
            goat_avrg = np.sum([el.score for el in goat])/len(goat)
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
                low_scores: list[float] = np.array([i.score for i in low_new])
                low_idx: int = np.argmin(low_scores)
                goat_scores: list[float] = np.array([el.score for el in goat])
                goat_idx: int = np.argmax(goat_scores)
                if goat[goat_idx].score > low_new[low_idx].score:
                    goat[goat_idx] = low_new.pop(low_idx)
                else:
                    msg = 'Bad replacement in goat list'
                    raise ValueError(msg)
                replaced += 1
            goat_avrg = np.average([el.score for el in goat])
            klog.info(f'Number of goat replaced: {replaced}')
            klog.info(f'GOAT AVERAGE SCORE: {goat_avrg:>60.3f}')

        with open(location + '/score_info.txt', 'a') as f:
            f.write(score_line_tpl.format(
                gen_id=f"G{new_gen.id:04d}",
                best_score=f"{new_gen.best_score:.3f}",
                score_avrg=f"{goat_avrg:.3f}"))

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
        klog.info(line_tpl.format(name='PARAMETER',
                                  mean='MEAN',
                                  std='STD'))
        line_tpl = "{name:<25}{mean:>-20.3E}{std:>-20.3E}"
        for k in means:
            klog.info(line_tpl.format(name=k,
                                      mean=means[k],
                                      std=stds[k]))

        if not isconverged(
           threshold=settings['final_conv'],
           old_means=old_means,
           old_stds=old_stds,
           new_means=means,
           new_stds=stds):
            old_means: Dict[str, float] = means
            old_stds: Dict[str, float] = stds
            if new_gen.id % settings['SA_freq'] == 0:
                klog.info('On-the-fly sensitivity analysis.')
                sensitivity = Linear(
                    elements=new_gen.elements,
                    settings=settings,
                    rc_tpl=input_tpl,
                    loc=location,
                    sf=sf,
                    pert=pert,
                    klog=klog)
                sensitivity.run()
                for p in sensitivity.selected:
                    if p not in settings['only_perturb']:
                        klog.info(f'New parameter to perturb: {p}')
                        settings['only_perturb'].append(p)
        else:
            converged = True
    klog.info('Run Sucessful.')
    klog.info(f'Termination at generation {new_gen.id}')
    klog.info(f'Final score: {new_gen.best_score}')


def get_gen_one(settings: dict[str, Any],
                pert: Perturbator,
                gen_0: Generation,
                sop_db: SOP_DB
                ) -> tuple[dict[int, Element], list[Element]]:
    """Perturb the first generation from the initial element

    Args:
        settings (dict[str, Any]): user defined settings + defaults
        pert (Perturbator): perturbator object
        gen_0 (Generation): initial generation only containing unperturbed data

    Returns:
        tuple[dict[int, Element], list[Element]]: _description_
    """
    next_gen: list[Element] = []
    prev_gen: dict[int, Element] = {}
    # Look in the db
    if sop_db.table_exists(f"G{gen_0.id+1:04d}"):
        rows = np.array(sop_db.get_table(f"G{gen_0.id+1:04d}"))
        # Restart if db is complete
        if len(rows) == settings['n_elem'] and\
           settings['restart'] == 'default':
            for id in range(settings['n_elem']):
                next_gen.append(
                    Element(
                        sop=SOP.from_db_row(
                            sop_tpl=gen_0.elements[0].sop,
                            row=rows[rows[:, 0] == id][0, 1:]
                        ),
                        id=id,
                        gen=1)
                    )
                next_gen[-1].status = ElementStatus.DONE
        else:
            next_gen: list[Element] = [
                Element(
                    sop=pert.perturb(sop=gen_0.elements[0].sop),
                    id=id,
                    gen=1)
                for id in range(settings['n_elem'])]
    else:
        next_gen: list[Element] = [
            Element(
                sop=pert.perturb(sop=gen_0.elements[0].sop),
                id=id,
                gen=1)
            for id in range(settings['n_elem'])]

    for id in range(settings['n_elem']):
        prev_gen[id] = gen_0.elements[0]
    return prev_gen, next_gen


def get_next_gen(gen: Generation,
                 sop_db: SOP_DB,
                 settings: dict[str, Any],
                 ga: GeneticAlgorithm,
                 pert: Perturbator
                 ) -> tuple[dict[int, Element], list[Element]]:
    """Returns the elements of the next generation.
    If they are already in db, does not trigger the GA,
    and restart from the db.

    Args:
        gen (Generation): Kimeco generation object
        sop_db (SOP_DB): SOP database
        settings (dict[str, Any]): user input
        ga (GeneticAlgorithm): Chosen genetic algorithm
        pert (Perturbator): perturbator

    Returns:
        tuple[dict[int, Element], list[Element]]: _description_
    """
    if sop_db.table_exists(f"G{gen.id+1:04d}"):
        rows = sop_db.get_table(table=f"G{gen.id+1:04d}")
        if len(rows) == 0:
            if Generation.total() > 1:
                prev_gen, next_gen = ga.create_next_gen(gen)
            else:
                prev_gen, next_gen = get_gen_one(gen_0=gen,
                                                 sop_db=sop_db,
                                                 settings=settings,
                                                 pert=pert)
        elif (len(rows) == int(len(gen.elements)/2) and
              settings['restart'] == 'default'):
            next_gen: list[Element] = []
            prev_gen: dict[int, Element] = {}
            losers = np.array(rows)
            for el in gen.elements:
                if el.id in losers[:, 0]:
                    next_gen.append(Element(
                        sop=SOP.from_db_row(
                            sop_tpl=gen.elements[0].sop,
                            row=losers[losers[:, 0] == el.id][0, 1:]),
                        id=el.id,
                        gen=gen.id+1
                            )
                            )
                    next_gen[-1].status = ElementStatus.DONE
                else:
                    next_gen.append(el)
        else:
            if Generation.total() > 1:
                prev_gen, next_gen = ga.create_next_gen(gen)
            else:
                prev_gen, next_gen = get_gen_one(gen_0=gen,
                                                 settings=settings,
                                                 pert=pert,
                                                 sop_db=sop_db)
    else:
        if Generation.total() > 1:
            prev_gen, next_gen = ga.create_next_gen(gen)
        else:
            prev_gen, next_gen = get_gen_one(gen_0=gen,
                                             sop_db=sop_db,
                                             settings=settings,
                                             pert=pert)
    return prev_gen, next_gen


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
                    klog.info(line_format.format(
                        type='MEAN',
                        param=key,
                        status='NOT CONVERGED',
                        ratio=ratio_mean
                    ))
                else:
                    klog.info(line_format.format(
                        type='MEAN',
                        param=key,
                        status='CONVERGED',
                        ratio=ratio_mean
                    ))
            else:
                klog.info(f'Warning: {key} skipped (div 0)')
                klog.info(f'Mean old: {old_mean}')
                klog.info(f'Mean new: {new_mean}')

    # Check convergence for standard deviations
    for key in old_stds:
        if key in new_stds:
            old_std: float = old_stds[key]
            new_std: float = new_stds[key]
            if old_std != 0:  # Avoid division by zero
                ratio_std: float = abs(new_std - old_std) / abs(old_std)
                if ratio_std > threshold:
                    converged = False
                    klog.info(line_format.format(
                        type='STD',
                        param=key,
                        status='NOT CONVERGED',
                        ratio=ratio_std
                    ))
                else:
                    klog.info(line_format.format(
                        type='STD',
                        param=key,
                        status='CONVERGED',
                        ratio=ratio_std
                    ))
            else:
                klog.info(f'Warning: {key} skipped (div 0)')
                klog.info(f'StdD old: {old_std}')
                klog.info(f'StdD new: {new_std}')

    return converged


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
