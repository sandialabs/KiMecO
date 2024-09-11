from sqlalchemy import URL, create_engine, Engine
from sqlalchemy_utils import database_exists, create_database
import pandas as pd
from pandas import DataFrame


class Game_db:
    def __init__(self,
                 name: str,
                 db_path: str,
                 user: str,
                 host_name: str) -> None:
        """Class managing the information storage of GAME database.
        """
        self.name: str = name
        self.path: str = db_path
        self.user: str = user
        self.host: str = host_name
        self.create()

    def remote_engine(self,
                      port: int = 5432
                      ) -> Engine:
        """Return a sqlalchemy Engine object to connect to the DB.

        Args:
            user (str, optional): User name on host.
                                  Defaults to getpass.getuser().
            host (str, optional): Host name. Defaults to '127.0.0.1'.
            port (str, optional): port number. Defaults to '3306'.

        Returns:
            Engine: _description_
        """
        database: str = f'{self.path}/{self.name}'
        url_object: URL = URL.create(drivername="postgresql",
                                     username=self.user,
                                     host=self.host,
                                     port=port,
                                     database=database)

        eng: Engine = create_engine(url_object,
                                    pool_size=32,
                                    max_overflow=32)
        return eng

    def create(self) -> None:
        """Create new database if it doesn't exist.
        """
        engine: Engine = self.remote_engine()
        if not database_exists(engine.url):
            create_database(engine.url)

    def save_data(self,
                  tablename: str,
                  df: pd.DataFrame) -> None:
        """Create a new table for the sim results.

        Args:
            name (str): sop, kin or sim
            df (pd.DataFrame):
                pd.DataFrame(data=moleFrac, index=times, columns=spec)
        """
        try:
            df.to_sql(name=tablename,
                      con=self.remote_engine(),
                      if_exists='replace'
                      )
        except ValueError:
            pass

    def get_data(self,
                 tablename: str,
                 index: str = '*') -> DataFrame:
        df: pd.DataFrame = pd.read_sql(sql=f'SELECT {index} FROM {tablename}',
                                       con=self.remote_engine().connect()
                                       )
        return df
