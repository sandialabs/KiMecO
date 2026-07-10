from io import BytesIO
from time import sleep
from typing import Any

import numpy as np
import pyarrow.feather as feather
from numpy.typing import NDArray
from sqlalchemy import (
    Column,
    Integer,
    LargeBinary,
    Table,
    UniqueConstraint,
    and_,
    or_,
    select,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import OperationalError

from kimeco.database.kimeco_db import Kimeco_db
from kimeco.logger_config import setup_logger


class SIM_DB(Kimeco_db):
    def __init__(self,
                 name: str,
                 path: str = '',
                 threads: int = 1,
                 tbl_name: str | None = 'G0000') -> None:
        super().__init__(name=name,
                         path=path,
                         threads=threads)

        self.columns: list[str] = ['mdl_id', 'experiment_id', 'result']
        # Kept as runtime convenience for GUI; not part of schema init.
        self.sv_species: list[str] = []

        tbls_in_db = self.get_table_names()
        for tbl in tbls_in_db:
            self.load_table(name=tbl[0])

        if tbl_name is None and tbls_in_db:
            tbl_name = tbls_in_db[0][0]
        if tbl_name is not None and self.table_exists(tbl_name):
            self._validate_schema(tbl_name)

    def _validate_schema(self, table: str) -> None:
        col_names = [c[1] for c in self.get_col_names(table)]
        if col_names != self.columns:
            raise ValueError(
                f'Unsupported SIM_DB schema in table {table}: {col_names}. '
                f'Expected {self.columns}.'
            )

    def create_new_table(self,
                         name: str) -> None:
        if name in self.tables:
            return
        if self.table_exists(name):
            self.load_table(name)
            self._validate_schema(name)
            return

        self.tables[name] = Table(
            name,
            self.metadata,
            Column('mdl_id', Integer, nullable=False),
            Column('experiment_id', Integer, nullable=False),
            Column('result', LargeBinary, nullable=False),
            UniqueConstraint('mdl_id', 'experiment_id',
                             name=f'uq_{name}_model_exp')
        )
        self.metadata.create_all(self.eng)

    @staticmethod
    def decode_result_blob(result: bytes,
                           mdl_id: int) -> tuple[NDArray, list[str]]:
        """Decode feather blob and return row-oriented matrix.

        Returned matrix columns are [mdl_id, time, species...].
        """
        table = feather.read_table(BytesIO(result))
        col_names: list[str] = list(table.column_names)
        if 'time' not in col_names:
            raise ValueError('Feather result is missing required time column')

        species = [col for col in col_names if col != 'time']
        n_steps = table.num_rows
        rows = np.zeros((n_steps, 2 + len(species)), dtype=float)
        rows[:, 0] = float(mdl_id)
        rows[:, 1] = np.array(table.column('time').to_pylist(), dtype=float)

        for idx, sp in enumerate(species):
            rows[:, idx + 2] = np.array(table.column(sp).to_pylist(),
                                        dtype=float)

        return rows, species

    def get_single_result(self,
                          table: str,
                          mdl_id: int,
                          experiment_id: int
                          ) -> tuple[NDArray, list[str]] | None:
        """Fetch and decode a single result blob on demand.

        Returns the decoded ``[mdl_id, time, species...]`` matrix and the
        species list, or ``None`` if the row does not exist.
        """
        if table not in self.tables:
            if not self.table_exists(table):
                return None
            self.load_table(table)

        query = select(
            self.tables[table].c.result,
        ).where(
            and_(
                self.tables[table].c.mdl_id == int(mdl_id),
                self.tables[table].c.experiment_id == int(experiment_id),
            )
        )
        with self.eng.begin() as conn:
            row = conn.execute(query).fetchone()
        if row is None:
            return None

        decoded, species = self.decode_result_blob(
            result=row.result,
            mdl_id=int(mdl_id),
        )
        if len(self.sv_species) == 0 and len(species) != 0:
            self.sv_species = species
        return decoded, species

    def get_all_results(self,
                        table: str
                        ) -> list[tuple[int, int, NDArray, list[str]]]:
        """Decode every row of ``table`` for bulk export.

        Returns a list of ``(mdl_id, experiment_id, decoded, species)``
        tuples where ``decoded`` is the ``[mdl_id, time, species...]``
        matrix from :meth:`decode_result_blob`.
        """
        if table not in self.tables:
            if not self.table_exists(table):
                return []
            self.load_table(table)

        query = select(
            self.tables[table].c.mdl_id,
            self.tables[table].c.experiment_id,
            self.tables[table].c.result,
        )
        with self.eng.begin() as conn:
            db_rows = conn.execute(query).fetchall()

        results: list[tuple[int, int, NDArray, list[str]]] = []
        for row in db_rows:
            decoded, species = self.decode_result_blob(
                result=row.result,
                mdl_id=int(row.mdl_id),
            )
            if len(self.sv_species) == 0 and len(species) != 0:
                self.sv_species = species
            results.append(
                (int(row.mdl_id), int(row.experiment_id), decoded, species))
        return results

    def prepare_batch_upsert(self,
                             table: str,
                             mdl_id: int,
                             experiment_id: int,
                             result: bytes) -> None:
        with self._upsert_lock:
            if table not in self._upsert:
                self._upsert[table] = {}
            self._upsert[table][(mdl_id, experiment_id)] = result

    def batch_upsert(self) -> None:
        with self._upsert_lock:
            if len(self._upsert) == 0:
                return
            upsert_snapshot = {
                table: payload.copy()
                for table, payload in self._upsert.items()
            }
            self._upsert = {}

        for table, payload in upsert_snapshot.items():
            if table not in self.tables:
                self.create_new_table(table)

            rows: list[dict[str, Any]] = []
            for (mdl_id, experiment_id), result in payload.items():
                rows.append({
                    'mdl_id': int(mdl_id),
                    'experiment_id': int(experiment_id),
                    'result': result,
                })
            if len(rows) == 0:
                continue

            stmt = insert(self.tables[table]).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    self.tables[table].c.mdl_id,
                    self.tables[table].c.experiment_id,
                ],
                set_={'result': stmt.excluded.result}
            )

            try2connect = 0
            tot_try = 10
            while try2connect < tot_try:
                try2connect += 1
                try:
                    with self.eng.begin() as conn:
                        conn.execute(stmt)
                    if self.sleep_time >= 10:
                        self.sleep_time -= 1
                    break
                except OperationalError as e:
                    if 'database is locked' in str(e):
                        self.sleep_time += 5
                        sleep(self.sleep_time)
                    else:
                        klog = setup_logger(name='sim_db.log')
                        klog.warning('An OperationalError occured in the db:')
                        klog.warning(str(e))
                except Exception as e:
                    klog = setup_logger(name='sim_db.log')
                    klog.warning('An error occured in the database:')
                    klog.warning(str(e))
                    raise TypeError(e)
            else:
                klog = setup_logger(name='sim.log')
                msg: str = (
                    f'DB locked for {self.sleep_time*tot_try/60:.2f} min.'
                )
                klog.warning(msg)
                self.sleep_time += 5
                klog.warning(f'Reconnect extended to {self.sleep_time:2f} s.')

    def prepare_batch_select(self,
                             table: str,
                             mdl_id: int,
                             experiment_id: int) -> None:
        with self._select_lock:
            if table not in self._select:
                self._select[table] = set()
            self._select[table].add((int(mdl_id), int(experiment_id)))

    def batch_select(self) -> dict[str, dict[int, dict[int, NDArray]]]:
        """Return decoded rows keyed by table/mdl_id/experiment_id."""
        with self._select_lock:
            if len(self._select) == 0:
                return {}
            select_snapshot = {
                table: pairs.copy() for table, pairs in self._select.items()
            }
            self._select = {}

        results: dict[str, dict[int, dict[int, NDArray]]] = {}

        for table, req_pairs in select_snapshot.items():
            if len(req_pairs) == 0:
                continue
            conditions = [
                and_(
                    self.tables[table].c.mdl_id == mdl_id,
                    self.tables[table].c.experiment_id == experiment_id,
                )
                for mdl_id, experiment_id in req_pairs
            ]
            query = select(
                self.tables[table].c.mdl_id,
                self.tables[table].c.experiment_id,
                self.tables[table].c.result,
            ).where(or_(*conditions))

            try2connect = 0
            tot_try = 10
            while try2connect < tot_try:
                try2connect += 1
                try:
                    with self.eng.begin() as conn:
                        db_rows = conn.execute(query).fetchall()
                    if self.sleep_time >= 10:
                        self.sleep_time -= 1
                    break
                except OperationalError as e:
                    if 'database is locked' in str(e):
                        self.sleep_time += 5
                        sleep(self.sleep_time)
                    else:
                        klog = setup_logger(name='sim_db.log')
                        klog.warning('An OperationalError occured in the db:')
                        klog.warning(str(e))
                except Exception as e:
                    klog = setup_logger(name='sim_db.log')
                    klog.warning('An error occured in the database:')
                    klog.warning(str(e))
                    raise TypeError(e)
            else:
                klog = setup_logger(name='sim.log')
                msg: str = (
                    f'DB locked for {self.sleep_time*tot_try/60:.2f} min.'
                )
                klog.warning(msg)
                self.sleep_time += 5
                klog.warning(f'Reconnect extended to {self.sleep_time:2f} s.')
                return results

            for row in db_rows:
                key = (int(row.mdl_id), int(row.experiment_id))
                if key not in req_pairs:
                    continue
                decoded, species = self.decode_result_blob(
                    result=row.result,
                    mdl_id=int(row.mdl_id),
                )
                if len(self.sv_species) == 0 and len(species) != 0:
                    self.sv_species = species
                if table not in results:
                    results[table] = {}
                if key[0] not in results[table]:
                    results[table][key[0]] = {}
                results[table][key[0]][key[1]] = decoded

        return results
