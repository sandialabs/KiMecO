import sys

from game.readers.mess import MessReader
from game.rate_constants import RateCon
from game.user_input import check_input


def main() -> None:
    try:
        input_file: str = sys.argv[1]
    except IndexError:
        print('To use GAME, supply one argument being the input file!')
        sys.exit(__status=-1)

    settings: dict = check_input(input_file=input_file)

    mr = MessReader(settings=settings)
    [init_SOP, input_tpl] = mr.read()

    init_KinCon = RateCon(sop=init_SOP,
                          software='mess',
                          software_tpl=input_tpl,
                          id='init')

    init_KinCon.calculate()
    init_KinCon.recover_rslts()
