from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from kimeco.database.kin_db import KIN_DB


class DummySOP:
    def __init__(self) -> None:
        self.pes_ids = [0, 1]


def test_batch_select_keeps_unfiltered_rows_when_filtered_request_exists(
    tmp_path: Path,
) -> None:
    kin_db = KIN_DB(
        sop=cast(Any, DummySOP()),
        name="TEST_DB_KIN",
        path=str(tmp_path),
        threads=1,
    )
    table = "G0000"
    kin_db.create_new_table(name=table)

    kin_db.prepare_batch_upsert(
        table=table,
        id=0,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 1.0,
        },
    )
    kin_db.prepare_batch_upsert(
        table=table,
        id=1,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 1,
            "from_name": "A",
            "to_name": "B",
            "k": 2.0,
        },
    )
    kin_db.batch_upsert()

    # Mixed request set: one unfiltered and one filtered on pes_id=1.
    kin_db.prepare_batch_select(
        table=table,
        kin_id=1,
        p=1.0,
        t=300.0,
        from_name="A",
        to_name="B",
    )
    kin_db.prepare_batch_select(
        table=table,
        kin_id=1,
        p=1.0,
        t=300.0,
        from_name="A",
        to_name="B",
        pes_id=1,
    )

    results = kin_db.batch_select()

    kin_results = results[table][1]
    assert (1.0, 300.0, 0, "A", "B") in kin_results
    assert (1.0, 300.0, 1, "A", "B") in kin_results
    assert kin_results[(1.0, 300.0, 0, "A", "B")] == 1.0
    assert kin_results[(1.0, 300.0, 1, "A", "B")] == 2.0


def test_get_rates_for_kin_id_respects_pes_filter(tmp_path: Path) -> None:
    kin_db = KIN_DB(
        sop=cast(Any, DummySOP()),
        name="TEST_DB_KIN_FILTER",
        path=str(tmp_path),
        threads=1,
    )
    table = "G0000"
    kin_db.create_new_table(name=table)

    kin_db.prepare_batch_upsert(
        table=table,
        id=0,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 2,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 1.5,
        },
    )
    kin_db.prepare_batch_upsert(
        table=table,
        id=1,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 2,
            "pes_id": 1,
            "from_name": "A",
            "to_name": "B",
            "k": 2.5,
        },
    )
    kin_db.batch_upsert()

    all_rows = kin_db.get_rates_for_kin_id(table=table, kin_id=2)
    pes1_rows = kin_db.get_rates_for_kin_id(table=table, kin_id=2, pes_id=1)

    assert len(all_rows) == 2
    assert len(pes1_rows) == 1
    assert pes1_rows[0][2] == 1
    assert pes1_rows[0][-1] == 2.5


def test_get_rates_for_models_filters_by_table_ids_and_conditions(
    tmp_path: Path,
) -> None:
    kin_db = KIN_DB(
        sop=cast(Any, DummySOP()),
        name="TEST_DB_KIN_MULTI",
        path=str(tmp_path),
        threads=1,
    )
    g0 = "G0000"
    g1 = "G0001"
    kin_db.create_new_table(name=g0)
    kin_db.create_new_table(name=g1)

    kin_db.prepare_batch_upsert(
        table=g0,
        id=0,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 1.2,
        },
    )
    kin_db.prepare_batch_upsert(
        table=g0,
        id=1,
        values={
            "P": 10.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 9.9,
        },
    )
    kin_db.prepare_batch_upsert(
        table=g1,
        id=2,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 3,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 2.4,
        },
    )
    kin_db.batch_upsert()

    rows = kin_db.get_rates_for_models(
        table_to_kin_ids={g0: [1], g1: [3]},
        pres=[1.0],
        temp=[300.0],
        pes_ids=[0],
    )

    assert len(rows) == 2
    assert (g0, 1, 1.0, 300.0, 0, "A", "B", 1.2) in rows
    assert (g1, 3, 1.0, 300.0, 0, "A", "B", 2.4) in rows
