from __future__ import annotations

from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

from kimeco.core import CoreRun
from kimeco.database.sim_db import SIM_DB
from kimeco.enums import ModelStatus
from kimeco.q_sys import JobStatus


def _blob_from_dict(data: dict[str, list[float]]) -> bytes:
    table = pa.table(data)
    sink = pa.BufferOutputStream()
    feather.write_feather(table, sink)
    return sink.getvalue().to_pybytes()


def _core_stub(tmp_path: Path, sim_db: SIM_DB, experiments: list) -> CoreRun:
    core = CoreRun.__new__(CoreRun)
    core.prefix = 'G'
    core.loc = str(tmp_path)
    core.base_dir = 'base'
    core.settings = {
        'experiments': experiments,
        'n_exp': len(experiments),
    }
    core.sim_db = sim_db
    core.models = []
    core.requeue_lock = Lock()
    core.requeue_timer = {}
    core.qs_lock = Lock()
    core.qs = cast(Any, SimpleNamespace(pickUp=lambda id, jtype: None))
    core.klog = cast(Any, SimpleNamespace(info=lambda msg: None))
    return core


class DummySim:
    def __init__(self, profiles, status: JobStatus) -> None:
        self.profiles = profiles
        self.status = status
        self.q_idx = 0
        self.q_up_calls = 0

    def set_status(self) -> None:
        return None

    def q_up(self) -> None:
        self.q_up_calls += 1


def test_collect_sim_profiles_restores_all_experiments_and_marks_scoring(
    tmp_path: Path,
) -> None:
    sim_db = SIM_DB(
        name='TEST_CORE_SIM_COLLECT',
        path=str(tmp_path),
        threads=1,
    )
    experiments = [
        SimpleNamespace(data=np.array([[0.0, 1.0]], dtype=float)),
        SimpleNamespace(data=np.array([[0.0, 1.0]], dtype=float)),
    ]
    core = _core_stub(
        tmp_path=tmp_path,
        sim_db=sim_db,
        experiments=experiments,
    )
    model = SimpleNamespace(
        id=7,
        gen=0,
        sim=SimpleNamespace(profiles=[None, None]),
        status=ModelStatus.SIM,
    )
    core.models = cast(Any, [model])

    sim_db.create_new_table(name='G0000')
    sim_db.prepare_batch_upsert(
        table='G0000',
        mdl_id=7,
        experiment_id=0,
        result=_blob_from_dict({'time': [0.0, 1.0], 'A': [1.0, 0.8]}),
    )
    sim_db.prepare_batch_upsert(
        table='G0000',
        mdl_id=7,
        experiment_id=1,
        result=_blob_from_dict({'time': [0.0, 1.0], 'A': [0.5, 0.2]}),
    )
    sim_db.batch_upsert()
    sim_db.prepare_batch_select(table='G0000', mdl_id=7, experiment_id=0)
    sim_db.prepare_batch_select(table='G0000', mdl_id=7, experiment_id=1)

    core.collect_sim_profiles()

    assert model.status == ModelStatus.SCORING
    assert model.sim.profiles[0].tolist() == [[0.0, 1.0], [1.0, 0.8]]
    assert model.sim.profiles[1].tolist() == [[0.0, 1.0], [0.5, 0.2]]


def test_collect_sim_profiles_skips_wrong_timestep_count(
    tmp_path: Path,
) -> None:
    sim_db = SIM_DB(name='TEST_CORE_SIM_SKIP', path=str(tmp_path), threads=1)
    experiments = [
        SimpleNamespace(data=np.array([[0.0, 1.0]], dtype=float)),
    ]
    core = _core_stub(
        tmp_path=tmp_path,
        sim_db=sim_db,
        experiments=experiments,
    )
    model = SimpleNamespace(
        id=7,
        gen=0,
        sim=SimpleNamespace(profiles=[None]),
        status=ModelStatus.SIM,
    )
    core.models = cast(Any, [model])

    sim_db.create_new_table(name='G0000')
    sim_db.prepare_batch_upsert(
        table='G0000',
        mdl_id=7,
        experiment_id=0,
        result=_blob_from_dict({'time': [0.0], 'A': [1.0]}),
    )
    sim_db.batch_upsert()
    sim_db.prepare_batch_select(table='G0000', mdl_id=7, experiment_id=0)

    core.collect_sim_profiles()

    assert model.status == ModelStatus.SIM
    assert model.sim.profiles == [None]


def test_recover_simulation_data_reads_json_and_converts_to_feather(
    tmp_path: Path,
) -> None:
    """Test that recovery reads JSON files and transforms them to feather."""
    import json

    sim_db = SIM_DB(name='TEST_CORE_SIM_FILE', path=str(tmp_path), threads=1)
    experiments = [
        SimpleNamespace(data=np.array([[0.0, 1.0]], dtype=float)),
    ]
    core = _core_stub(
        tmp_path=tmp_path,
        sim_db=sim_db,
        experiments=experiments,
    )
    model = SimpleNamespace(
        id=7,
        gen=0,
        name='E0007',
        sim=DummySim(profiles=[None], status=JobStatus.PICKED_UP),
        status=ModelStatus.SIM,
    )

    # Create JSON file (simulation output format)
    folder = tmp_path / 'base' / 'G0000' / '00'
    folder.mkdir(parents=True)
    json_file = folder / 'G0000E0007S00.json'
    data = {'time': [0.0, 1.0], 'A': [1.0, 0.25]}
    json_file.write_text(json.dumps(data))

    core.recover_simulation_data(cast(Any, model))

    # Verify JSON file is deleted after recovery
    assert not json_file.exists()
    assert model.status == ModelStatus.SCORING
    assert model.sim.profiles[0].tolist() == [[0.0, 1.0], [1.0, 0.25]]

    # Verify feather blob is stored in database
    expected_blob = _blob_from_dict({'time': [0.0, 1.0], 'A': [1.0, 0.25]})
    assert sim_db._upsert['G0000'][(7, 0)] == expected_blob
