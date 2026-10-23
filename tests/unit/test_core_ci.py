"""CI-safe tests for ``CoreRun`` lifecycle steps, with RateCo / SIM / database
doubles (no MESS, no Slurm):

* the postprocessing rate-reuse branch of ``calculate_rate_coefficients``
  (full grid reused from KIN_DB without parsing stale MESS outputs, partial
  grid submits MESS) and the normal-run parity; ``run_simulation`` KIN -> SIM;
* simulation recovery: ``collect_sim_profiles`` and
  ``recover_simulation_data`` (JSON -> feather, sim_offset banding);
* KIN/SIM table-name routing with origin prefixes.
"""
from __future__ import annotations

from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

import kimeco.core as core_mod
from kimeco.core import CoreRun
from kimeco.database.sim_db import SIM_DB
from kimeco.enums import ModelStatus
from kimeco.q_sys import JobStatus


# ===========================================================================
# Rate reuse branch and run_simulation
# ===========================================================================
class _FakeRateCo:
    """Configurable RateCo stand-in installed via monkeypatch.

    ``recover_raises`` emulates a reused GA project whose on-disk MESS ``.out``
    files sit on a *different* pressure grid: parsing them raises the stale
    "0.5 is not in list" ValueError. The fixed reuse branch must never call
    ``recover_rslts`` so this raise must never surface.
    """

    next_missing_grid: list = []
    next_status: JobStatus = JobStatus.NOT_IN_QUEUE
    recover_raises: bool = False
    last: Any = None

    def __init__(self, **kwargs) -> None:
        self.missing_grid = list(_FakeRateCo.next_missing_grid)
        self.status = _FakeRateCo.next_status
        self.q_up_called = False
        self.recover_called = False
        self.file_read = False
        _FakeRateCo.last = self

    def set_status(self, table: str) -> None:
        return None

    def q_up(self) -> None:
        self.q_up_called = True

    def recover_rslts(self) -> None:
        self.recover_called = True
        self.file_read = True
        if _FakeRateCo.recover_raises:
            raise ValueError('0.5 is not in list')


def _core(postprocess: bool) -> CoreRun:
    core = CoreRun.__new__(CoreRun)
    core.prefix = 'G'
    core.loc = '/tmp'
    core.base_dir = 'base'
    core.settings = {'postprocess': postprocess}
    core.rc_tpls = cast(Any, [])
    core.kin_db = cast(Any, object())
    core.qs = cast(Any, object())
    core.klog = cast(Any, SimpleNamespace(
        debug=lambda *a, **k: None,
        info=lambda *a, **k: None,
        error=lambda *a, **k: None))
    return core


def _mdl(status=ModelStatus.SOP):
    return SimpleNamespace(
        id=0, gen=0, name='E0000', sop=object(),
        status=status, origin_prefix=None)


def _reset_fake():
    _FakeRateCo.next_missing_grid = []
    _FakeRateCo.next_status = JobStatus.NOT_IN_QUEUE
    _FakeRateCo.recover_raises = False
    _FakeRateCo.last = None


def test_pp_full_reuse_sets_kin_and_skips_mess(monkeypatch) -> None:
    """Postprocessing with the full grid already in KIN_DB: SOP -> KIN, MESS is
    not submitted, and the on-disk MESS .out files (possibly on a stale pressure
    grid that would raise "0.5 is not in list") are never parsed; rates are
    rebuilt from KIN_DB at simulation time."""
    _mp_root = monkeypatch
    # -- test_reuse_path_status_sop_to_kin
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(core_mod, 'RateCo', _FakeRateCo)
        _reset_fake()
        core = _core(postprocess=True)
        mdl = _mdl(status=ModelStatus.SOP)

        assert mdl.status == ModelStatus.SOP
        core.calculate_rate_coefficients(cast(Any, mdl))

        assert mdl.status == ModelStatus.KIN
        assert _FakeRateCo.last.q_up_called is False

    # -- test_reuse_branch_does_not_touch_stale_mess_out
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(core_mod, 'RateCo', _FakeRateCo)
        _reset_fake()
        _FakeRateCo.recover_raises = True  # stale .out grid would raise if parsed
        core = _core(postprocess=True)
        mdl = _mdl()

        # Pre-fix code called recover_rslts() and this would raise ValueError.
        core.calculate_rate_coefficients(cast(Any, mdl))

        assert mdl.status == ModelStatus.KIN
        assert _FakeRateCo.last.recover_called is False
        assert _FakeRateCo.last.q_up_called is False

    # -- test_reuse_branch_ignores_grid_mismatch_no_file_reads
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(core_mod, 'RateCo', _FakeRateCo)
        _reset_fake()
        # Branch decides purely on empty missing_grid, independent of grid values
        # or disk state. recover_raises stays True to prove no file access happens.
        _FakeRateCo.recover_raises = True
        core = _core(postprocess=True)
        mdl = _mdl()

        core.calculate_rate_coefficients(cast(Any, mdl))

        assert mdl.status == ModelStatus.KIN
        assert _FakeRateCo.last.recover_called is False
        assert _FakeRateCo.last.file_read is False
        assert _FakeRateCo.last.q_up_called is False


def test_pp_partial_submits_missing_sub_grid(monkeypatch) -> None:
    """Missing cells remain: the reuse shortcut is skipped, MESS is submitted
    and the model stays SOP."""
    _mp_root = monkeypatch
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(core_mod, 'RateCo', _FakeRateCo)
        _reset_fake()
        _FakeRateCo.next_missing_grid = [(1.0, 400.0)]
        _FakeRateCo.next_status = JobStatus.NOT_IN_QUEUE
        core = _core(postprocess=True)
        mdl = _mdl(status=ModelStatus.SOP)

        core.calculate_rate_coefficients(cast(Any, mdl))

        # Missing cells remain -> reuse shortcut skipped, MESS submitted.
        assert mdl.status == ModelStatus.SOP
        assert _FakeRateCo.last.q_up_called is True
        assert _FakeRateCo.last.recover_called is False


def test_normal_full_grid_parity_and_run_simulation(monkeypatch) -> None:
    """A normal run takes no reuse shortcut: FINISHED persists rates via
    save_kin. run_simulation loads the rates from KIN_DB, submits the SIM job
    and moves KIN -> SIM."""
    _mp_root = monkeypatch
    # -- test_normal_full_grid_finished_parity
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(core_mod, 'RateCo', _FakeRateCo)
        _reset_fake()
        _FakeRateCo.next_status = JobStatus.FINISHED
        core = _core(postprocess=False)

        saved: list[str] = []
        mdl = _mdl()
        mdl.save_kin = lambda db, table: saved.append(table)

        core.calculate_rate_coefficients(cast(Any, mdl))

        # Normal run: no reuse shortcut, FINISHED persists rates via save_kin.
        assert saved == ['G0000']
        assert _FakeRateCo.last.q_up_called is False

    # -- test_run_simulation_transitions_kin_to_sim
    with _mp_root.context() as monkeypatch:
        calls: dict[str, Any] = {'load': None, 'q_up': 0}

        class _StubSim:
            def __init__(self, **kwargs) -> None:
                pass

            def q_up(self) -> None:
                calls['q_up'] += 1

        monkeypatch.setattr(core_mod, 'SIM', _StubSim)

        core = _core(postprocess=True)
        core.sim_db = cast(Any, object())

        def _fake_gen_folder(mdl):
            return '/tmp'

        core.get_gen_folder = _fake_gen_folder  # type: ignore[assignment]

        def _load(table: str) -> None:
            calls['load'] = table

        rate_coef = SimpleNamespace(load_rates_from_db=_load)
        mdl = _mdl(status=ModelStatus.KIN)
        mdl.rateCoef = rate_coef

        core.run_simulation(cast(Any, mdl))

        assert calls['load'] == 'G0000'
        assert calls['q_up'] == 1
        assert mdl.status == ModelStatus.SIM


# ===========================================================================
# Simulation recovery
# ===========================================================================
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


def test_collect_sim_profiles_restores_all_experiments_and_marks_scoring(tmp_path) -> None:
    """collect_sim_profiles restores every experiment from SIM_DB, marks the
    model for scoring and maps the banded offset ids back to local experiment
    indices."""
    _tmp_root = tmp_path
    # -- test_collect_sim_profiles_restores_all_experiments_and_marks_scoring
    tmp_path = _tmp_root / 'test_collect_sim_profiles_restores_all_experiments_and_marks_scoring'
    tmp_path.mkdir(parents=True)
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

    # -- test_collect_sim_profiles_maps_offset_back_to_local: Banded DB
    #    experiment_ids map back to local indices via the offset.
    tmp_path = _tmp_root / 'test_collect_sim_profiles_maps_offset_back_to_local'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(
        name='TEST_CORE_SIM_COLLECT_OFF',
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
        _sim_offset=10,
    )
    core.models = cast(Any, [model])

    sim_db.create_new_table(name='G0000')
    sim_db.prepare_batch_upsert(
        table='G0000', mdl_id=7, experiment_id=10,
        result=_blob_from_dict({'time': [0.0, 1.0], 'A': [1.0, 0.8]}))
    sim_db.prepare_batch_upsert(
        table='G0000', mdl_id=7, experiment_id=11,
        result=_blob_from_dict({'time': [0.0, 1.0], 'A': [0.5, 0.2]}))
    sim_db.batch_upsert()
    sim_db.prepare_batch_select(table='G0000', mdl_id=7, experiment_id=10)
    sim_db.prepare_batch_select(table='G0000', mdl_id=7, experiment_id=11)

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


def test_recover_simulation_data_json_to_feather(tmp_path) -> None:
    """recover_simulation_data reads the JSON outputs, stores them as feather
    blobs and applies the sim_offset."""
    _tmp_root = tmp_path
    # -- test_recover_simulation_data_reads_json_and_converts_to_feather: Test
    #    that recovery reads JSON files and transforms them to feather.
    tmp_path = _tmp_root / 'test_recover_simulation_data_reads_json_and_converts_to_feather'
    tmp_path.mkdir(parents=True)
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

    # -- test_recover_simulation_data_applies_sim_offset: Banded models upsert
    #    at experiment_id = sim + _sim_offset.
    tmp_path = _tmp_root / 'test_recover_simulation_data_applies_sim_offset'
    tmp_path.mkdir(parents=True)
    import json

    sim_db = SIM_DB(name='TEST_CORE_SIM_OFF', path=str(tmp_path), threads=1)
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
        _sim_offset=5,
    )

    folder = tmp_path / 'base' / 'G0000' / '00'
    folder.mkdir(parents=True)
    json_file = folder / 'G0000E0007S00.json'
    json_file.write_text(json.dumps({'time': [0.0, 1.0], 'A': [1.0, 0.25]}))

    core.recover_simulation_data(cast(Any, model))

    assert model.status == ModelStatus.SCORING
    # experiment_id is banded by the offset, not the raw sim index.
    assert (7, 5) in sim_db._upsert['G0000']
    assert (7, 0) not in sim_db._upsert.get('G0000', {})


# ===========================================================================
# Table-name routing
# ===========================================================================
class _RouteDB:
    """Minimal stand-in exposing the tables API used by create_tables."""

    def __init__(self) -> None:
        self.tables: dict[str, object] = {}
        self.created: list[str] = []

    def create_new_table(self, name: str) -> None:
        self.tables[name] = object()
        self.created.append(name)


def _route_core(prefix: str = 'G', models: list | None = None) -> CoreRun:
    core = CoreRun.__new__(CoreRun)
    core.prefix = prefix
    core.models = cast(Any, models or [])
    core.sop_db = cast(Any, _RouteDB())
    core.kin_db = cast(Any, _RouteDB())
    core.sim_db = cast(Any, _RouteDB())
    return core


def _route_mdl(gen: int, id: int = 0, origin_prefix=None):
    return SimpleNamespace(gen=gen, id=id, origin_prefix=origin_prefix)


# ---------------------------------------------------------------------------
# get_table_name
# ---------------------------------------------------------------------------
def test_get_table_name() -> None:
    """Normal runs keep <prefix><gen>; a model with an origin prefix uses it;
    never an x/gt table name."""
    # -- test_get_table_name_normal_run_parity
    core = _route_core(prefix='G')

    assert core.get_table_name(_route_mdl(gen=0)) == 'G0000'
    assert core.get_table_name(_route_mdl(gen=2)) == 'G0002'

    # -- test_get_table_name_uses_origin_prefix_when_set
    core = _route_core(prefix='G')

    assert core.get_table_name(
        _route_mdl(gen=3, origin_prefix='NM')) == 'NM0003'
    # origin_prefix='G' is the normal-run value and still routes to G tables.
    assert core.get_table_name(
        _route_mdl(gen=1, origin_prefix='G')) == 'G0001'

    # -- test_get_table_name_never_x_or_gt
    core = _route_core(prefix='G')

    for mdl in (_route_mdl(gen=0), _route_mdl(gen=1, origin_prefix='NM')):
        name = core.get_table_name(mdl)
        assert not name.startswith('X')
        assert not name.startswith('GT')


# ---------------------------------------------------------------------------
# create_tables
# ---------------------------------------------------------------------------
def test_create_tables() -> None:
    """Models with mixed origin prefixes get distinct tables; a normal run
    creates the usual ones, never x/gt."""
    # -- test_create_tables_mixed_prefix_creates_distinct_tables
    models = [
        _route_mdl(gen=0, id=0, origin_prefix=None),   # G0000
        _route_mdl(gen=0, id=1, origin_prefix='NM'),   # NM0000
        _route_mdl(gen=1, id=2, origin_prefix=None),   # G0001
    ]
    core = _route_core(prefix='G', models=models)

    core.create_tables()

    expected = {'G0000', 'NM0000', 'G0001'}
    assert set(core.sop_db.created) == expected
    assert set(core.kin_db.created) == expected
    assert set(core.sim_db.created) == expected

    # -- test_create_tables_normal_run_parity_no_x_or_gt
    models = [_route_mdl(gen=0, id=0), _route_mdl(gen=1, id=1)]
    core = _route_core(prefix='G', models=models)

    core.create_tables()

    assert set(core.sop_db.created) == {'G0000', 'G0001'}
    assert not any(
        name.startswith(('X', 'GT')) for name in core.sop_db.created)



# ===========================================================================
# CoreRun.__init__ and the NelderMead swarm runner (NMSRunner)
# ===========================================================================
import os  # noqa: E402
import threading  # noqa: E402

from kimeco.optimizers.NelderMead.nm_swarm_runner import NMSRunner  # noqa: E402

_QS_SETTINGS: dict[str, Any] = {
    'max_jobs': 4, 'max_cpu': 4, 'max_mem': 4000, 'cpu_kin': 1, 'cpu_sim': 1,
    'mem_kin': 500, 'mem_sim': 500, 'n_exp': 2, 'exclude_nodes': [],
    'q_name': 'test-queue', 'threads': 3,
}


class _TableDB(_RouteDB):
    """Tables API plus the batch hooks NMSRunner calls after each step."""

    def __init__(self) -> None:
        super().__init__()
        self._select: dict = {}
        self.upserts = 0

    def batch_upsert(self) -> None:
        self.upserts += 1


def _quiet_log() -> Any:
    return SimpleNamespace(debug=lambda *a, **k: None, info=lambda *a, **k: None,
                           warning=lambda *a, **k: None, error=lambda *a, **k: None)


def _core_mdl(gen: int, id: int, status=ModelStatus.SOP, origin_prefix=None,
              files=('a.inp', 'missing.inp')) -> Any:
    return SimpleNamespace(gen=gen, id=id, status=status, name=f'E{id:04d}',
                           origin_prefix=origin_prefix,
                           sop=SimpleNamespace(files2copy=list(files)))


def test_core_run_init_builds_tables_folders_links_and_chdirs(
        tmp_path: Path, monkeypatch) -> None:
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    (tmp_path / 'a.inp').write_text('x')
    (cwd / 'G0001E0000.log').write_text('stale')
    (cwd / 'G0001E0051.log').write_text('done')
    models = [_core_mdl(1, 0), _core_mdl(1, 51, status=ModelStatus.DONE),
              _core_mdl(0, 2, origin_prefix='NM')]
    dbs = [_TableDB(), _TableDB(), _TableDB()]
    settings = dict(_QS_SETTINGS, workdir=str(tmp_path))
    core = CoreRun(models=cast(Any, models), settings=settings, rc_tpls=[],
                   sop_db=cast(Any, dbs[0]), kin_db=cast(Any, dbs[1]),
                   sim_db=cast(Any, dbs[2]), sf=cast(Any, None), pert=None,
                   klog=_quiet_log(), base_dir='base', prefix='G')

    for db in dbs:
        assert set(db.created) == {'G0001', 'NM0000'}
    assert core.qs.kin_q.shape == (3,)
    assert not (cwd / 'G0001E0000.log').exists()
    assert (cwd / 'G0001E0051.log').exists()
    base = tmp_path / 'base'
    for sub in ('G0001/logs', 'G0001/00/logs', 'G0001/01/logs', 'NM0000/00/logs'):
        assert (base / sub).is_dir(), sub
    for sub in ('G0001/00', 'G0001/01', 'NM0000/00'):
        assert (base / sub / 'a.inp').is_symlink(), sub
        assert not (base / sub / 'missing.inp').exists(), sub
    assert set(core.mdl_locks) == {('G0001', 0), ('G0001', 51), ('NM0000', 2)}
    assert Path(os.getcwd()) == base

    # No model (the NMSRunner path): only the base folder, no lock.
    empty = tmp_path / 'empty'
    empty.mkdir()
    core = CoreRun(models=[], settings=dict(settings, workdir=str(empty)), rc_tpls=[],
                   sop_db=cast(Any, _TableDB()), kin_db=cast(Any, _TableDB()),
                   sim_db=cast(Any, _TableDB()), sf=cast(Any, None), pert=None,
                   klog=_quiet_log(), base_dir='base', prefix='G')
    assert [p.name for p in empty.iterdir()] == ['base']
    assert list((empty / 'base').iterdir()) == []
    assert core.mdl_locks == {}
    assert Path(os.getcwd()) == empty / 'base'


def _nms_runner(tmp_path: Path, monkeypatch, sim_db: Any,
                experiments: list | None = None) -> NMSRunner:
    monkeypatch.chdir(tmp_path)
    settings = dict(_QS_SETTINGS, workdir=str(tmp_path),
                    experiments=experiments or [])
    return NMSRunner(settings=settings, rc_tpls=[], sop_db=cast(Any, _TableDB()),
                     kin_db=cast(Any, _TableDB()), sim_db=cast(Any, sim_db),
                     sf=cast(Any, None), klog=_quiet_log())


def _nms_mdl(gen: int, id: int, nexp: int = 2, offset: int = 0) -> Any:
    return SimpleNamespace(gen=gen, id=id, status=ModelStatus.SIM, origin_prefix=None,
                           _sim_offset=offset, sim=SimpleNamespace(profiles=[None] * nexp))


def _nms_sim_db(tmp_path: Path, name: str, rows: dict[str, list[tuple]]) -> SIM_DB:
    sim_db = SIM_DB(name=name, path=str(tmp_path), threads=1)
    for table, entries in rows.items():
        sim_db.create_new_table(name=table)
        for mdl_id, exp_id, data in entries:
            sim_db.prepare_batch_upsert(table=table, mdl_id=mdl_id, experiment_id=exp_id,
                                        result=_blob_from_dict(data))
    sim_db.batch_upsert()
    for table, entries in rows.items():
        for mdl_id, exp_id, _ in entries:
            sim_db.prepare_batch_select(table=table, mdl_id=mdl_id, experiment_id=exp_id)
    return sim_db


_EXPS = [SimpleNamespace(data=np.array([[0.0, 1.0]], dtype=float)),
         SimpleNamespace(data=np.array([[0.0, 1.0]], dtype=float))]
_FULL_A = {'time': [0.0, 1.0], 'A': [1.0, 0.8]}
_FULL_B = {'time': [0.0, 1.0], 'A': [0.5, 0.2]}


def test_nms_collect_sim_profiles_maps_nmsg_tables_and_offsets(
        tmp_path: Path, monkeypatch) -> None:
    sim_db = _nms_sim_db(tmp_path, 'TEST_NMS_COLLECT', {
        'NMSG0000': [(3, 0, _FULL_A), (3, 1, _FULL_B)],
        'NMSG0001': [(4, 10, _FULL_B), (4, 11, _FULL_A)],
    })
    runner = _nms_runner(tmp_path, monkeypatch, sim_db, _EXPS)
    assert 'exp_profiles' not in runner.settings
    m_a, m_b = _nms_mdl(0, 3), _nms_mdl(1, 4, offset=10)
    runner.models = cast(Any, [m_a, None, m_b])

    runner.collect_sim_profiles()

    assert m_a.status == ModelStatus.SCORING
    # Same decoded layout as the base CoreRun.collect_sim_profiles test.
    assert m_a.sim.profiles[0].tolist() == [[0.0, 1.0], [1.0, 0.8]]
    assert m_a.sim.profiles[1].tolist() == [[0.0, 1.0], [0.5, 0.2]]
    assert m_b.status == ModelStatus.SCORING
    assert m_b.sim.profiles[0].tolist() == [[0.0, 1.0], [0.5, 0.2]]
    assert m_b.sim.profiles[1].tolist() == [[0.0, 1.0], [1.0, 0.8]]


def test_nms_collect_sim_profiles_skips_unmatched_and_incomplete(
        tmp_path: Path, monkeypatch) -> None:
    sim_db = _nms_sim_db(tmp_path, 'TEST_NMS_SKIP', {
        'G0000': [(3, 0, _FULL_A), (3, 1, _FULL_B)],         # other prefix
        'NMSG0005': [(9, 0, _FULL_A)],                        # not pooled
        'NMSG0000': [(3, 1, {'time': [0.0], 'A': [1.0]})],    # wrong nsteps
    })
    runner = _nms_runner(tmp_path, monkeypatch, sim_db, _EXPS)
    m_a = _nms_mdl(0, 3)
    runner.models = cast(Any, [None, m_a, None])

    runner.collect_sim_profiles()

    assert m_a.sim.profiles == [None, None]
    assert m_a.status == ModelStatus.SIM
    assert sim_db._select == {}

    # Nothing selected: early return, nothing changes.
    m_a.sim.profiles = ['kept', None]
    runner.collect_sim_profiles()
    assert m_a.sim.profiles == ['kept', None]
    assert m_a.status == ModelStatus.SIM


def test_nms_run_registers_and_releases_table_id_lock(
        tmp_path: Path, monkeypatch) -> None:
    runner = _nms_runner(tmp_path, monkeypatch, _TableDB())
    assert not hasattr(runner, 'el_locks')
    runner.qs = cast(Any, SimpleNamespace(run=lambda: None))
    calls: list[tuple[str, int, int]] = []

    def _calc(mdl: Any) -> None:
        calls.append(('calc_score', mdl.gen, mdl.id))
        mdl.status = ModelStatus.TO_SAVE

    def _final(mdl: Any) -> None:
        calls.append(('finalize_model', mdl.gen, mdl.id))
        mdl.status = ModelStatus.DONE

    runner.calc_score = _calc
    runner.finalize_model = _final

    def _mdl(gen: int, id: int) -> Any:
        return SimpleNamespace(id=id, gen=gen, status=ModelStatus.SCORING,
                               origin_prefix=None, sop=SimpleNamespace(files2copy=[]))

    mdl = _mdl(0, 4)
    assert runner.run(cast(Any, mdl)) is mdl
    assert mdl.status == ModelStatus.DONE
    assert calls == [('calc_score', 0, 4), ('finalize_model', 0, 4)]
    assert ('NMSG0000', 4) in runner.mdl_locks
    assert not runner.mdl_locks[('NMSG0000', 4)].locked()
    assert runner.models == [None, None, None]

    runner.run(cast(Any, _mdl(1, 4)))
    assert {('NMSG0000', 4), ('NMSG0001', 4)} <= set(runner.mdl_locks)

    # Lock held elsewhere: the step is skipped without processing.
    held = _mdl(2, 5)
    runner.mdl_locks[('NMSG0002', 5)] = threading.Lock()
    runner.mdl_locks[('NMSG0002', 5)].acquire()
    calls.clear()
    runner._process_single_model(cast(Any, held))
    assert calls == [] and held.status == ModelStatus.SCORING
    runner.mdl_locks[('NMSG0002', 5)].release()
