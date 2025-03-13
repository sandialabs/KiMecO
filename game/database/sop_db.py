from game.database.game_db import Game_db
from game.parameters import SOP
from sqlalchemy import select


class SOP_DB(Game_db):
    def __init__(self,
                 sop: SOP,
                 name: str,
                 path: str = '',
                 tbl_name: str = 'G0000') -> None:
        super().__init__(name=name,
                         path=path)

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
