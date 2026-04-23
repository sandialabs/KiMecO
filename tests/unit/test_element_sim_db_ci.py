from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from kimeco.element import Element
from kimeco.enums import ElementStatus
from kimeco.database.sim_db import SIM_DB


class DummySIMDB:
    def __init__(self) -> None:
        self.requests: list[tuple[str, int, int]] = []

    def prepare_batch_select(
        self,
        table: str,
        model_id: int,
        experiment_id: int,
    ) -> None:
        self.requests.append((table, model_id, experiment_id))


def _element() -> Element:
    sop = SimpleNamespace(pres=[1.0], temp=[300.0])
    return Element(sop=sop, id=7, status=ElementStatus.SOP.value)


def test_request_sim_profiles_only_queues_missing_experiments() -> None:
    el = _element()
    el.sim = SimpleNamespace(profiles=[None, object(), None])
    db = DummySIMDB()

    el.request_sim_profiles(sim_db=db, table='G0000')

    assert db.requests == [('G0000', 7, 0), ('G0000', 7, 2)]


def test_save_sim_persists_blob_roundtrip_for_one_experiment(
    tmp_path: Path,
) -> None:
    el = _element()
    db = SIM_DB(name='TEST_ELEMENT_SIM_DB', path=str(tmp_path), threads=1)
    exp = SimpleNamespace(
        species=['A', 'B'],
        data=np.array([[0.0, 1.0, 2.0]], dtype=float),
    )
    el.sim = SimpleNamespace(
        settings={'experiments': [exp]},
        profiles=[
            np.array(
                [
                    [0.0, 1.0, 2.0],
                    [1.0, 0.5, 0.25],
                    [0.0, 0.2, 0.4],
                ],
                dtype=float,
            )
        ],
    )

    el.save_sim(db=db, table='G0000', sim_num=0)
    db.batch_upsert()
    db.prepare_batch_select(table='G0000', model_id=7, experiment_id=0)

    rows = db.batch_select()['G0000'][7][0]

    assert rows[:, 0].tolist() == [7.0, 7.0, 7.0]
    assert rows[:, 1].tolist() == [0.0, 1.0, 2.0]
    assert rows[:, 2].tolist() == [1.0, 0.5, 0.25]
    assert rows[:, 3].tolist() == [0.0, 0.2, 0.4]


def test_save_sim_raises_for_missing_profile(tmp_path: Path) -> None:
    el = _element()
    db = SIM_DB(name='TEST_ELEMENT_SIM_DB_MISSING', path=str(tmp_path))
    exp = SimpleNamespace(
        species=['A'],
        data=np.array([[0.0, 1.0]], dtype=float),
    )
    el.sim = SimpleNamespace(
        settings={'experiments': [exp]},
        profiles=[None],
    )

    with pytest.raises(ValueError, match='Missing simulation profile 0'):
        el.save_sim(db=db, table='G0000', sim_num=0)
