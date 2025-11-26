from kimeco.database.kimeco_db import Kimeco_db
from kimeco.parameters import SOP
from sqlalchemy import select
from typing import Sequence
import numpy as np
from numpy.typing import NDArray
from sqlalchemy.exc import OperationalError
from time import sleep
from logging import Logger
from kimeco.logger_config import setup_logger


class SIM_DB(Kimeco_db):
    def __init__(self,
                 name: str,
                 path: str = '',
                 sop: SOP | None = None,
                 threads: int = 1,
                 tbl_name: str = 'G0000') -> None:
        super().__init__(name=name,
                         path=path,
                         threads=threads)

        if isinstance(sop, SOP):
            self.sv_species: list[str] = sop.sc_species

            self.columns: list[str] = ['P', 'T', 'sim_id', 'time']
            self.columns.extend(self.sv_species)
        else:
            # Only work if the SIM_DB is already created.
            self.columns: list[str] = [
                c[1] for c in self.get_col_names(tbl_name)[1:]]
            self.sv_species = self.columns[4:]
        self.types = [int, float, float, int, float]
        self.types.extend([float for i in range(len(self.sv_species))])
        tbls_in_db = self.get_table_names()

        for tbl in tbls_in_db:
            self.load_table(name=tbl[0])

    def create_new_table(self,
                         name: str) -> None:
        return super().create_table(name=name,
                                    columns=self.columns,
                                    types=self.types)

    def get_TP_sim_profiles(self,
                            table: str,
                            species: list[str],
                            pres: float,
                            temp: float):

        query = select(
            self.tables[table].c.P,
            self.tables[table].c.T,
            self.tables[table].c.sim_id,
            self.tables[table].c.time,
            *[self.tables[table].c[sp]
              for sp in species]
        ).where(
            self.tables[table].c.P == pres,
            self.tables[table].c.T == temp
        )
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)

    def get_profile_from_id(self,
                            table: str,
                            sim_id: int) -> list[list[float]]:
        """Query the db for a simulation profile

        Args:
            table (str): name of the table in the db
            sim_id (int): id of simulation

        Returns:
            list[list[float]]: _description_
        """
        query = select(
            self.tables[table].c.time,
            *[self.tables[table].c[sp]
              for sp in self.columns[4:]]
        ).where(
            self.tables[table].c.sim_id == sim_id
        )
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)

    def prepare_batch_select(self, table: str, sim_id: int) -> None:
        """Prepare a batch select request to store in the _select dictionary.

        Args:
            table (str): name of the table
            sim_id (int): simulation ID to select
        """
        if table not in self._select:
            self._select[table] = []
        self._select[table].append(sim_id)

    def batch_select(self) -> dict[str, dict[int, NDArray]]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            dict[str, dict[int, NDArray]]:
                str: table name.
                int: sim_id within this table.
                NDArray: [rows, [sim_id, time, concentrations]]
        """
        results: dict[str, dict[int, NDArray]] = {}
        for table in self._select:
            sim_ids = self._select[table]
            query = select(
                self.tables[table].c.sim_id,
                self.tables[table].c.time,
                *[self.tables[table].c[sp]
                  for sp in self.sv_species]
                    ).where(
                        self.tables[table].c.sim_id.in_(sim_ids))
            try2connect = 0
            tot_try = 10
            results[table] = {}
            while try2connect < tot_try:
                try2connect += 1
                try:
                    with self.eng.begin() as conn:
                        db_rslt: NDArray = np.array(
                            conn.execute(
                                query).fetchall()
                            )
                    if self.sleep_time >= 10:
                        self.sleep_time -= 1
                    break
                except OperationalError as e:
                    if 'database is locked' in str(e):
                        self.sleep_time += 5
                        sleep(self.sleep_time)
                    else:
                        klog: Logger = setup_logger(name='sim_db.log')
                        klog.warning('An OperationalError occured in the db:')
                        klog.warning(e)
                except Exception as e:
                    klog: Logger = setup_logger(name='sim_db.log')
                    klog.warning('An error occured in the database:')
                    klog.warning(e)
                    raise TypeError(e)
            else:
                klog: Logger = setup_logger(name='sim.log')
                msg: str = \
                    f'DB locked for {self.sleep_time*tot_try/60:.2f} min.'
                klog.warning(msg)
                self.sleep_time += 5
                klog.warning(f'Reconnect extended to {self.sleep_time:2f} s.')
                return results

            if len(db_rslt) != 0:
                collected_sim_ids = set(db_rslt[:, 0])
                for sim_id in collected_sim_ids:
                    results[table][int(sim_id)] = db_rslt[
                        db_rslt[:, 0] == sim_id
                        ]

        self._select = {}  # Clear the _select dictionary after processing
        return results
