import csv
import os
import sys
import json
from kimeco.default_settings import default_settings, mandatory_keys
import numpy as np
from numpy import float64
from numpy.typing import NDArray
from scipy.constants import gas_constant
import cantera.with_units as ctu
from logging import Logger
from kimeco.enums import Distrib, Optimizers, Pclass, Ptype
from kimeco.enums import FreqMode


ureg = ctu.cantera_units_registry
Q_ = ureg.Quantity

R = Q_(gas_constant, 'J mol^-1 K^-1')
Vol = Q_(1, 'cm^3')


def check_input(input_file: str,
                klog: Logger) -> dict:
    """Method that checks if the argument given by the user is valid.
    All checks on user inputs should be performed here.
    Avoid using 'raise' a maximum during the code.
    If a user input error can be detected here, check it here.

    Args:
        input_file (str): Path to JSON file
        klog (Logger): Logger

    Returns:
        dict: settings
    """
    cancel_run = False

    # File exist?
    if not os.path.isfile(path=input_file):
        klog.info(f'The input_file {input_file} was not found.')
        sys.exit(-1)

    # Is JSON file?
    if input_file[-5:].casefold() != '.json':
        klog.info("The argument given to KIMECO should be a json file.")
        sys.exit(-1)

    with open(input_file, mode='r') as f:
        json_file: dict = json.load(fp=f)

    # Has mandatory keys?
    for key, value in mandatory_keys.items():
        if key not in json_file:
            if key == 'initial_C':
                if 'initial_X' not in json_file:
                    klog.info(f"{key} or initial_X is a mandatory keyword.")
                    continue
                else:
                    # The initial composition was given as a percentage
                    continue
            klog.info(f"{key} is a mandatory keyword.")
            cancel_run = True
        elif not isinstance(json_file[key], type(value)):
            if isinstance(value, float) and isinstance(json_file[key], int):
                continue
            klog.info(f"{key} has incorrect type. Type should be {type(value)}")
            cancel_run = True

    if 'pres_unit' not in json_file:
        json_file['pres_unit'] = default_settings['pres_unit']
    klog.info(f"Pressure unit in input assumed in {json_file['pres_unit']}")

    # Check if initial concentrations are correct:
    # May fail if mandatory key is missing
    n_exp: int = len(json_file['rc_pres'])*len(json_file['rc_temp'])
    base_key = 'n2'

    if 'initial_X' in json_file:
        if not isinstance(json_file['initial_X'], list)\
           or len(json_file['initial_X']) != n_exp:
            msg: str = 'initial_X: Should be a list of dictionaries.\n'
            msg += 'Each dict should have for key '
            msg += 'the specie name in the ct mechanism.\n'
            msg += 'The value should be the ratio of that specie.'
            klog.info(msg)
            cancel_run = True
        else:
            for exp in json_file['initial_X']:
                base_given = False
                sum = 0.0
                for k, v in exp.items():
                    if not isinstance(k, str):
                        klog.info('initial_X keys should be ct species names.')
                        cancel_run = True
                        break
                    # Set the base
                    if isinstance(v, str) and v.casefold() == 'base':
                        if not base_given:
                            klog.info(f"Base specie: {k}.")
                            base_key: str = k
                            base_given = True
                        else:
                            klog.info(
                                "Two base are given for an experiment.")
                            cancel_run = True
                    # Check total composition
                    elif isinstance(v, float):
                        sum += v
                if sum > 1:
                    klog.info("An initial composition exceeds 100%.")
                    cancel_run = True
                    break
                else:
                    if not base_given:
                        klog.info("No base given, using n2.")
                exp[base_key] = 1 - sum

    # Calculate total number of mol in 1 cm3
    # n = PV/RT
    if 'initial_C' in json_file:
        json_file['initial_X'] = []
        sum = 0.0
        base_key = 'n2'
        base_given = False
        for key, value in json_file['initial_C'].items():
            if not isinstance(key, str):
                klog.info('initial_C keys should be ct species names.')
                cancel_run = True
                break
            if isinstance(value, str) and value.casefold() == 'base':
                if not base_given:
                    base_key: str = key
                    base_given = True
                else:
                    klog.info(
                        f"{key} cannot be the base. It is already {base_key}.")
                    cancel_run = True
            elif isinstance(value, float):
                n = Q_(value, 'molecule')
                exp = 0
                # Setup molar fraction for each experiment for 1cm^3
                for a in json_file['rc_pres']:
                    try:
                        p = Q_(a, json_file['pres_unit']).to('torr')
                    except ValueError as e:
                        cancel_run = True
                        klog.info('pres_unit was not recognised.')
                        klog.info(e)
                    for b in json_file['rc_temp']:
                        t = Q_(b, 'K')
                        if len(json_file['initial_X']) <= exp:
                            json_file['initial_X'].append({})
                        ntot = (p*Vol/(R*t)).to('molecule')
                        json_file['initial_X'][exp][key] = (n/ntot).magnitude
                        exp += 1
                sum += (n/ntot).magnitude
                if sum > 1:
                    klog.info(
                        "The sum of initial C exeeds the total pressure.")
                    cancel_run = True
            else:
                klog.info('Values of initial_C should be floats.')
                cancel_run = True
                break
        for exp in json_file['initial_X']:
            exp[base_key] = 1 - sum

    for idx, exp in enumerate(json_file['initial_X']):
        klog.info(f"Initial composition for experiment {idx}:")
        for k, v in exp.items():
            msg = '\t'
            msg += f'{k}: {v:-.2e}'
            klog.info(msg)

    # Has unknown keys?
    for key in json_file:
        if key not in default_settings and\
           key not in mandatory_keys and\
           key != 'initial_X':
            klog.info(f"{key} is an unknown keyword and will be ignored.")

    # Set default values for all keys
    for key, value in default_settings.items():
        if key not in json_file:
            # Replace value by enum for RNG distributions
            if 'distrib' in key:
                value = Distrib(value)
            # Check the FreqMode
            if key == 'freq_mode':
                value = FreqMode(value)
            elif key == 'optimizer':
                value = Optimizers(value)
            json_file[key] = value
        elif not isinstance(json_file[key], type(value)):
            if isinstance(value, float) and isinstance(json_file[key], int):
                continue
            klog.warning(f"{key} has incorrect type. It should be {type(value)}")
            cancel_run = True
        # Replace value by enum for RNG distributions
        elif 'distrib' in key:  # Key is a distribution specified in JSON
            for ptype in Ptype:
                if ptype.value in key:
                    break
            if any([json_file[key].casefold() == distrib.value
                    for distrib in Distrib]):
                dist = Distrib(json_file[key].casefold())
                if ptype.value in Pclass.ADDITIVE.value:
                    if dist == Distrib.LOGNORMAL or\
                       dist == Distrib.LOGUNIFORM:
                        msg = f"{key} is not allowed for this parameter."
                        klog.warning(msg)
                        cancel_run = True
                json_file[key] = Distrib(json_file[key].casefold())
            else:
                klog.warning(f"{key} has unknown distribution.")
                cancel_run = True
        # Replace value by enum for mode of frequencxy perturbation
        elif key == 'freq_mode':
            if any([json_file[key].casefold() == fm.value
                    for fm in FreqMode]):
                json_file[key] = FreqMode(json_file[key].casefold())
            else:
                klog.warning(f"{key} has unknown frequency perturbation mode.")
                cancel_run = True
        elif key == 'optimizer':
            if any([json_file[key].casefold() == opt.value
                    for opt in Optimizers]):
                json_file[key] = Optimizers(json_file[key].casefold())
            else:
                klog.warning(f"{key} has unknown type.")
                cancel_run = True


    # READ CSVs
    clean_profiles = []
    clean_errors = []
    species = []
    exp_headers = []
    if len(json_file['exp_profiles']) != n_exp:
        klog.info(
            "There should be one csv profile file for each TP condition.")
        cancel_run = True
    else:
        for p in range(len(json_file['rc_pres'])):
            for t in range(len(json_file['rc_temp'])):
                idx: int = p*len(json_file['rc_temp']) + t
                file: str = json_file['exp_profiles'][idx]
                file_err: str = json_file['exp_errors'][idx]
                clean_profiles.append({})
                clean_errors.append({})
                exp_headers.append([])
                if not os.path.isfile(file) or\
                   not os.path.isfile(file_err):
                    klog.info(f'Could not find file {file}.')
                    cancel_run = True
                else:
                    # Read experimental profiles
                    with open(file, mode='r', encoding='utf-8-sig') as f:
                        csv_DictReader = csv.DictReader(f)
                        ln = 0
                        for line in csv_DictReader:
                            if 'time' not in line:
                                msg = "A column should be the 'time'"
                                msg += f" in file {file}."
                                klog.info(msg)
                                cancel_run = True
                            else:
                                for header in line:
                                    # Skip excluded species
                                    if header in json_file['exclude_sp']:
                                        continue
                                    # Consider other species
                                    if header not in species and\
                                       header != 'time':
                                        species.append(header)
                                    if header not in exp_headers[-1] and\
                                       header != 'time':
                                        exp_headers[-1].append(header)
                                    if ln == 0:
                                        clean_profiles[-1][header] = []
                                    try:
                                        clean_profiles[-1][header].append(
                                            float(line[header]))
                                    except TypeError as e:
                                        klog.debug(e)
                                        msg = 'Incorrect value detected' +\
                                              f' line{ln} in file {file}' +\
                                              f' column {header}'
                                        klog.info(msg)
                                        cancel_run = True
                            ln += 1
                    # Read experimental profiles errors
                    with open(file_err, mode='r', encoding='utf-8-sig') as f:
                        csv_DictReader = csv.DictReader(f)
                        ln = 0
                        for line in csv_DictReader:
                            if 'time' not in line:
                                msg = "A column should be the 'time'" +\
                                      f"column in file {file_err}."
                                klog.info(msg)
                                cancel_run = True
                            else:
                                for header in line:
                                    # Skip excluded species
                                    if header in json_file['exclude_sp']:
                                        continue
                                    # Consider other species
                                    if ln == 0:
                                        clean_errors[-1][header] = []
                                    try:
                                        clean_errors[-1][header].append(
                                            float(line[header]))
                                    except TypeError as e:
                                        klog.debug(e)
                                        msg = 'Incorrect value detected' +\
                                              f' line{ln} in file {file}' +\
                                              f' column {header}'
                                        klog.info(msg)
                                        cancel_run = True
                            ln += 1
                # check the created profiles:
                nstep: int = len(clean_profiles[-1]['time'])
                if nstep != len(clean_errors[-1]['time']):
                    msg = 'Error file has a different number of values' +\
                          ' than corresponding profile.'
                    klog.info(msg)
                    cancel_run = True
                for header, profile in clean_profiles[-1].items():
                    if len(profile) != nstep:
                        msg = f'Not enough values in profile {header}' +\
                              f' in file {file}'
                        klog.info(msg)
    # Transform the profiles in numpy structured arrays
    for idx, prof in enumerate(clean_profiles):
        clean_profiles[idx] = np.empty(
            shape=(len(prof), len(prof['time'])),
            dtype=float64)
        for cidx, col in enumerate(prof):
            clean_profiles[idx][cidx] = prof[col]
    json_file['exp_profiles'] = clean_profiles
    # Do the same with error files
    for idx, prof in enumerate(clean_errors):
        clean_errors[idx] = np.empty(
            shape=(len(prof), len(prof['time'])),
            dtype=float64)
        for cidx, col in enumerate(prof):
            clean_errors[idx][cidx] = prof[col]
    json_file['exp_errors'] = clean_errors

    # Modify score_sp to contain appropriate species
    if json_file['score_sp'] == []:
        json_file['score_sp'] = species
    else:
        for sp in json_file['score_sp']:
            if sp not in species:
                msg = f'Specie {key} cannot be scored' +\
                      ' because it is not in the' +\
                      ' experimental profiles.'
                klog.info(msg)
                cancel_run = True

    # Setting the weight for each experiment
    # default
    if len(json_file['w_exp']) == 0:
        json_file['w_exp'] = [1.0/n_exp for i in range(n_exp)]
    # Error in input
    elif len(json_file['w_exp']) != n_exp:
        klog.info(f"The number of weights in w_exp should be {n_exp}")
        cancel_run = True
    else:
        sum = 0.0
        for val in json_file['w_exp']:
            sum += val
        # Normalize the weights
        json_file['w_exp'] = np.array(
            [val*n_exp/sum for val in json_file['w_exp']])

    # Setup species weights for each experiment
    json_file['weights'] = []
    for key in json_file['w_species']:
        if key not in species:
            msg = f'Specie {key} cannot have a weight' +\
                  ' because it is not in the' +\
                  ' experimental profiles.'
            klog.info(msg)
            cancel_run = True
    for idx, exp_h in enumerate(exp_headers):
        sp_w_exp: NDArray[float64] = np.ones(
            shape=len(exp_h),
            dtype=float64)
        i = 0
        for sp_i in exp_h:
            # If a specie should have a score
            if sp_i in json_file['score_sp'] and \
               sp_i not in json_file['exclude_sp']:
                # If the specie has a specific weight
                if sp_i in json_file['w_species']:
                    sp_w_exp[i] = json_file['w_species'][sp_i]
                else:
                    pass

            else:
                sp_w_exp[i] = 0.0
            i += 1
        sp_w_exp *= json_file['w_exp'][idx]
        json_file['weights'].append(sp_w_exp)

    # Specific cases with interdependent non-mandatory settings
    # Checking the scoring function:
    implemented_sf: list[str] = ['weighteddif']
    if json_file['scoring_func'].casefold() not in implemented_sf:
        klog.info('Unknown scoring function. Check the spelling?')
        cancel_run = True
    implemented_restart: list[str] = ['default', 'scratch']
    if json_file['restart'].casefold() not in implemented_restart:
        klog.info('Unknown restart mode. Check the spelling?')
        cancel_run = True

    if cancel_run:
        sys.exit(-1)

    return json_file
