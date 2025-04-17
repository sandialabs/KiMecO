from kimeco.database.kimeco_db import Kimeco_db
from kimeco.parameters import SOP
from sqlalchemy import select, Row
from typing import Any, Sequence
from numpy.typing import NDArray
import numpy as np
from numpy import int32, str_, float64


class KIN_DB(Kimeco_db):
    def __init__(self,
                 sop: SOP,
                 name: str,
                 path: str = '',) -> None:
        super().__init__(name=name,
                         path=path)

        self.columns: list[str] = ['P', 'T', 'kin_id', 'specie']
        self.columns.extend(sop.wells_names)
        self.columns.extend(sop.bimols_names)
        self.types: list = [float, float, int, str]
        self.types.extend([float for i in range(
            len(sop.wells_names) +
            len(sop.bimols_names))])

        tbls_in_db = self.get_table_names()

        for tbl in tbls_in_db:
            self.create_table(name=tbl[0])

    def create_table(self,
                     name: str) -> None:
        return super().create_table(name=name,
                                    columns=self.columns,
                                    types=self.types)

    def get_kin_rc(self,
                   table: str,
                   From: str,
                   To: str,
                   pres: float,
                   temp: float) -> list[Any]:
        """Query the rate coefficients.

        Args:
            table (str): Generation
            From (str): Species name
            To (str): Specie name
            pres (float): Pressure (Torr)
            temp (float): Temperature (K)

        Returns:
            list[Any]: _description_
        """
        query = select(
            self.tables[table].c.kin_id,
            self.tables[table].c[To],
            ).where(
                self.tables[table].c.P == pres,
                self.tables[table].c.T == temp,
                self.tables[table].c.specie == From)
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)

    def get_ids_from_kin_id(self,
                            table: str,
                            kin_id: int):

        query = select(
            self.tables[table].c.id
            ).where(
                self.tables[table].c.kin_id == kin_id)
        with self.eng.begin() as connection:
            db_rslt: Sequence = connection.execute(query).fetchall()
        return list(db_rslt)

    def prepare_batch_select(self,
                             table: str,
                             kin_id: int,
                             p: float,
                             t: float,
                             From: str,
                             To: str) -> None:
        """Prepare a batch select request to store in the _select dictionary.

        Args:
            table (str): table names
            kin_id (int): id of the RateCo object
            p (float): pressure (Torr)
            t (float): temperature (Kelvin)
            From (str): specie name
            To (str): specie name
        """

        if table not in self._select:
            self._select[table] = {}
        if kin_id not in self._select[table]:
            self._select[table][kin_id] = {
                'pres': [],
                'temp': [],
                'From': [],
                'To': []
            }
        self._select[table][kin_id]['pres'].append(p)
        self._select[table][kin_id]['temp'].append(t)
        self._select[table][kin_id]['To'].append(To)
        self._select[table][kin_id]['From'].append(From)

    def batch_select(self) -> dict[str, dict[int, NDArray]]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            dict[str, dict[int, NDArray]]:
                str: table name.
                int: sim_id within this table.
                NDArray: [rows, [sim_id, time, concentrations]]
        """
        results: dict[dict[NDArray]] = {}
        for table in self._select:
            kin_ids = [kid for kid in self._select[table].keys()]
            tmp_pres = []
            tmp_temp = []
            tmp_From = []
            tmp_To = []
            for kin_id in kin_ids:
                tmp_pres.extend(self._select[table][kin_id]['pres'])
                tmp_temp.extend(self._select[table][kin_id]['temp'])
                tmp_From.extend(self._select[table][kin_id]['From'])
                tmp_To.extend(self._select[table][kin_id]['To'])
            pres = set(tmp_pres)
            temp = set(tmp_temp)
            To = set(tmp_To)
            From = set(tmp_From)
            
            db_row = np.dtype(dtype=[
                ('kin_id', int32),
                ('p', float64),
                ('t', float64),
                ('specie', str_, (30)),
                *[(to, float64) for to in To]])

            query = select(
                self.tables[table].c.kin_id,
                self.tables[table].c.P,
                self.tables[table].c.T,
                self.tables[table].c.specie,
                *[self.tables[table].c[to]
                  for to in To]
            ).where(
                self.tables[table].c.kin_id.in_(kin_ids),
                self.tables[table].c.P.in_(pres),
                self.tables[table].c.T.in_(temp),
                self.tables[table].c.specie.in_(From))
            with self.eng.begin() as connection:
                db_rslt: Sequence[Row[Any]] = connection.execute(
                        query).fetchall()
            db_arr = np.empty(shape=(len(db_rslt)), dtype=db_row)
            for idx, row in enumerate(db_rslt):
                # Structured numpy array must be set with imutable
                db_arr[idx] = tuple(row)
            results[table] = {}
            if len(db_arr) != 0:
                for kin_id in set(db_arr['kin_id']):
                    if int(kin_id) not in results[table]:
                        results[table][int(kin_id)] = {}
                        for p in pres:
                            for t in temp:
                                for to in To:
                                    for frm in From:
                                        condition = \
                                            (db_arr['kin_id'] ==
                                             int(kin_id)) &\
                                            (db_arr['p'] == p) &\
                                            (db_arr['t'] == t) &\
                                            (db_arr['specie'] == frm)
                                        key = (p, t, to, frm)
                                        results[table][int(kin_id)][key] =\
                                            db_arr[condition][to][0]

        self._select = {}  # Clear the _select dictionary after processing
        return results
