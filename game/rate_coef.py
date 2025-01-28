from typing import Any

from pandas import Index, MultiIndex, DataFrame, RangeIndex
from game.database.game_db import Game_db
from game.parameters import SOP
from game.q_sys import QueueingSystem
from game.writers.mess import MessWriter
from game.readers.mess_output import MessOutputReader
import os
import numpy as np
from numpy.typing import NDArray


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
                 db: Game_db
                 ) -> None:

        self.status: str
        self.id: int = id
        self.sop: SOP = sop
        self.software: str = settings['rc_software'].casefold()
        self.software_tpl: list[str] = software_tpl
        self.name: str = name
        self.set: dict[str, Any] = settings
        self.loc: str = loc
        self.q_sys: QueueingSystem = q_sys
        self.db: Game_db = db
        # Modulable if something else than mess is used.
        if self.software == 'mess':
            self.output_name: str = f"{self.loc}/{self.name}.out"
        else:
            self.output_name = f"{self.loc}/{self.name}.out"

    def set_status(self,
                   table: str) -> None:
        status: str = self.q_sys.status(id=self.id,
                                        jtype='kin')
        if status == 'notInQueue' and\
           os.path.isfile(self.output_name) and\
           self.is_in_db(table=table):
            self.status = 'finished'
        else:
            self.status = status

    def is_in_db(self,
                 table: str) -> bool:
        """Check if the rate coefficients of this object are in the db.


        Args:
            table (int): Generation id

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
        if db_row_ids == row_ids:
            return True
        else:
            return False

    def q_up(self) -> None:
        """Generate and submit a Kinetic
        Constants calculation
        """
        if not os.path.isfile(self.output_name) and\
           self.status == 'notInQueue' or\
           self.status == 'reset':
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
            mw.write(filename=f'{self.name}.inp')
        else:
            raise NotImplementedError(
                "K constants calculation with this software not available yet")

    def recover_rslts(self) -> DataFrame:
        """Wait for the results of the Kinetic constants calculations
        """
        if self.software == 'mess':
            mor = MessOutputReader(filename=self.output_name,
                                   settings=self.set,
                                   sop=self.sop)
            mor.read()
        self.rc: np.ndarray = mor.rc
        self.rc[self.rc < 1.e-14] = 0.0
        # self.hp_rc: np.ndarray = mor.hp_rc  # Not used for now
        self.tbl_map: dict[str, int] = mor.tbl_map
        names: NDArray[Any] = np.full(shape=(len(self.tbl_map)),
                                      fill_value='',
                                      dtype='<U5')
        self.q_sys.pickUp(id=self.id,
                          jtype='kin')
        if self.q_sys.status(id=self.id,
                             jtype='kin') == 'reset':
            print(f'Resetting KIN job {self.id}')
            self.status = 'reset'
            
        for k, v in self.tbl_map.items():
            names[v] = k

        # Happens with convergence issues in Mess calculation
        if self.tbl_map == {}:
            data = []
            df = DataFrame(data)
            return df

        row_ids: list[int] = [i for i in RangeIndex(
            start=(self.id *
                   len(self.set['rc_pres']) *
                   len(self.set['rc_temp']) *
                   len(names)),
            stop=(self.id *
                  len(self.set['rc_pres']) *
                  len(self.set['rc_temp']) *
                  len(names) +
                  len(self.set['rc_pres']) *
                  len(self.set['rc_temp']) *
                  len(names)),
            step=1)]

        indexes: MultiIndex = MultiIndex.from_product([
            self.set['rc_pres'],
            self.set['rc_temp'],
            [self.name],
            names,],
            names=['P', 'T', 'kin_id', 'specie'])
        db_data = np.reshape(
            a=self.rc,
            newshape=(
                len(self.set['rc_pres']) *
                len(self.set['rc_temp']) *
                len(names),
                len(names))
                   )
        df = DataFrame(data=db_data,
                       index=indexes,
                       columns=names)
        df.reset_index(inplace=True)
        df.index = Index(row_ids)
        df.index.name = 'id'
        
        return df
