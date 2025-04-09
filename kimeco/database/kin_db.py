from kimeco.database.kimeco_db import Kimeco_db
from kimeco.parameters import SOP
from sqlalchemy import select
from typing import Any, Sequence


class KIN_DB(Kimeco_db):
    def __init__(self,
                 sop: SOP,
                 name: str,
                 path: str = '',) -> None:
        super().__init__(name=name,
                         path=path)

        self.columns: list[str] = ['P', 'T', 'kin_id', 'specie']
        self.columns.extend(sop.wells_names)
        self.columns.extend(sop.bimols_names)
        self.types: list = [float, float, str, str]
        self.types.extend([float for i in range(
            len(sop.wells_names) +
            len(sop.bimols_names))])

        tbls_in_db = self.get_table_names()

        for tbl in tbls_in_db:
            self.create_table(name=tbl[0])

    def create_table(self,
                     name: str) -> None:
        return super().create_table(name=name,
                                    columns=self.columns,
                                    types=self.types)

    def get_kin_rc(self,
                   table: str,
                   From: str,
                   To: str,
                   pres: float,
                   temp: float) -> list[Any]:
        """Query the rate coefficients.

        Args:
            table (str): Generation
            From (str): Species name
            To (str): Specie name
            pres (float): Pressure (Torr)
            temp (float): Temperature (K)

        Returns:
            list[Any]: _description_
        """
        query = select(
            self.tables[table].c.kin_id,
            self.tables[table].c[To],
            ).where(
                self.tables[table].c.P == pres,
                self.tables[table].c.T == temp,
                self.tables[table].c.specie == From)
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)

    def get_ids_from_kin_id(self,
                            table: str,
                            kin_id: int):

        query = select(
            self.tables[table].c.id
            ).where(
                self.tables[table].c.kin_id == kin_id)
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)
