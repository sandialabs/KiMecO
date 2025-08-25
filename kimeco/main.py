import sys
import os
import shutil
from kimeco.enums import Optimizers
from kimeco.optimizers.GeneticAlgo.exponential import Exponential
from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm
from kimeco.optimizers.GeneticAlgo.tournament import Tournament
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element, ElementStatus
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.optimizers.nelder_mead import NelderMead
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
    msg = f"{'Parameters selected for perturbation:':<80}"
    msg += '\n'
    msg += "{}".format(settings['only_perturb']).replace("'", '"')
    klog.info(msg)

    # Reinitialize the perturbator once the list of parameters to perturb
    # has been reduced
    pert: Perturbator = Perturbator(
        settings=settings,
        initial_SOP=init_SOP,
        klog=klog
        )
    klog.info(f"{'Selected parameters transmitted to perturbator':<80}")

    if first_sensi:
        sensitivity.save_initial_element(
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db
        )
    if settings['optimizer'] == Optimizers.GA:
        if settings['ga_type'].casefold() == 'tournament':
            optimizer = Tournament(
                settings=settings,
                sf=sf,
                pert=pert,
                input_tpl=input_tpl,
                location=location,
                sop_db=sop_db,
                kin_db=kin_db,
                sim_db=sim_db,
                f_el=f_el,
                klog=klog)
        elif settings['ga_type'].casefold() == 'exp':
            optimizer = Exponential(
                settings=settings,
                sf=sf,
                pert=pert,
                input_tpl=input_tpl,
                location=location,
                sop_db=sop_db,
                kin_db=kin_db,
                sim_db=sim_db,
                f_el=f_el,
                klog=klog)
        else:
            raise TypeError('Unknown genetic algorythm requested')
    elif settings['optimizer'] == Optimizers.NM:
        optimizer = NelderMead(
                settings=settings,
                sf=sf,
                pert=pert,
                input_tpl=input_tpl,
                location=location,
                sop_db=sop_db,
                kin_db=kin_db,
                sim_db=sim_db,
                f_el=f_el,
                klog=klog)
    else:
        raise TypeError('Unknown optimizer requested')
    klog.info(f"{'OPTIMIZER:':<65}{optimizer.name}")
    optimizer.run()
