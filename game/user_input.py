import csv
import os
import sys
import json
from game.default_settings import default_settings, mandatory_keys
import numpy as np
from numpy import float64
from numpy.typing import NDArray


def check_input(input_file: str) -> dict:
    """Method that checks if the argument given by the user is valid.
    All checks on user inputs should be performed here.
    Avoid using 'raise' a maximum during the code.
    If a user input error can be detected here, check it here.

    Args:
        input_file (str): path to input file
    """
    cancel_run = False

    # File exist?
    if not os.path.isfile(path=input_file):
        print(f'The input_file {input_file} was not found.')
        sys.exit(-1)

    # Is JSON file?
    if input_file[-5:].casefold() != '.json':
        print("The argument given to GAME should be a json file.")
        sys.exit(-1)

    with open(input_file, mode='r') as f:
        json_file: dict = json.load(fp=f)

    # Has mandatory keys?
    for key, value in mandatory_keys.items():
        if key not in json_file:
            print(f"{key} is a mandatory keyword.")
            cancel_run = True
        elif not isinstance(json_file[key], type(value)):
            print(f"{key} has incorrect type. Type should be {type(value)}")
            cancel_run = True

    # Check if initial concentrations are correct:
    # May fail if mandatory key is missing
    if 'initial_X' in json_file:
        sum = 0.0
        base_key = 'n2'
        base_given = False
        for key, value in json_file['initial_X'].items():
            if not isinstance(key, str):
                print('initial_X keys should be ct species names.')
                cancel_run = True
                break
            if isinstance(value, str) and value.casefold() == 'base' and\
               not base_given:
                base_key: str = key
                base_given = True
            elif isinstance(value, float):
                sum += value
                if sum > 1.0:
                    print(
                        f"The sum of initial X exeeds 1 from specie {key}.")
                    cancel_run = True
            else:
                if base_given:
                    print('More than 1 base given in initial_X.')
                else:
                    print('Values of initial_X should be floats.')
                cancel_run = True
                break
        json_file['initial_X'][base_key] = 1 - sum

    # Has unknown keys?
    for key in json_file:
        if key not in default_settings and\
           key not in mandatory_keys:
            print(f"{key} is an unknown keyword and will be ignored.")

    # Set default values for all keys
    for key, value in default_settings.items():
        if key not in json_file:
            json_file[key] = value
        elif not isinstance(json_file[key], type(value)):
            print(f"{key} has incorrect type. It should be {type(value)}")
            cancel_run = True

    # READ CSVs
    clean_profiles = []
    species = []
    exp_headers = []
    n_exp: int = len(json_file['rc_pres'])*len(json_file['rc_temp'])
    if len(json_file['exp_profiles']) != n_exp:
        print("There should be one csv profile file for each TP condition.")
        cancel_run = True
    else:
        for p in range(len(json_file['rc_pres'])):
            for t in range(len(json_file['rc_temp'])):
                idx: int = p*len(json_file['rc_temp']) + t
                file: str = json_file['exp_profiles'][idx]
                clean_profiles.append({})
                exp_headers.append([])
                if not os.path.isfile(file):
                    print(f'Could not find file {file}.')
                    cancel_run = True
                else:
                    with open(file, 'r') as f:
                        csv_DictReader = csv.DictReader(f)
                        ln = 0
                        for line in csv_DictReader:
                            if 'time' not in line:
                                print(
                                    "A column should be the 'time'",
                                    f"column in file {file}.")
                                cancel_run = True
                            else:
                                for header in line:
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
                                    except TypeError:
                                        print('Incorrect value detected line',
                                              f'{ln} in file {file}',
                                              'column {header}')
                                        cancel_run = True
                            ln += 1
                # check the created profiles:
                nstep: int = len(clean_profiles[-1]['time'])
                for header, profile in clean_profiles[-1].items():
                    if len(profile) != nstep:
                        print(
                            f'Not enough values in profile {header}',
                            f'in file {file}')
    # Transform the profiles in numpy structured arrays
    for idx, prof in enumerate(clean_profiles):
        clean_profiles[idx] = np.empty(
            shape=(len(prof), len(prof['time'])),
            dtype=float64)
        for cidx, col in enumerate(prof):
            clean_profiles[idx][cidx] = prof[col]
    json_file['exp_profiles'] = clean_profiles

    # Modify score_sp to contain appropriate species
    if json_file['score_sp'] == []:
        json_file['score_sp'] = species
    else:
        for sp in json_file['score_sp']:
            if sp not in species:
                print(f'Specie {key} cannot be scored',
                      'because it is not in the',
                      'experimental profiles.')
                cancel_run = True

    # Setting the weight for each experiment
    # default
    if len(json_file['w_exp']) == 0:
        json_file['w_exp'] = [1.0 for i in range(n_exp)]
    # Error in input
    elif len(json_file['w_exp']) != n_exp:
        print("The number of weights in w_exp should be {n_exp}")
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
            print(f'Specie {key} cannot have a weight',
                  'because it is not in the',
                  'experimental profiles.')
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
        print('Unknown scoring function. Check the spelling?')
        cancel_run = True
    implemented_restart: list[str] = ['default', 'scratch']
    if json_file['restart'].casefold() not in implemented_restart:
        print('Unknown restart mode. Check the spelling?')
        cancel_run = True

    if cancel_run:
        sys.exit(-1)

    return json_file
