import os
from typing import Literal, Sequence
from sqlalchemy import create_engine, Engine, Table, Column, Integer, String
from sqlalchemy import MetaData, Float, text, TextClause, update, Update
from sqlalchemy_utils import database_exists, create_database
import pandas as pd
from pandas import DataFrame
from typing import Any


class Game_db:
    def __init__(self,
                 name: str,
                 path: str = '') -> None:
        """Class managing the information storage of GAME database.
        """
        self.name: str = name
        if path == '':
            self.path = os.getcwd()
        else:
            self.path: str = path
        self.eng: Engine = create_engine(f'sqlite:///{self.path}/{name}.db',
                                         pool_size=1,
                                         max_overflow=2000)
        if not database_exists(self.eng.url):
            create_database(self.eng.url)
        self.metadata = MetaData()
        self.tables: dict[str, Table] = {}
        self.sql_alch_type: dict = {
            # Python types: SQLAlchemy types
            str: String,
            int: Integer,
            float: Float,
            # bool: Boolean,
            # dict: JSON,
            # list: ARRAY
        }

    def table_exists(self,
                     name: str) -> bool:
        with self.eng.begin() as conn:
            if self.eng.dialect.has_table(conn, name):
                return True
            else:
                return False

    def create_table(self,
                     name: str,
                     columns: list[str],
                     types: list[type]) -> None:
        self.tables[name] = Table(
            name,
            self.metadata,
            Column('id', Integer, primary_key=True),
            *[Column(columns[i],
                     self.sql_alch_type[types[i]])
              for i in range(len(columns))]
            )
        self.metadata.create_all(self.eng)

    def entry_exist(self,
                    table: str,
                    id: int) -> bool:
        """Check if the db already contains
        the unique id in the given table.

        Args:
            table (str): table name in the db
            id (int): id of the row

        Returns:
            bool: is in db or not
        """
        query: TextClause = text(f"SELECT id FROM {table} WHERE id={id+1}")
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        if len(db_rslt) == 0:
            return False
        else:
            return True

    def update_entry(self,
                     table: str,
                     id: int,
                     values: dict[str, Any]) -> None:
        query: Update = (
            update(table=self.tables[table]).
            where(self.tables[table].c.id == id).
            values(**values)
            )
        with self.eng.begin() as connection:
            connection.execute(query)

    def save_data(self,
                  table: str,
                  df: pd.DataFrame,
                  mode: Literal['fail', 'replace', 'append'] = 'replace'
                  ) -> None:
        """Create a new table for the sim results.

        Args:
            table (str): table of the corresponding generation (GX)
            df (pd.DataFrame):
                dataframe to save.
            mode (Literal['fail', 'replace', 'append']):
                Mode of saving the DF in the DB if a row already exists.
        """
        with self.eng.begin() as connection:
            df.to_sql(name=table,
                      con=connection,
                      if_exists=mode,
                      index=False,
                      method="multi"
                      )

    def get_sop_row(self,
                    table,
                    id) -> list[Any]:
        """Return the values in the row uniquely identified by id
        in the table.

        Args:
            table (_type_): table name in db
            id (_type_): row id

        Returns:
            list[Any]: List of values in the row
        """
        query: TextClause = text(f"SELECT * FROM {table} WHERE id={id+1}")
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt[0][1:])

    def get_sim_data(self,
                     sim_id: int,
                     gen: int) -> DataFrame:

        with self.eng.begin() as connection:
            df: DataFrame = pd.read_sql(
                sql="""SELECT *
                FROM sim
                WHERE sim_id={} AND gen={}""".format(
                    sim_id,
                    gen
                ),
                con=connection)
        return df
