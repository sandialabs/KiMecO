import os
import sys
import json
from game.default_settings import default_settings, mandatory_keys


def check_input(input_file: str) -> dict:
    """Method that checks if the argument given by the user is valid.

    Args:
        input_file (str): path to input file
    """

    # File exist?
    if not os.path.isfile(path=input_file):
        print(f'The input_file {input_file} was not found.')
        sys.exit(__status=-1)

    # Is JSON file?
    if input_file[-5:].casefold() != '.json':
        print("The argument given to GAME should be a json file.")
        sys.exit(__status=-1)

    with open(input_file, mode='r') as f:
        json_file: dict = json.load(fp=f)

    # Has mandatory keys?
    for key in mandatory_keys:
        if key not in json_file:
            print(f"{key} is a mandatory keyword.")
            sys.exit(__status=-1)

    # Has unknown keys?
    for key in json_file:
        if key not in default_settings and\
           key not in mandatory_keys:
            print(f"{key} is an unknown keyword and will be ignored.")

    # Set default values for all keys
    for key, value in default_settings.items():
        if key not in json_file:
            json_file[key] = value

    return json_file
