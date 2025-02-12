import os
from typing import Literal, Sequence
from sqlalchemy import create_engine, MetaData, Table, Column, Row
from sqlalchemy import Engine, Insert, update, Update, select
from sqlalchemy import Float, Integer, String, text, TextClause
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy_utils import database_exists, create_database
import pandas as pd
from typing import Any


class Game_db:
    def __init__(self,
                 name: str,
                 path: str = '') -> None:
        """Class managing the information storage of GAME database.
        """
        self.name: str = name
        self._tabls = []
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
        self._upsert = {}

    def get_table_names(self):
        query: TextClause = text(
            "SELECT name FROM sqlite_master WHERE type='table'")
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return db_rslt
    

    def set_wal_mode(self):
        query: TextClause = text(f"PRAGMA journal_mode=WAL")
        with self.eng.begin() as connection:
            db_rslt = connection.execute(query)

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
        query: TextClause = text(text=f"SELECT id FROM {table} WHERE id={id+1}")
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

    def upsert_entries(self,
                       table: str,
                       ids: list[int],
                       values: list[dict[str, Any]]) -> None:
        """Multiple upsert statement at once.
        Used to store the concentration profiles.

        Args:
            table (str): Table name
            ids (list[int]): list of row ids to update
            values (dict[str, list[Any]]):
                keys are column names.
                values are list of values to update,
                    given in same order as ids
        """
        for i in range(len(values)):
            values[i]['id'] = ids[i]
        g_insert: Insert = (
            insert(table=self.tables[table]).
            values(values))

        g_upsert: Insert = g_insert.on_conflict_do_update(
                index_elements=[self.tables[table].c.id],
                set_=g_insert.excluded
            )

        with self.eng.begin() as connection:
            connection.execute(g_upsert)

    def manual_upsert_entries(self,
                              table: str,
                              ids: list[int],
                              values: list[dict[str, Any]]) -> None:
        column_names: str = 'id'
        vals: str = ''

        txt0: str = f"INSERT INTO '{table}' ("
        txt1: str = ") VALUES "

        for ridx in range(len(ids)):
            vals += f'({ids[ridx]}'
            for cidx in values[0].keys():
                if ridx == 0:
                    column_names += f",'{cidx}'"
                vals += f",'{values[ridx][cidx]}'"
            vals += '),'
        vals = vals[:-1]
        insert_txt: str = txt0 + column_names + txt1 + vals  # + ';'

        upsert_txt: str = ' ON CONFLICT (id) DO UPDATE SET'
        for c in values[0].keys():
            upsert_txt += f" '{c}' = excluded.'{c}',"
        upsert_txt = upsert_txt[:-1]
        query: TextClause = text(insert_txt + upsert_txt)
        with self.eng.begin() as connection:
            connection.execute(query)

    def prepare_batch_upsert(self,
                             table: str,
                             id: int,
                             values: dict[str, Any]) -> None:
        """Actualize the upsert variable to prepare a batch upsert.
1
        Args:
            table (str): name of table
            id (int): row id
            values (dict[str, Any]): dictionary of param name - value
        """
        if table not in self._upsert:
            self._upsert[table] = {}
        self._upsert[table][id] = values

    def batch_upsert(self) -> None:
        if len(self._upsert) == 0:
            return
        for table in self._upsert:
            ids: list[int] = []
            values: list[dict] = []
            for id in self._upsert[table]:
                ids.append(id)
                values.append(self._upsert[table][id])
            self.upsert_entries(
                table=table,
                ids=ids,
                values=values)
        self._upsert = {}

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

    def get_col_names(self,
                      table):
        """Query the name of the columns of a given table.

        Args:
            table (str): _description_
        """
        query: TextClause = text(f"PRAGMA table_info('{table}')")
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)

    def get_table(self,
                  table: str) -> Sequence:
        """Return the values in the row uniquely identified by id
        in the table.

        Args:
            table (str): table name in db

        Returns:
            list[Any]: List of values in the row
        """
        query: TextClause = text(f"SELECT * FROM {table}")
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return db_rslt

    def get_data(self,
                 table: str,
                 ids: list[int]) -> Sequence[Row[Any]]:
        """Query all rows having the listed ids.

        Args:
            table (str): table name
            ids (list[int]): list of rows ids

        Returns:
            _type_: list of rows data
        """
        query = select(
            self.tables[table]).where(self.tables[table].c.id.in_(ids))
        with self.eng.begin() as connection:
            rslt: Sequence[Row[Any]] = connection.execute(query).fetchall()
        return rslt
