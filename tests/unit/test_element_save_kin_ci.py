from __future__ import annotations

from types import SimpleNamespace

from kimeco.element import Element
from kimeco.enums import ElementStatus
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


def _element() -> Element:
    sop = SimpleNamespace(pres=[1.0], temp=[300.0])
    return Element(sop=sop, id=0, status=ElementStatus.SOP.value)


def test_save_kin_waits_when_rows_empty_and_job_not_failed() -> None:
    el = _element()
    db = DummyKINDB()
    el.rateCoef = DummyRateCo(rows=[], status=JobStatus.NOT_IN_QUEUE)

    el.save_kin(db=db, table="G0000")

    assert el.status == ElementStatus.SOP
    assert db.upserts == []


def test_save_kin_resets_when_rows_empty_and_job_failed() -> None:
    el = _element()
    db = DummyKINDB()
    el.rateCoef = DummyRateCo(rows=[], status=JobStatus.FAILED)

    el.save_kin(db=db, table="G0000")

    assert el.status == ElementStatus.RESET
    assert db.upserts == []


def test_save_kin_sets_kin_and_writes_rows_when_results_present() -> None:
    el = _element()
    db = DummyKINDB()
    el.rateCoef = DummyRateCo(rows=[(10, 1.0, 300.0)], status=JobStatus.FINISHED)

    el.save_kin(db=db, table="G0000")

    assert el.status == ElementStatus.KIN
    assert len(db.upserts) == 1
    table, row_id, values = db.upserts[0]
    assert table == "G0000"
    assert row_id == 10
    assert values == {"pres": 1.0, "temp": 300.0}
