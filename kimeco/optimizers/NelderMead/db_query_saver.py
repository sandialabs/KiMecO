import numpy as np
import threading

from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB


class DBQuerySaver:
    def __init__(self,
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 settings: dict) -> None:
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.settings = settings
        self.ids_in_sop_db: dict[int, set[int]] = {}
        self.ids_in_kin_db: dict[int, set[int]] = {}
        self.ids_in_sim_db: dict[int, set[int]] = {}
        self._locks: dict[int, threading.Lock] = {}  # Lock per el_id

    def _get_lock(self,
                  gen_id: int) -> threading.Lock:
        """Get or create a lock for the given gen_id."""
        if gen_id not in self._locks:
            self._locks[gen_id] = threading.Lock()
        return self._locks[gen_id]

    def is_vertice_finished(self,
                            el_id: int,
                            gen_id: int,
                            prefix: str) -> bool:
        """Check if gen is in memory.
        if not query ids of gen from db.

        Args:
            el_id (int): id of element
            gen_id (int): id of generation

        Returns:
            bool: is in db
        """
        lock = self._get_lock(gen_id)

        with lock:
            # If this gen hasn't been queried yet, add it to memory
            if not (gen_id in self.ids_in_sop_db and
                    gen_id in self.ids_in_kin_db and
                    gen_id in self.ids_in_sim_db):
                table_name: str = f"{prefix}{gen_id:04d}"
                if self.sop_db.table_exists(table_name) and\
                   self.kin_db.table_exists(table_name) and\
                   self.sim_db.table_exists(table_name):
                    self.ids_in_sop_db[gen_id] = set(self.sop_db.get_column(
                        table=table_name,
                        column_name='id'))
                    self.ids_in_kin_db[gen_id] = set(self.kin_db.get_column(
                        table=table_name,
                        column_name='kin_id'))
                    tmp = np.array(self.sim_db.get_column(
                        table=table_name,
                        column_name='sim_id'))//len(self.settings['exp_profiles'])
                    self.ids_in_sim_db[gen_id] = set(tmp.tolist())
                # if the gen is not in db, not finished
                else:
                    return False

        if (el_id in self.ids_in_sop_db[gen_id] and
            el_id in self.ids_in_kin_db[gen_id] and
            el_id in self.ids_in_sim_db[gen_id]):
            return True
        else:
            return False
