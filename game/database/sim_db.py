from game.database.game_db import Game_db
from game.parameters import SOP
from game.well import Well
from game.barrier import Barrier
from sqlalchemy import select
from typing import Any, Sequence


class SIM_DB(Game_db):
    def __init__(self,
                 sop: SOP,
                 name: str,
                 path: str = '',) -> None:
        super().__init__(name=name,
                         path=path)
        
        self.species: list[str] = [
            sop.items[specie].ct_name
            for specie, obj in sop.items.items()
            if isinstance(obj, Well) and not isinstance(obj, Barrier)]
        
        self.columns: list[str] = ['P', 'T', 'sim_id', 'time']
        self.columns.extend(self.species)
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
        # command: str = "SELECT P, T, sim_id, time, "
        # for sp in species:
        #     command += f"{sp}, "
        # command = command[:-2] + \
        #     f" FROM {table} WHERE P={pres} AND T={temp}"
        # query: TextClause = text(
        #     command)
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)
