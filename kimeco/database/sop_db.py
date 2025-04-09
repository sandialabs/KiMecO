from kimeco.database.game_db import Game_db
from kimeco.parameters import SOP
from sqlalchemy import select, Row
from typing import Any, Sequence


class SOP_DB(Game_db):
    def __init__(self,
                 sop: SOP,
                 name: str,
                 path: str = '',
                 tbl_name: str = 'G0000') -> None:
        super().__init__(name=name,
                         path=path)
        self._select = {}

        self.columns: list[str] = \
            [key for key in sop.parameters_names.keys()]
        self.types: list[type] = \
            [type(val) for val in sop.parameters_names.values()]
        tbls_in_db = self.get_table_names()

        for tbl in tbls_in_db:
            self.create_table(name=tbl[0])

    def create_table(self,
                     name: str) -> None:
        return super().create_table(name=name,
                                    columns=self.columns,
                                    types=self.types)

    def get_sop_row(self,
                    table: str,
                    id: int) -> list[float]:
        """Return the values in the row uniquely identified by the id
        in the table.

        Args:
            table (_type_): table name in db
            id (_type_): row id

        Returns:
            list[Any]: List of values in the row
        """
        query = select(
            self.tables[table]).where(self.tables[table].c.id == id)
        with self.eng.begin() as connection:
            rslt: list[float] = list(connection.execute(query).fetchall()[0])
        return rslt

    def prepare_batch_select(self,
                             table: str,
                             row_id: int) -> None:
        """Prepare a batch select request to store in the _select dictionary.

        Args:
            table (str): name of the table
            row_id (int): SOP id
        """
        if table not in self._select:
            self._select[table] = []
        self._select[table].append(row_id)

    def batch_select(self) -> dict[int, list[list[Any]]]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            dict[int, list[list[Any]]]:
            A dictionary with sim_id as keys and lists
            of their corresponding data as values.
        """
        all_db_rslt = []
        for table in self._select:
            row_ids = self._select[table]
            query = select(
                self.tables[table]
                    ).where(
                        self.tables[table].c.id.in_(row_ids))
            with self.eng.begin() as connection:
                db_rslt: Sequence[Row[Any]] = connection.execute(query).fetchall()
            all_db_rslt.extend(db_rslt)
        self._select = {}  # Clear the _select dictionary after processing
        return all_db_rslt
