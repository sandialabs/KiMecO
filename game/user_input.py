import os
import sys
import json
from game.default_settings import default_settings, mandatory_keys


def check_input(input_file: str) -> dict:
    """Method that checks if the argument given by the user is valid.

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
    try:
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
    except ValueError:
        # Occurs when initial_X was not given.
        print('Missing mandatory key initial_X in json file.')
        cancel_run = True
        pass

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
            print(f"{key} has incorrect type.")
            cancel_run = True

    if cancel_run:
        sys.exit(-1)

    return json_file
