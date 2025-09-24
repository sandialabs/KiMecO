import sys
from kimeco._kimeco import KiMecO


def main() -> None:

    # Call the setup function to configure logging
    if len(sys.argv) != 2:
        print("""
    KIMECO needs various parameters to be set in a JSON input file.
    This JSON input file should be supplied as the first and only
    argument.

    Usage:  kmo path/to/JSON/input/file.json
    """)
        sys.exit()
    try:
        kmo = KiMecO(input_file=sys.argv[1])
    except IndexError as e:
        print(e)
        print('To use KIMECO, supply the input file as argument.')
        sys.exit(-1)

    kmo.initialize_workdir()
    kmo.copy_necessary_files()
    kmo.initialize_databases()
    kmo.set_scoring_function()
    kmo.set_perturbator()
    kmo.set_important_parameters()
    kmo.set_optimizer()
    kmo.optimizer.run()
