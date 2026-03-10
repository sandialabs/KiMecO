import sys
from kimeco._kimeco import KiMecO


def _print_help() -> None:
    print(
        """
KiMecO (kmo)
Run a full kinetic mechanism optimization workflow.

This command reads a JSON input file, initializes databases/work directories,
configures scoring and optimization, then executes the selected optimizer.

Usage:
  kmo INPUT_JSON

Arguments:
  INPUT_JSON    Path to the KiMecO JSON configuration file.

Options:
  -h, --help    Show this help message and exit.
""".strip()
    )


def main() -> None:

    if len(sys.argv) == 2 and sys.argv[1] in {'-h', '--help'}:
        _print_help()
        sys.exit(0)

    if len(sys.argv) != 2:
        _print_help()
        sys.exit(1)

    try:
        kmo = KiMecO(input_file=sys.argv[1])
    except IndexError as e:
        print(e)
        print('To use KiMecO, supply the input file as argument.')
        sys.exit(-1)

    kmo.check_kinmech()
    kmo.initialize_workdir()
    kmo.copy_necessary_files()
    kmo.initialize_databases()
    kmo.set_scoring_function()
    kmo.set_perturbator()
    kmo.set_important_parameters()
    kmo.set_optimizer()
    kmo.optimizer.run()
    kmo.finalize()
