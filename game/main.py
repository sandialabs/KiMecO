import sys

from game.readers.mess_input import MessInputReader
from game.rate_constants import RateCon
from game.user_input import check_input
from game.parameters import SOP


def main() -> None:
    try:
        input_file: str = sys.argv[1]
    except IndexError:
        print('To use GAME, supply one argument being the input file!')
        sys.exit(-1)

    settings: dict = check_input(input_file=input_file)

    mr = MessInputReader(settings=settings)
    init_SOP: SOP
    input_tpl: list[str]
    (init_SOP, input_tpl) = mr.read()

    init_KinCon = RateCon(sop=init_SOP,
                          settings=settings,
                          software_tpl=input_tpl,
                          id='init')

    init_KinCon.calculate()
    init_KinCon.recover_rslts()
