from __future__ import annotations

from pathlib import Path

from kimeco.database.kin_db import KIN_DB


class DummySOP:
    def __init__(self) -> None:
        self.pes_ids = [0, 1]


def test_batch_select_keeps_unfiltered_rows_when_filtered_request_exists(
    tmp_path: Path,
) -> None:
    kin_db = KIN_DB(
        sop=DummySOP(),
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
