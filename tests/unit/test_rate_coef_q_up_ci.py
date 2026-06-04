from __future__ import annotations

from pathlib import Path
import re
from typing import Any, cast

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


class DummyDBMissingTable:
    def get_ids_from_kin_id(self, table: str, kin_id: int):
        raise KeyError(table)


class DummyQueue:
    def __init__(self) -> None:
        self.calls = []

    def add_to_q(self, **kwargs) -> None:
        self.calls.append(kwargs)


class DummyStatusQueue(DummyQueue):
    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.NOT_IN_QUEUE


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


class DummyRotorForInput:
    def __init__(self) -> None:
        self._sym = 2.0
        self.iem = 4000.0
        self.file = "dummy_pes.dat"
        self.qlem = 1500.0

    @property
    def symFact(self) -> float:
        return self._sym


class DummyWellForInput:
    def __init__(self) -> None:
        self.m_rotors = [DummyRotorForInput()]


class DummySOPForInput:
    def __init__(self) -> None:
        self.pes_ids = [0]
        self.parameters_names: dict[str, str] = {}
        self.items = {"WELL": DummyWellForInput()}

    def reaction_iterator(self):
        return iter([])


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
        sop=cast(Any, DummySOP()),
        settings=settings,
        software_tpls=[["tpl0"], ["tpl1"], ["tpl2"]],
        id=0,
        q_idx=7,
        name="G0000E0001",
        loc=str(tmp_path),
        q_sys=cast(Any, DummyQueue()),
        db=cast(Any, DummyDB()),
        klog=KMOLogger(filename=str(tmp_path / "rateco.log")),
    )


def test_q_up_passes_n_pes_to_queue(
    rateco: RateCo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rateco, "create_input", lambda: None)
    rateco.status = JobStatus.NOT_IN_QUEUE

    rateco.q_up()

    assert len(cast(Any, rateco.q_sys).calls) == 1
    call = cast(Any, rateco.q_sys).calls[0]
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
        sop=cast(Any, DummyRecoverSOP()),
        settings=settings,
        software_tpls=[["tpl0"], ["tpl1"]],
        id=0,
        q_idx=3,
        name="G0000E0001",
        loc=str(tmp_path),
        q_sys=cast(Any, DummyRecoverQueue()),
        db=cast(Any, DummyDB()),
        klog=KMOLogger(filename=str(tmp_path / "recover.log")),
    )
    monkeypatch.setattr(
        "kimeco.rate_coef.MessOutputReader",
        FakeMessOutputReader,
    )

    Path(rateco.loc).mkdir(parents=True, exist_ok=True)
    for output_name in rateco.output_names:
        Path(output_name).write_text("ok")

    rows = rateco.recover_rslts()

    assert len(rows) == 2
    k_by_pes = {row[4]: row[7] for row in rows}
    assert k_by_pes[2] == 2.0
    assert k_by_pes[5] == 5.0


def test_set_status_surfaces_missing_generation_table_keyerror(
    tmp_path: Path,
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
        sop=cast(Any, DummySOP()),
        settings=settings,
        software_tpls=[["tpl0"], ["tpl1"], ["tpl2"]],
        id=0,
        q_idx=1,
        name="G0000E0000",
        loc=str(tmp_path),
        q_sys=cast(Any, DummyStatusQueue()),
        db=cast(Any, DummyDBMissingTable()),
        klog=KMOLogger(filename=str(tmp_path / "missing_table.log")),
    )

    Path(rateco.loc).mkdir(parents=True, exist_ok=True)
    for output_name in rateco.output_names:
        Path(output_name).write_text("ok")

    with pytest.raises(KeyError) as exc:
        rateco.set_status(table="G0000")

    assert exc.value.args == ("G0000",)


def test_create_input_resolves_indexed_multirotor_placeholder(
    tmp_path: Path,
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
        sop=cast(Any, DummySOPForInput()),
        settings=settings,
        software_tpls=[[
            "Core MultiRotor\n",
            "SymmetryFactor {WELL.m_rotors[0].symFact}\n",
            "InterpolationEnergyMax {WELL.m_rotors[0].iem}\n",
            "PotentialEnergySurface {WELL.m_rotors[0].file}\n",
            "QuantumLevelEnergyMax {WELL.m_rotors[0].qlem}\n",
            "End\n",
        ]],
        id=0,
        q_idx=1,
        name="G0000E0000",
        loc=str(tmp_path),
        q_sys=cast(Any, DummyQueue()),
        db=cast(Any, DummyDB()),
        klog=KMOLogger(filename=str(tmp_path / "create_input.log")),
    )

    Path(rateco.loc).mkdir(parents=True, exist_ok=True)
    rateco.create_input()

    generated = Path(rateco.loc) / "G0000E0000P00.inp"
    assert generated.exists()
    content = generated.read_text()
    assert "SymmetryFactor 2.0" in content
    assert "InterpolationEnergyMax 4000.0" in content
    assert "PotentialEnergySurface dummy_pes.dat" in content
    assert "QuantumLevelEnergyMax 1500.0" in content
    assert "{" not in content
    assert "}" not in content
