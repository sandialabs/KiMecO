import os
import threading
from time import sleep
from typing import Literal, Sequence
from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    update,
    select,
    Float,
    Integer,
    String,
    delete,
)
from sqlalchemy.engine import Row, Engine
from sqlalchemy.sql import Insert, text
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy_utils import database_exists, create_database
import pandas as pd
from typing import Any
from sqlalchemy.exc import OperationalError
from kimeco.logger_config import KMOLogger
import numpy

# Database separator
dbs = '__'


class Kimeco_db:
    def __init__(self,
                 name: str,
                 path: str = '',
                 threads: int = 1) -> None:
        """Class managing the information storage of KIMECO database.
        """
        self.name: str = name
        self.sleep_time: float = 10
        self._tabls = []
        if path == '':
            self.path = os.getcwd()
        else:
            self.path: str = path
        self.eng: Engine = create_engine(f'sqlite:///{self.path}/{name}.db',
                                         pool_size=threads,
                                         max_overflow=0,
                                         connect_args={'timeout': threads})
        if not database_exists(self.eng.url):
            create_database(self.eng.url)
        self.metadata = MetaData()
        self.tables: dict[str, Table] = {}
        self.sql_alch_type: dict = {
            # Python types: SQLAlchemy types
            str: String,
            int: Integer,
            float: Float,
            numpy.float64: Float,
            # bool: Boolean,
            # dict: JSON,
            # list: ARRAY
        }
        self._upsert: dict = {}
        self._select: dict = {}

        # Thread-safe locks for batch operations
        self._upsert_lock = threading.Lock()
        self._select_lock = threading.Lock()

        # Enable WAL mode and optimizations for thread safety
        with self.eng.begin() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL;"))
            conn.execute(text("PRAGMA synchronous=NORMAL;"))
            conn.execute(text("PRAGMA busy_timeout=30000;"))
            conn.execute(text("PRAGMA cache_size=-64000;"))  # 64MB cache

    def load_metadata(self) -> None:
        self.metadata.reflect(bind=self.eng)

    def defragmentate(self) -> None:
        with self.eng.begin() as conn:
            conn.execute(text('VACUUM'))

    def get_table_names(self):
        query: TextClause = text(
            "SELECT name FROM sqlite_master WHERE type='table'")
        with self.eng.begin() as conn:
            db_rslt: Sequence = conn.execute(query).fetchall()
        return db_rslt

    def table_exists(self,
                     name: str) -> bool:
        with self.eng.begin() as conn:
            if self.eng.dialect.has_table(conn, name):
                return True
            else:
                return False

    def wipe_table(self,
                   table: str) -> None:
        delete_query = delete(self.tables[table])
        with self.eng.begin() as conn:
            conn.execute(delete_query)

    def load_table(self,
                   name: str) -> None:
        # Currently not used: May cause a slowdown for db
        # with many tables
        self.tables[name] = Table(
            name,
            self.metadata,
            autoload_with=self.eng)

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
        query = select(
            self.tables[table]).where(self.tables[table].c.id == id)
        with self.eng.begin() as conn:
            db_rslt: Sequence = conn.execute(query).fetchall()
        if len(db_rslt) == 0:
            return False
        else:
            return True

    def update_entry(self,
                     table: str,
                     id: int,
                     values: dict[str, Any]) -> None:
        query = (
            update(table=self.tables[table]).
            where(self.tables[table].c.id == id).
            values(**values)
            )
        with self.eng.begin() as conn:
            conn.execute(query)

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
        # Number of values in a chunk
        max_var = 30000
        total_entries: int = len(values)
        while total_entries > 0:
            # values[0] is the number of columns
            chunk_size: int = min(max_var // (len(values[0]) + 1),
                                  total_entries)
            # Create chunks of ids and values
            val_chunk: list[dict[str, Any]] = values[:chunk_size]
            id_chunk: list[int] = ids[:chunk_size]
            for i in range(len(val_chunk)):
                val_chunk[i]['id'] = id_chunk[i]
            g_insert: Insert = (
                insert(table=self.tables[table]).
                values(val_chunk))

            g_upsert: Insert = g_insert.on_conflict_do_update(
                    index_elements=[self.tables[table].c.id],
                    set_=g_insert.excluded
                )
            try2connect = 0
            tot_try = 10
            while try2connect < tot_try:
                try2connect += 1
                try:
                    with self.eng.begin() as conn:
                        conn.execute(g_upsert)
                    if self.sleep_time >= 10:
                        self.sleep_time -= 1
                    break
                except OperationalError as e:
                    if 'database is locked' in str(e):
                        self.sleep_time += 5
                        sleep(self.sleep_time)
                    else:
                        klog: KMOLogger = KMOLogger(filename='db.log')
                        klog.warning('An OperationalError occured in the db:')
                        klog.warning(str(e))
                except Exception as e:
                    klog: KMOLogger = KMOLogger(filename='db.log')
                    klog.warning('An error occured in the database:')
                    klog.warning(str(e))
            else:
                klog: KMOLogger = KMOLogger(filename='db.log')
                msg: str = \
                    f'DB locked for {self.sleep_time*tot_try/60:.2f} min.'
                klog.warning(msg)
                self.sleep_time += 5
                klog.warning(f'Reconnect extended to {self.sleep_time:2f} s.')
            # Update the lists to process the remaining entries
            values = values[chunk_size:]
            ids = ids[chunk_size:]
            total_entries -= chunk_size

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
        with self.eng.begin() as conn:
            conn.execute(query)

    def prepare_batch_upsert(self,
                             table: str,
                             id: int,
                             values: dict[str, Any]) -> None:
        """Actualize the upsert variable to prepare a batch upsert.
        Args:
            table (str): name of table
            id (int): row id
            values (dict[str, Any]): dictionary of param name - value
        """
        with self._upsert_lock:
            if table not in self._upsert:
                self._upsert[table] = {}
            self._upsert[table][id] = values

    def batch_upsert(self) -> None:
        """Upsert entries perpapred with the
        prepare_batch_upsert() method
        """
        # Take snapshot and clear under lock
        with self._upsert_lock:
            if len(self._upsert) == 0:
                return

            # Copy the data
            upsert_snapshot = {}
            for table in self._upsert:
                upsert_snapshot[table] = self._upsert[table].copy()

            # Clear immediately
            self._upsert = {}

        # Execute outside the lock
        for table in upsert_snapshot:
            ids: list[int] = []
            values: list[dict] = []
            for id in upsert_snapshot[table]:
                ids.append(id)
                values.append(upsert_snapshot[table][id])
            self.upsert_entries(
                table=table,
                ids=ids,
                values=values)

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
        with self.eng.begin() as conn:
            db_rslt: Sequence = conn.execute(query).fetchall()
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
        with self.eng.begin() as conn:
            db_rslt: Sequence = conn.execute(query).fetchall()
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
        with self.eng.begin() as conn:
            rslt: Sequence[Row[Any]] = conn.execute(query).fetchall()
        return rslt

    def get_column(self,
                   table: str,
                   column_name: str) -> list[Any]:
        """Retrieve all values from a specified column in a given table.

        Args:
            table (str): The name of the table to query.
            column_name (str): The name of the column to retrieve values from.

        Returns:
            list[Any]: A list of values from the specified column.
        """
        query = select(self.tables[table].c[column_name])
        with self.eng.begin() as conn:
            db_rslt: Sequence[Row[Any]] = conn.execute(query).fetchall()
        return [row[0] for row in db_rslt]
