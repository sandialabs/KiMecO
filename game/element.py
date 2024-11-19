from game.database.game_db import Game_db
from game.parameters import SOP
from game.rate_coef import RateCo
from game.scoring_f.scoring import Scoring
from game.simulation import SIM
from typing import Any, Literal
from pandas import DataFrame


class Element:

    def __init__(self,
                 sop: SOP,
                 id: int,
                 sf: Scoring) -> None:
        """An element is part of a generation and has
        different attributes, such as an id and a status.
        It is mainly a container object.

        Args:
            sop (SOP): perturbed set of parameters

        Attributes:
            status (int): Status of the element
                0 - initialized
                1 - Rate coefficients are submitted
                2 - Rate coefficients are calculated
                3 - Cantera simulations submitted
                4 - Cantera simulations finished
                5 - Scoring is finished for all P and T
            id (int): ID of the element.
        """
        self.sop: SOP = sop
        self.status: str = 'sop'
        self.id: int = id
        self.sop.id = self.id
        self.rateCoef: RateCo
        self.sim: SIM
        self.sf: Scoring = sf

    def save_sop(self,
                 db: Game_db,
                 table: str,
                 mode: Literal['default',
                               'scratch']) -> None:
        """Save the SOP in the database in the table
        of the generation

        Args:
            db (Game_db): SOP Game database
            table (str): Table name (GX)
            mode (Literal):
                'default': Make the SOP in the worflow equal to the db entry
                'scratch': Update the db with new SOP values.
        """
        db_table: dict[str, Any] = {}
        db_table.update(self.sop.parameters_names)

        df: DataFrame = DataFrame(data=db_table, index=[self.id])
        df.index.name = 'id'

        if db.entry_exist(table=table,
                          id=self.id):
            if mode == 'scratch':
                db.update_entry(table=table,
                                id=self.id,
                                values=db_table)
            elif mode == 'default':
                sop_param: list[str] = \
                    [key for key in self.sop.parameters_names.keys()]
                db_param: list[str] = \
                    [key for key in db.tables[table].columns.keys()]
                if sop_param != db_param[1:]:
                    raise KeyError(
                        "The db and workflow parameters are different.")

                row: list[float] = db.get_sop_row(table=table,
                                                  id=self.id)
                pos = 0
                for key, val in self.sop.parameters_names.items():
                    if val != row[pos]:
                        self.sop.update(key=key,
                                        value=val)
                    pos += 1
        else:
            db.save_data(table=table,
                         df=df,
                         mode='append')

    def save_kin(self,
                 db: Game_db,
                 table: str) -> None:
        """Save the RateCoef in the database in the table
        of the generation

        Args:
            db (Game_db): KIN Game database
            table (str): Table name (GX)
        """
        df: DataFrame = self.rateCoef.recover_rslts()
        # Happens if the ME calculation didn't converge
        if len(df) == 0:
            self.status = 'reset'
            return
        if db.entry_exist(table=table,
                          id=df.index[0]):
            # Make sure the data in db are always consistent witgh the run
            for id in df.index:
                db_table: dict[str, Any] = df.loc[id].to_dict()
                db.update_entry(table=table,
                                id=id,
                                values=db_table)
        else:
            db.save_data(table=table,
                         df=df,
                         mode='append')
        self.status = 'kin2sim'

    def check_rc_status(self) -> None:
        self.rateCoef.set_status()
        if self.rateCoef.status == 'reset':
            self.status = 'reset'

    def recover_sim_profiles(self,
                             db: Game_db,
                             table) -> None:
        for sim in range(len(self.sim.simulations)):
            self.sim.profiles.append(
                db.get_sim_data(table=table,
                                sim_id=self.id*len(self.sim.simulations)+sim)
            )

    def calc_score(self,
                   settings: dict[str, Any]) -> None:
        """Calculate the score of the element
        using the user requested function.
        If the elif statement for a new scoring function
        is missing, also add the chosen string to
        the implemented_sf list in default_settings.py.

        Args:
            settings (dict[str, Any]): User input + default settings
        """

        self.sop.score = self.sf.score(sim=self.sim,
                                       exp_profiles=settings['exp_profiles'])

    @property
    def score(self) -> float:
        return self.sop.score

    def prepare_upsert(self,
                       db: Game_db,
                       table: str) -> None:
        db.prepare_batch_upsert(table=table,
                                id=self.id,
                                values=self.sop.parameters_names)
