from __future__ import annotations

from pathlib import Path
import re

import numpy as np

import pytest

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus
from kimeco.rate_coef import RateCo


class DummySOP:
    def __init__(self) -> None:
        self.pes_ids = [0, 1, 2]

    def reaction_iterator(self):
        return iter([])


class DummyDB:
    def get_ids_from_kin_id(self, table: str, kin_id: int):
        return []


class DummyQueue:
    def __init__(self) -> None:
        self.calls = []

    def add_to_q(self, **kwargs) -> None:
        self.calls.append(kwargs)


class DummyRecoverQueue:
    def __init__(self) -> None:
        self._status = JobStatus.PICKED_UP

    def pickUp(self, id: int, jtype: str) -> None:
        return None

    def status(self, id: int, jtype: str) -> JobStatus:
        return self._status


class DummyRecoverSOP:
    def __init__(self) -> None:
        self.pes_ids = [2, 5]

    def reaction_iterator(self):
        return iter([
            (2, "A", "B"),
            (5, "A", "B"),
        ])


class FakeMessOutputReader:
    def __init__(self, filename: str, settings: dict, sop, klog) -> None:
        self.filename = filename
        self.tbl_map = {"A": 0, "B": 1}
        self.rc = np.zeros((1, 1, 2, 2), dtype=float)

    def read(self) -> None:
        filename = Path(self.filename).name
        match = re.search(r"P(\d{2})\.out$", filename)
        assert match is not None
        output_slot = int(match.group(1))
        # Distinct values to validate slot -> PES mapping.
        if output_slot == 0:
            self.rc[0, 0, 0, 1] = 2.0
        elif output_slot == 1:
            self.rc[0, 0, 0, 1] = 5.0


@pytest.fixture
def rateco(tmp_path: Path) -> RateCo:
    settings = {
        "rc_software": "mess",
        "postprocess": False,
        "rc_pres": [1.0],
        "rc_temp": [300.0],
        "cpu_kin": 2,
        "mem_kin": 500,
    }
    return RateCo(
        sop=DummySOP(),
        settings=settings,
        software_tpls=[["tpl0"], ["tpl1"], ["tpl2"]],
        id=0,
        q_idx=7,
        name="G0000E0001",
        loc=str(tmp_path),
        q_sys=DummyQueue(),
        db=DummyDB(),
        klog=KMOLogger(filename=str(tmp_path / "rateco.log")),
    )


def test_q_up_passes_n_pes_to_queue(rateco: RateCo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rateco, "create_input", lambda: None)
    rateco.status = JobStatus.NOT_IN_QUEUE

    rateco.q_up()

    assert len(rateco.q_sys.calls) == 1
    call = rateco.q_sys.calls[0]
    assert call["n_pes"] == 3
    assert call["jtype"] == "kin"
    assert call["name"] == "G0000E0001"


def test_recover_results_maps_output_slot_to_real_pes_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = {
        "rc_software": "mess",
        "postprocess": False,
        "rc_pres": [1.0],
        "rc_temp": [300.0],
        "cpu_kin": 2,
        "mem_kin": 500,
    }
    rateco = RateCo(
        sop=DummyRecoverSOP(),
        settings=settings,
        software_tpls=[["tpl0"], ["tpl1"]],
        id=0,
        q_idx=3,
        name="G0000E0001",
        loc=str(tmp_path),
        q_sys=DummyRecoverQueue(),
        db=DummyDB(),
        klog=KMOLogger(filename=str(tmp_path / "recover.log")),
    )
    monkeypatch.setattr("kimeco.rate_coef.MessOutputReader", FakeMessOutputReader)

    Path(rateco.loc).mkdir(parents=True, exist_ok=True)
    for output_name in rateco.output_names:
        Path(output_name).write_text("ok")

    rows = rateco.recover_rslts()

    assert len(rows) == 2
    k_by_pes = {row[4]: row[7] for row in rows}
    assert k_by_pes[2] == 2.0
    assert k_by_pes[5] == 5.0
