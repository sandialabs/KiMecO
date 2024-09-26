from sqlalchemy import create_engine, Engine
from sqlalchemy_utils import database_exists, create_database
import pandas as pd
from pandas import DataFrame


class Game_db:
    def __init__(self,
                 name: str) -> None:
        """Class managing the information storage of GAME database.
        """
        self.name: str = name
        self.eng: Engine = create_engine(f'sqlite:///{name}.db',
                                         pool_size=32,
                                         max_overflow=32)
        if not database_exists(self.eng.url):
            create_database(self.eng.url)

    def save_data(self,
                  table: str,
                  df: pd.DataFrame) -> None:
        """Create a new table for the sim results.

        Args:
            name (str): sop, kin or sim
            df (pd.DataFrame):
                pd.DataFrame(data=moleFrac, index=times, columns=spec)
        """
        with self.eng.begin() as connection:
            df.to_sql(name=table,
                      con=connection,
                      if_exists='replace',
                      index=False
                      )

    def get_sop_data(self,
                     parameters: list[str],
                     sop_ids: list[int]
                     ) -> None:
        """Pull all the desired parameters for all the desired SOPs
           from the database.

        Args:
            parameters (list[str]): List of the parameters names to query.
            sop_ids (list[int]): List of sop_ids for which to query.
        """

        command: str = f'SELECT sop_id, {", ".join(parameters)} FROM sop'
        first = True
        for sop_id in sop_ids:
            if first:
                first = False
                command += f' WHERE sop_id={sop_id}'
            else:
                command += f' OR WHERE sop_id={sop_id}'

        with self.eng.begin() as connection:
            df: DataFrame = pd.read_sql(sql=command,
                                        con=connection
                                        )
        print(df)

    def save_sim_data(self,
                      df: DataFrame) -> None:
        """Create a new table for the sim results.

        Args:
            name (str): sop, kin or sim
            df (pd.DataFrame):
                pd.DataFrame(data=moleFrac, index=times, columns=spec)
        """
        with self.eng.begin() as connection:
            df.to_sql(name='sim',
                      con=connection,
                      if_exists='replace',
                      index=False
                      )

    def get_sim_data(self,
                     index: str = '*') -> DataFrame:

        with self.eng.begin() as connection:
            df: DataFrame = pd.read_sql(
                sql=f'SELECT * FROM sim WHERE sop_id={index}',
                con=connection)
        return df
