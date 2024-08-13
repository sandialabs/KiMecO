from typing import Any
from game.parameters import SOP
from game.q_sys import QueueingSystem
from game.writers.mess import MessWriter
from game.readers.mess_output import MessOutputReader
import os
import numpy as np


class RateCo:
    """Wrapper around different calculators
    for kinetic constants calculation.
    """
    def __init__(self,
                 sop: SOP,
                 settings: dict,
                 software_tpl: list[str],
                 id: int,
                 name: str,
                 loc: str,
                 q_sys: QueueingSystem
                 ) -> None:

        self.id: int = id
        self.SOP: SOP = sop
        self.software: str = settings['rc_software'].casefold()
        self.software_tpl: list[str] = software_tpl
        self.name: str = name
        self.set: dict[str, Any] = settings
        self.loc: str = loc
        self.q_sys: QueueingSystem = q_sys
        # Modulable if something else than mess is used.
        if self.software == 'mess':
            self.output_name: str = f"{self.loc}/{self.name}.out"
        else:
            self.output_name = f"{self.loc}/{self.name}.out"

    def set_status(self) -> None:
        self.status: str = self.q_sys.status(id=self.id,
                                             jtype='kin')

    def q_up(self) -> None:
        """Generate and submit a Kinetic
        Constants calculation
        """
        self.set_status()
        if not os.path.isfile(self.output_name) and\
           self.status == 'notInQueue':
            cpu = self.set['cpu_kin']
            mem = self.set['mem_kin']
            self.create_input()
            self.q_sys.add_to_q(name=self.name,
                                idx=self.id,
                                location=self.loc,
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
            mw.write(filename=f'{self.name}.inp')
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
        self.q_sys.pickUp(id=self.name)
