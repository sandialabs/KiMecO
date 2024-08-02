from typing import Any
from game.parameters import SOP
from game.queue.q_sys import QueueingSystem
from game.writers.mess import MessWriter
from game.readers.mess_output import MessOutputReader
import subprocess
import os
import getpass
import numpy as np


class RateCo:
    """Wrapper around different calculators
    for kinetic constants calculation.
    """
    def __init__(self,
                 sop: SOP,
                 settings: dict,
                 software_tpl: list[str],
                 id: str,
                 loc: str
                 ) -> None:

        self.SOP: SOP = sop
        self.software: str = settings['rc_software'].casefold()
        self.software_tpl: list[str] = software_tpl
        self.id: str = id
        self.set: dict[str, Any] = settings
        self.loc: str = loc
        if self.software == 'mess':
            self.output_name: str = f"{self.loc}/{self.id}.out"
        else:
            self.output_name = f"{self.loc}/{self.id}.out"

    def calculate(self,
                  q_sys: QueueingSystem,
                  loc: str) -> None:
        """Generate and submit a Kinetic
        Constants calculation
        """
        if not os.path.isfile(self.output_name) or\
           q_sys.status(self.id) != 'finished':
            cpu = 4
            mem = 10000
            self.create_input()
            q_sys.add_to_q(id=self.id,
                           location=loc,
                           jtype='kin',
                           ressources=(cpu, mem)
                           )

    def create_input(self) -> None:
        """Create an input for the selected solftware.

        Raises:
            NotImplementedError: Writter for this software doesn't exist yet
        """
        if self.software == 'mess':
            mw = MessWriter(SOP=self.SOP, tpl=self.software_tpl)
            mw.write(filename=f'{self.id}.inp')
        else:
            raise NotImplementedError(
                "K constants calculation with this software not available yet")

    def recover_rslts(self) -> None:
        """Wait for the results of the Kinetic constants calculations
        """
        if self.software == 'mess':
            mor = MessOutputReader(filename=self.output_name,
                                   settings=self.set,
                                   sop=self.SOP)
            mor.read()
        self.rc: np.ndarray = mor.rc
        self.hp_rc: np.ndarray = mor.hp_rc
        self.tbl_map: dict[str, int] = mor.tbl_map
