from sqlalchemy import create_engine, Engine
from sqlalchemy_utils import database_exists, create_database
import getpass
import pandas as pd


class Game_db:
    def __init__(self,
                 name: str,
                 db_path: str) -> None:
        """Class managing the information storage of GAME database.
        """
        self.name: str = name
        self.path: str = db_path
        self.create()

    def remote_engine(self,
                      user: str = getpass.getuser(),
                      host: str = '127.0.0.1',
                      port: str = '3306'
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
        database: str = self.path
        eng: Engine = create_engine("mysql://{0}@{1}:{2}/{3}?charset=utf8"
                                    .format(user, host, port, database))
        return eng

    def create(self) -> None:
        """Create new database if it doesn't exist.
        """
        engine: Engine = self.remote_engine()
        if not database_exists(engine.url):
            create_database(engine.url)

    def save_data(self,
                  id: int,
                  df: pd.DataFrame) -> None:
        """Create a new table for the sim results.

        Args:
            id (int): Simulation ID
            df (pd.DataFrame):
                pd.DataFrame(data=moleFrac, index=times, columns=spec)
        """
        try:
            df.to_sql(name=f'sim_{id}',
                      con=self.remote_engine(),
                      if_exists='fail'
                      )
        except ValueError:
            pass

    def get_data(self,
                 id: int,
                 data: str = '*'):
        df: pd.DataFrame = pd.read_sql(sql=f'SELECT {data} FROM sim_{id}',
                                       con=self.remote_engine()
                                       )
        return df
