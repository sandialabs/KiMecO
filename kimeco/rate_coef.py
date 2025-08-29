from genericpath import isfile
import time
from typing import Any

from pandas import RangeIndex
from kimeco.database.kin_db import KIN_DB
from kimeco.parameters import SOP
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.writers.mess import MessWriter
from kimeco.readers.mess_output import MessOutputReader
import os
import numpy as np
from numpy.typing import NDArray
from logging import Logger


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
                 q_sys: QueueingSystem,
                 db: KIN_DB,
                 klog: Logger
                 ) -> None:
        self.klog: Logger = klog
        self.status: JobStatus = JobStatus.NOT_IN_QUEUE
        self.id: int = id
        self.sop: SOP = sop
        self.software: str = settings['rc_software'].casefold()
        self.software_tpl: list[str] = software_tpl
        self.name: str = name
        self.set: dict[str, Any] = settings
        self.loc: str = loc + f'/{(self.id)//50:02d}'
        self.q_sys: QueueingSystem = q_sys
        self.db: KIN_DB = db
        # Modulable if something else than mess is used.
        if self.software == 'mess':
            self.output_name: str = f"{self.loc}/{self.name}.out"
        else:
            self.output_name = f"{self.loc}/{self.name}.out"

    def set_status(self,
                   table: str) -> None:
        status: JobStatus = self.q_sys.status(id=self.id,
                                              jtype='kin')
        if (status == JobStatus.NOT_IN_QUEUE
           and os.path.isfile(self.output_name)
           and self.is_in_db(table=table)):
            self.status = JobStatus.FINISHED
        else:
            self.status = status

    def is_in_db(self,
                 table: str) -> bool:
        """Check if the rate coefficients of this object are in the db.


        Args:
            table (str): Generation's name

        Returns:
            bool: Wether data in db correspond to this object.
        """
        db_row_ids: list[int] = self.db.get_ids_from_kin_id(table=table,
                                                            kin_id=self.id)
        cols = self.db.get_col_names(table=table)
        row_ids: list[int] = [i for i in RangeIndex(
            start=(self.id *
                   len(self.set['rc_pres']) *
                   len(self.set['rc_temp']) *
                   len(cols[5:])),
            stop=(self.id *
                  len(self.set['rc_pres']) *
                  len(self.set['rc_temp']) *
                  len(cols[5:]) +
                  len(self.set['rc_pres']) *
                  len(self.set['rc_temp']) *
                  len(cols[5:])),
            step=1)]
        return db_row_ids == row_ids

    def q_up(self) -> None:
        """Generate and submit a Kinetic
        Constants calculation
        """
        if self.status in {
           JobStatus.NOT_IN_QUEUE,
           JobStatus.FAILED}:
            cpu: int = self.set['cpu_kin']
            mem: int = self.set['mem_kin']
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
            mw = MessWriter(SOP=self.sop, tpl=self.software_tpl)
            mw.write(loc=self.loc,
                     filename=f'{self.name}.inp')
        else:
            raise NotImplementedError(
                "K constants calculation with this software not available yet")

    def recover_rslts(self
                      ) -> list[tuple[Any]]:
        """Wait for the results of the Kinetic constants calculations
        """
        rows = []
        i = 0
        while not isfile(self.output_name):
            if i == 10:
                self.klog.info(f'{self.output_name} not found after 20s.')
                return rows
            time.sleep(2)
            i += 1
        else:
            while not os.stat(self.output_name).st_size > 0:
                time.sleep(2)
        
        if self.software == 'mess':
            mor = MessOutputReader(filename=self.output_name,
                                   settings=self.set,
                                   sop=self.sop,
                                   klog=self.klog)
            mor.read()
        self.rc: np.ndarray = mor.rc
        self.rc[self.rc < 0 ] = 0.0
        # self.hp_rc: np.ndarray = mor.hp_rc  # Not used for now
        self.tbl_map: dict[str, int] = mor.tbl_map
        names: NDArray[Any] = np.full(shape=(len(self.tbl_map)),
                                      fill_value='',
                                      dtype='<U5')
        self.q_sys.pickUp(id=self.id,
                          jtype='kin')
        if (self.q_sys.status(id=self.id, jtype='kin')
           == JobStatus.FAILED):
            self.klog.info(f'Resetting KIN job {self.id}')
            self.status = JobStatus.FAILED

        # Happens with convergence issues in Mess calculation
        if self.tbl_map == {}:
            return rows

        for k, v in self.tbl_map.items():
            names[v] = k

        row_id = int(
            self.id *
            len(self.set['rc_pres']) *
            len(self.set['rc_temp']) *
            len(names))
        for pidx, p in enumerate(self.set['rc_pres']):
            for tidx, t in enumerate(self.set['rc_temp']):
                for From, specie in enumerate(names):
                    rows.append(
                        (row_id,
                         p,
                         t,
                         self.id,
                         specie,
                         *[self.rc[pidx, tidx, From, To]
                           for To in range(len(names))])
                    )
                    row_id += 1
        return rows
