from game.database.game_db import Game_db
from game.parameters import SOP
from sqlalchemy import select, Row
from typing import Sequence
from typing import Any


class SIM_DB(Game_db):
    def __init__(self,
                 name: str,
                 path: str = '',
                 sop: SOP | None = None) -> None:
        super().__init__(name=name,
                         path=path)
        self._select = {}

        if isinstance(sop, SOP):
            self.species: list[str] = sop.species

            self.columns: list[str] = ['P', 'T', 'sim_id', 'time']
            self.columns.extend(self.species)
        else:
            # Only work if the SIM_DB is already created.
            self.columns: list[str] = [
                c[1] for c in self.get_col_names('G0')[1:]]
            self.species = self.columns[4:]
        self.types = [int, float, float, int, float]
        self.types.extend([float for i in range(len(self.species))])
        tbls_in_db = self.get_table_names()

        for tbl in tbls_in_db:
            self.create_table(name=tbl[0])

    def create_table(self,
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
                            table,
                            sim_id) -> list[list[float]]:
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

    def batch_select(self) -> dict[int, list[list[Any]]]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            dict[int, list[list[Any]]]: A dictionary with sim_id as keys and lists of their corresponding data as values.
        """
        results = {}
        for table in self._select:
            sim_ids = self._select[table]
            query = select(
                self.tables[table].c.sim_id,
                self.tables[table].c.time,
                *[self.tables[table].c[sp]
                  for sp in self.columns[4:]]
                    ).where(
                        self.tables[table].c.sim_id.in_(sim_ids))
            with self.eng.begin() as connection:
                db_rslt: Sequence[Row[Any]] = connection.execute(query).fetchall()
            for row in db_rslt:
                sim_id = int(row.sim_id)
                if sim_id not in results:
                    results[sim_id] = []
                results[sim_id].append(row)

        self._select = {}  # Clear the _select dictionary after processing
        return results
