from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from kimeco.model import Model
from kimeco.enums import ModelStatus
from kimeco.q_sys import JobStatus


class DummyKINDB:
    def __init__(self) -> None:
        self.columns = ["pres", "temp"]
        self.upserts = []

    def prepare_batch_upsert(self, table: str, id: int, values: dict) -> None:
        self.upserts.append((table, id, values))


class DummyRateCo:
    def __init__(self, rows, status: JobStatus) -> None:
        self._rows = rows
        self.status = status

    def recover_rslts(self):
        return self._rows


def _model() -> Model:
    sop = SimpleNamespace(pres=[1.0], temp=[300.0])
    return Model(sop=cast(Any, sop), id=0, status=ModelStatus.SOP.value)


def test_save_kin_waits_when_rows_empty_and_job_not_failed() -> None:
    mdl = _model()
    db = DummyKINDB()
    mdl.rateCoef = cast(Any, DummyRateCo(rows=[], status=JobStatus.NOT_IN_QUEUE))

    mdl.save_kin(db=cast(Any, db), table="G0000")

    assert mdl.status == ModelStatus.SOP
    assert db.upserts == []


def test_save_kin_resets_when_rows_empty_and_job_failed() -> None:
    mdl = _model()
    db = DummyKINDB()
    mdl.rateCoef = cast(Any, DummyRateCo(rows=[], status=JobStatus.FAILED))

    mdl.save_kin(db=cast(Any, db), table="G0000")

    assert mdl.status == ModelStatus.RESET
    assert db.upserts == []


def test_save_kin_sets_kin_and_writes_rows_when_results_present() -> None:
    mdl = _model()
    db = DummyKINDB()
    mdl.rateCoef = cast(Any, DummyRateCo(rows=[(10, 1.0, 300.0)], status=JobStatus.FINISHED))

    mdl.save_kin(db=cast(Any, db), table="G0000")

    assert mdl.status == ModelStatus.KIN
    assert len(db.upserts) == 1
    table, row_id, values = db.upserts[0]
    assert table == "G0000"
    assert row_id == 10
    assert values == {"pres": 1.0, "temp": 300.0}
