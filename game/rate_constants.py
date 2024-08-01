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
                 id='') -> None:

        self.SOP: SOP = sop
        self.software: str = settings['rc_software'].casefold()
        self.software_tpl: list[str] = software_tpl
        self.id: str = id
        self.set: dict[str, Any] = settings

    @property
    def output_name(self) -> str:
        """Find name of output file depending on the software

        Returns:
            str: name of output file
        """
        if self.software == 'mess':
            return f"{self.id}.out"
        else:
            return f"{self.id}.out"

    def calculate(self,
                  q_sys: QueueingSystem) -> None:
        """Generate and submit a Kinetic
        Constants calculation
        """
        if not os.path.isfile(self.output_name) or\
           os.path.getsize(self.output_name) == 0:
            self.create_input()
            self.submit(q_sys)

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

    def submit(self,
               q_sys: QueueingSystem) -> None:
        """Submit kinetic constant calculation on Slurm queing system
        """
        filename: str = f'{self.id}.slurm'
        if self.software == 'mess':
            submitscript = tpl.format(nprocs=8,
                                      filename=self.id,
                                      sub_queue='week-long-cpu',
                                      mem_mb=10000)
            with open(filename, 'w') as f:
                f.write(submitscript)
            command = ['sbatch', filename]
            process = subprocess.Popen(command,
                                       shell=False,
                                       stdout=subprocess.PIPE,
                                       stdin=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            out, err = process.communicate()
            outstr: str = out.decode()
            self.job_id: int = int(outstr.split()[-1])

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

    @property
    def job_finished(self) -> bool:
        if os.path.isfile(f"{self.id}.out"):
            return True

        command = ['squeue', '-u', f'{getpass.getuser()}']
        process = subprocess.Popen(args=command,
                                   shell=False,
                                   stdout=subprocess.PIPE,
                                   stdin=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        out, err = process.communicate()
        out = out.decode()

        for line in out:
            if self.job_id in line:
                return False
        if os.path.isfile(self.output_name):
            return True
        else:
            return False
