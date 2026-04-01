from kimeco.database.kimeco_db import Kimeco_db
from kimeco.parameters import SOP
from sqlalchemy import select
from sqlalchemy.sql import text
from sqlalchemy.engine import Row
from typing import Any, Sequence
import numpy as np
from numpy import int32, str_, float64


class KIN_DB(Kimeco_db):
    def __init__(self,
                 sop: SOP,
                 name: str,
                 path: str = '',
                 threads: int = 1) -> None:
        super().__init__(name=name,
                         path=path,
                         threads=threads)
        self.sop: SOP = sop

        self.columns: list[str] = [
            'P',
            'T',
            'kin_id',
            'pes_id',
            'from_name',
            'to_name',
            'k',
        ]
        self.types: list = [float, float, int, int, str, str, float]

        tbls_in_db = self.get_table_names()

        for tbl in tbls_in_db:
            self.load_table(name=tbl[0])

    def create_new_table(self,
                         name: str) -> None:
        super().create_table(name=name,
                             columns=self.columns,
                             types=self.types)
        with self.eng.begin() as conn:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{name}_kin_pt_pair "
                f"ON '{name}' (kin_id, P, T, pes_id, from_name, to_name)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{name}_pt_pair "
                f"ON '{name}' (P, T, from_name, to_name)"
            ))

    def get_kin_rc(self,
                   table: str,
                   from_name: str,
                   to_name: str,
                   pres: float,
                   temp: float,
                   pes_id: int | None = None) -> list[Any]:
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
            self.tables[table].c.k,
            ).where(
                self.tables[table].c.P == pres,
                self.tables[table].c.T == temp,
                self.tables[table].c.from_name == from_name,
                self.tables[table].c.to_name == to_name)
        if pes_id is not None:
            query = query.where(self.tables[table].c.pes_id == pes_id)
        with self.eng.begin() as conn:
            db_rslt: Sequence = conn.execute(query).fetchall()
        return list(db_rslt)

    def get_kin_rc_for_kin_id(self,
                              table: str,
                              from_name: str,
                              to_name: str,
                              pres: float,
                              temp: float,
                              kin_id: int,
                              pes_id: int | None = None) -> list[Any]:
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
            self.tables[table].c.k,
            ).where(
                self.tables[table].c.P == pres,
                self.tables[table].c.T == temp,
                self.tables[table].c.kin_id == kin_id,
                self.tables[table].c.from_name == from_name,
                self.tables[table].c.to_name == to_name)
        if pes_id is not None:
            query = query.where(self.tables[table].c.pes_id == pes_id)
        with self.eng.begin() as conn:
            db_rslt: Sequence = conn.execute(query).fetchall()
        return list(db_rslt)

    def get_ids_from_kin_id(self,
                            table: str,
                            kin_id: int):

        query = select(
            self.tables[table].c.id
            ).where(
                self.tables[table].c.kin_id == kin_id)
        with self.eng.begin() as conn:
            db_rslt: Sequence = conn.execute(query).fetchall()
        return [row[0] for row in db_rslt]

    def prepare_batch_select(self,
                             table: str,
                             kin_id: int,
                             p: float,
                             t: float,
                             from_name: str,
                             to_name: str,
                             pes_id: int | None = None) -> None:
        """Prepare a batch select request to store in the _select dictionary.

        Args:
            table (str): table names
            kin_id (int): id of the RateCo object
            p (float): pressure (Torr)
            t (float): temperature (Kelvin)
            From (str): specie name
            To (str): specie name
        """
        with self._select_lock:
            if table not in self._select:
                self._select[table] = {}
            if kin_id not in self._select[table]:
                self._select[table][kin_id] = {
                    'pres': [],
                    'temp': [],
                    'from_name': [],
                    'to_name': [],
                    'pes_id': []
                }
            self._select[table][kin_id]['pres'].append(p)
            self._select[table][kin_id]['temp'].append(t)
            self._select[table][kin_id]['to_name'].append(to_name)
            self._select[table][kin_id]['from_name'].append(from_name)
            self._select[table][kin_id]['pes_id'].append(pes_id)

    def batch_select(self) -> dict[
        str,
        dict[int, dict[tuple[float, float, int, str, str], float]],
    ]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            dict[
                str,
                dict[int, dict[tuple[float, float, int, str, str], float]],
            ]:
                str: table name.
                int: kin_id within this table.
                tuple: (p, t, pes_id, from_name, to_name)
                float: rate coefficient value
        """
        # Take snapshot and clear under lock
        with self._select_lock:
            if len(self._select) == 0:
                return {}

            select_snapshot = {}
            for table in self._select:
                select_snapshot[table] = {}
                for kin_id in self._select[table]:
                    select_snapshot[table][kin_id] = {
                        'pres': self._select[table][kin_id]['pres'].copy(),
                        'temp': self._select[table][kin_id]['temp'].copy(),
                        'from_name':
                        self._select[table][kin_id]['from_name'].copy(),
                        'to_name':
                        self._select[table][kin_id]['to_name'].copy(),
                        'pes_id': self._select[table][kin_id]['pes_id'].copy()
                    }
            self._select = {}

        # Execute outside the lock
        results: dict[
            str, dict[int, dict[tuple[float, float, int, str, str], float]]
        ] = {}
        for table in select_snapshot:
            kin_ids = [kid for kid in select_snapshot[table].keys()]
            tmp_pres = []
            tmp_temp = []
            tmp_from = []
            tmp_to = []
            tmp_pes = []
            for kin_id in kin_ids:
                tmp_pres.extend(select_snapshot[table][kin_id]['pres'])
                tmp_temp.extend(select_snapshot[table][kin_id]['temp'])
                tmp_from.extend(select_snapshot[table][kin_id]['from_name'])
                tmp_to.extend(select_snapshot[table][kin_id]['to_name'])
                tmp_pes.extend(select_snapshot[table][kin_id]['pes_id'])
            pres = set(tmp_pres)
            temp = set(tmp_temp)
            to_names = set(tmp_to)
            from_names = set(tmp_from)
            pes_ids = set([pid for pid in tmp_pes if pid is not None])

            db_row = np.dtype(dtype=[
                ('kin_id', int32),
                ('p', float64),
                ('t', float64),
                ('pes_id', int32),
                ('from_name', str_, (30)),
                ('to_name', str_, (30)),
                ('k', float64),
            ])

            query = select(
                self.tables[table].c.kin_id,
                self.tables[table].c.P,
                self.tables[table].c.T,
                self.tables[table].c.pes_id,
                self.tables[table].c.from_name,
                self.tables[table].c.to_name,
                self.tables[table].c.k,
            ).where(
                self.tables[table].c.kin_id.in_(kin_ids),
                self.tables[table].c.P.in_(pres),
                self.tables[table].c.T.in_(temp),
                self.tables[table].c.from_name.in_(from_names),
                self.tables[table].c.to_name.in_(to_names),
            )
            if len(pes_ids) > 0:
                query = query.where(self.tables[table].c.pes_id.in_(pes_ids))
            with self.eng.begin() as conn:
                db_rslt: Sequence[Row[Any]] = conn.execute(
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
                    condition = (db_arr['kin_id'] == int(kin_id))
                    for row in db_arr[condition]:
                        key = (
                            float(row['p']),
                            float(row['t']),
                            int(row['pes_id']),
                            str(row['from_name']),
                            str(row['to_name']),
                        )
                        results[table][int(kin_id)][key] = float(row['k'])

        return results

    def _legacy_dynamic_columns(self,
                                table: str) -> list[str]:
        """Return dynamic species columns from a legacy wide KIN table."""
        fixed_cols = {'id', 'P', 'T', 'kin_id', 'specie'}
        db_cols = [col[1] for col in self.get_col_names(table)]
        if not {'P', 'T', 'kin_id', 'specie'}.issubset(set(db_cols)):
            raise ValueError(
                f"Table '{table}' is not a legacy kinetics wide-format table."
            )
        return [col for col in db_cols if col not in fixed_cols]

    def migrate_legacy_table(self,
                             legacy_table: str,
                             target_table: str | None = None,
                             overwrite: bool = False,
                             dry_run: bool = False) -> dict[str, int]:
        """Migrate one legacy wide KIN table to long-format schema.

        Legacy rows are assumed to belong to a single PES and are migrated
        with `pes_id = 0`.
        """
        if len(self.sop.pes_ids) > 1:
            raise ValueError(
                'Legacy migration only supports a single-PES SOP context. '
                f'Found PES ids: {self.sop.pes_ids}'
            )

        if not self.table_exists(legacy_table):
            raise ValueError(f"Legacy table '{legacy_table}' does not exist.")

        dynamic_cols = self._legacy_dynamic_columns(legacy_table)
        if len(dynamic_cols) == 0:
            raise ValueError(
                f"Legacy table '{legacy_table}' has no species "
                'columns to migrate.'
            )

        if target_table is None:
            target_table = f'{legacy_table}_v2'

        if self.table_exists(target_table):
            if overwrite:
                self.wipe_table(target_table)
            elif not dry_run:
                raise ValueError(
                    f"Target table '{target_table}' already exists. "
                    'Use overwrite=True or provide another target table name.'
                )

        if not dry_run and not self.table_exists(target_table):
            self.create_new_table(name=target_table)

        legacy_sql_table = self.tables[legacy_table]
        query = select(legacy_sql_table).order_by(legacy_sql_table.c.id)
        with self.eng.begin() as conn:
            legacy_rows: Sequence[Row[Any]] = conn.execute(query).fetchall()

        migrated_rows = 0
        nonzero_rows = 0
        missing_rows = 0

        for ridx, row in enumerate(legacy_rows):
            row_map = row._mapping
            p_val = float(row_map['P'])
            t_val = float(row_map['T'])
            kin_id = int(row_map['kin_id'])
            from_name = str(row_map['specie'])

            for cidx, to_name in enumerate(dynamic_cols):
                raw_k = row_map[to_name]
                if raw_k is None:
                    missing_rows += 1
                    k_val = 0.0
                else:
                    k_val = float(raw_k)
                if k_val != 0.0:
                    nonzero_rows += 1

                migrated_rows += 1
                if dry_run:
                    continue

                row_id = ridx * len(dynamic_cols) + cidx
                values = {
                    'P': p_val,
                    'T': t_val,
                    'kin_id': kin_id,
                    'pes_id': 0,
                    'from_name': from_name,
                    'to_name': str(to_name),
                    'k': k_val,
                }
                self.prepare_batch_upsert(table=target_table,
                                          id=row_id,
                                          values=values)

        if not dry_run:
            self.batch_upsert()

        return {
            'legacy_rows': len(legacy_rows),
            'species_columns': len(dynamic_cols),
            'migrated_rows': migrated_rows,
            'nonzero_rows': nonzero_rows,
            'missing_rows': missing_rows,
        }

    def migrate_all_legacy_tables(self,
                                  tables: list[str] | None = None,
                                  target_suffix: str = '_v2',
                                  overwrite: bool = False,
                                  dry_run: bool = False
                                  ) -> dict[str, dict[str, int]]:
        """Migrate all requested legacy wide KIN tables to long format."""
        if tables is None:
            tables = [name[0] for name in self.get_table_names()]

        summary: dict[str, dict[str, int]] = {}
        for table in tables:
            try:
                target = f'{table}{target_suffix}'
                summary[table] = self.migrate_legacy_table(
                    legacy_table=table,
                    target_table=target,
                    overwrite=overwrite,
                    dry_run=dry_run,
                )
            except ValueError:
                # Skip tables that are not legacy kinetics wide-format tables.
                continue
        return summary
