from kimeco.database.kimeco_db import Kimeco_db
from kimeco.parameters import SOP
from sqlalchemy import Column, String, Table, select
from sqlalchemy.engine import Row
from sqlalchemy.dialects.sqlite import insert
from kimeco.logger_config import KMOLogger
from typing import Any, Sequence
import json
import os


class SOPItemPesIdsTable:
    table_name = '__sop_item_pes_ids'
    item_column = 'item'
    pes_ids_column = 'pes_ids'

    def __init__(self,
                 metadata,
                 engine,
                 exists: bool = False) -> None:
        if exists:
            self.table = Table(
                self.table_name,
                metadata,
                autoload_with=engine,
                extend_existing=True,
            )
        else:
            self.table = Table(
                self.table_name,
                metadata,
                Column(self.item_column, String, primary_key=True),
                Column(self.pes_ids_column, String, nullable=False),
                extend_existing=True,
            )

    @staticmethod
    def serialize_pes_ids(pes_ids: Sequence[int]) -> str:
        return json.dumps(list(SOP.normalize_pes_ids(pes_ids)))

    @classmethod
    def serialize_map(
        cls,
        item_pes_ids: dict[str, tuple[int, ...]],
    ) -> list[dict[str, str]]:
        return [
            {
                cls.item_column: item,
                cls.pes_ids_column: cls.serialize_pes_ids(pes_ids),
            }
            for item, pes_ids in sorted(item_pes_ids.items())
        ]

    @staticmethod
    def deserialize_pes_ids(raw_pes_ids: str) -> tuple[int, ...]:
        return SOP.normalize_pes_ids(json.loads(raw_pes_ids))


class SOP_DB(Kimeco_db):
    def __init__(self,
                 sop: SOP,
                 name: str,
                 path: str = '',
                 threads: int = 1,
                 klog: KMOLogger | None = None) -> None:
        db_path = os.path.join(path or os.getcwd(), f'{name}.db')
        self._db_file_exists = os.path.isfile(db_path)
        super().__init__(name=name,
                         path=path,
                         threads=threads)

        # Keep a reference to the SOP template used to build this DB
        # This allows other modules to reconstruct SOP objects from DB rows
        self.sop_tpl: SOP = sop
        self.klog: KMOLogger | None = klog
        self.item_pes_table: SOPItemPesIdsTable | None = None

        self.columns: list[str] = \
            [key for key in sop.parameters_names.keys()]
        self.types: list[type] = \
            [type(val) for val in sop.parameters_names.values()]
        tbls_in_db = self.get_table_names()
        for tbl in tbls_in_db:
            if tbl[0] == SOPItemPesIdsTable.table_name:
                self.item_pes_table = SOPItemPesIdsTable(
                    metadata=self.metadata,
                    engine=self.eng,
                    exists=True,
                )
                continue
            self.load_table(name=tbl[0])
            # Causes slow-down
            # self.create_table(name=tbl[0],
            #                      columns=self.columns,
            #                      types=self.types)
        self.validate_or_initialize_item_pes_ids()

    def create_new_table(self,
                         name: str) -> None:
        super().create_table(
            name=name,
            columns=self.columns,
            types=self.types)

    def has_generation_tables(self) -> bool:
        return len(self.tables) > 0

    def has_item_pes_table(self) -> bool:
        return self.item_pes_table is not None

    def ensure_item_pes_table(self) -> None:
        if self.item_pes_table is None:
            self.item_pes_table = SOPItemPesIdsTable(
                metadata=self.metadata,
                engine=self.eng,
                exists=False,
            )
            self.metadata.create_all(
                self.eng,
                tables=[self.item_pes_table.table],
            )

    def save_item_pes_ids(self,
                          sop: SOP | None = None) -> None:
        self.ensure_item_pes_table()
        assert self.item_pes_table is not None
        table = self.item_pes_table.table
        payload = SOPItemPesIdsTable.serialize_map(
            (sop or self.sop_tpl).item_pes_ids
        )
        if not payload:
            return
        insert_stmt = insert(table).values(payload)
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[table.c.item],
            set_={
                SOPItemPesIdsTable.pes_ids_column:
                    insert_stmt.excluded.pes_ids,
            },
        )
        with self.eng.begin() as conn:
            conn.execute(upsert_stmt)

    def get_item_pes_ids(self) -> dict[str, tuple[int, ...]]:
        if self.item_pes_table is None:
            return {}
        query = select(
            self.item_pes_table.table.c.item,
            self.item_pes_table.table.c.pes_ids,
        )
        with self.eng.begin() as conn:
            rows = conn.execute(query).fetchall()
        return {
            row[0]: SOPItemPesIdsTable.deserialize_pes_ids(row[1])
            for row in rows
        }

    def compare_item_pes_ids(self,
                             sop: SOP | None = None) -> tuple[bool, str]:
        current_map = (sop or self.sop_tpl).item_pes_ids
        db_map = self.get_item_pes_ids()
        missing_in_db = sorted(set(current_map) - set(db_map))
        extra_in_db = sorted(set(db_map) - set(current_map))
        changed_items = [
            item for item in sorted(set(current_map) & set(db_map))
            if current_map[item] != db_map[item]
        ]
        if not missing_in_db and not extra_in_db and not changed_items:
            return True, ''

        details: list[str] = []
        if missing_in_db:
            details.append(
                'Missing items in SOP_DB metadata: '
                + ', '.join(missing_in_db[:5])
            )
        if extra_in_db:
            details.append(
                'Unexpected items in SOP_DB metadata: '
                + ', '.join(extra_in_db[:5])
            )
        for item in changed_items[:5]:
            details.append(
                f"Item {item}: current pes_ids={list(current_map[item])}, "
                f"database pes_ids={list(db_map[item])}"
            )
        message = (
            f'SOP_DB {self.name} contains an item/PES_ID mapping that '
            'does not match the current input. This can happen if the order '
            'of the MESS input files changed between runs. '
            'The run was stopped '
            'to avoid reusing inconsistent restart data.\n'
            + '\n'.join(details)
        )
        return False, message

    def validate_or_initialize_item_pes_ids(self) -> None:
        if self.has_item_pes_table():
            matches, message = self.compare_item_pes_ids()
            if not matches:
                if self.klog is not None:
                    self.klog.error(message)
                raise ValueError(message)
            return

        if self.has_generation_tables() or self._db_file_exists:
            return

        self.save_item_pes_ids()

    def get_sop_row(self,
                    table: str,
                    id: int) -> list[float]:
        """Return the values in the row uniquely identified by the id
        in the table.

        Args:
            table (_type_): table name in db
            id (_type_): row id

        Returns:
            list[Any]: List of values in the row
        """
        query = select(
            self.tables[table]).where(self.tables[table].c.id == id)
        with self.eng.begin() as conn:
            rslt: list[float] = list(conn.execute(query).fetchall()[0])
        return rslt

    def prepare_batch_select(self,
                             table: str,
                             row_id: int) -> None:
        """Prepare a batch select request to store in the _select dictionary.

        Args:
            table (str): name of the table
            row_id (int): SOP id
        """
        if table not in self._select:
            self._select[table] = []
        self._select[table].append(row_id)

    def batch_select(self) -> list[Row[Any]]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            list[Row[Any]]:
            List of selected rows across requested tables.
        """
        all_db_rslt = []
        for table in self._select:
            row_ids = self._select[table]
            query = select(
                self.tables[table]
                    ).where(
                        self.tables[table].c.id.in_(row_ids))
            with self.eng.begin() as conn:
                db_rslt: Sequence[Row[Any]] = \
                    conn.execute(query).fetchall()
            all_db_rslt.extend(db_rslt)
        self._select = {}  # Clear the _select dictionary after processing
        return all_db_rslt

    def batch_select_to_dict(self) -> dict[str, list[Row[Any]]]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            dict[str, list[Row[Any]]]:
            A dictionary with table names as keys and lists
            of their corresponding rows as values.
        """
        all_db_rslt = {}
        for table in self._select:
            row_ids = self._select[table]
            query = select(
                self.tables[table]
                    ).where(
                        self.tables[table].c.id.in_(row_ids))
            with self.eng.begin() as conn:
                db_rslt: Sequence[Row[Any]] = \
                    conn.execute(query).fetchall()
            all_db_rslt[table] = db_rslt
        self._select = {}  # Clear the _select dictionary after processing
        return all_db_rslt

    def batch_select_cols(self,
                          cols: list[str]) -> list[tuple[Any]]:
        """Execute batch select requests stored in the _select dictionary.

        Returns:
            dict[int, list[list[Any]]]:
            A dictionary with sop_id as keys and lists
            of the corresponding (col) data as values.
        """
        all_db_rslt = []
        for table in self._select:
            row_ids = self._select[table]
            column_references = [self.tables[table].c[col] for col in cols]
            query = select(*column_references).where(
                    ).where(
                        self.tables[table].c.id.in_(row_ids))
            with self.eng.begin() as conn:
                db_rslt: Sequence[Row[Any]] = \
                    conn.execute(query).fetchall()
            all_db_rslt.extend(db_rslt)
        self._select = {}  # Clear the _select dictionary after processing
        return all_db_rslt
