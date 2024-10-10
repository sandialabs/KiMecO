import os
from sqlalchemy import create_engine, Engine
from sqlalchemy_utils import database_exists, create_database
import pandas as pd
from pandas import DataFrame


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
                      if_exists='append',
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
                     species: list[str],
                     sim_id: int,
                     gen: int) -> DataFrame:

        with self.eng.begin() as connection:
            df: DataFrame = pd.read_sql(
                sql="""SELECT *
                FROM sim
                WHERE sim_id={} AND gen={}""".format(
                    #','.join(species),
                    sim_id,
                    gen
                ),
                con=connection)
        return df
