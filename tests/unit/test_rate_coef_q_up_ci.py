from __future__ import annotations

from pathlib import Path

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
