"""CI-safe tests for ``RateCo`` (rate-coefficient job of one model), with
fake SOP, KIN_DB, queue and MESS output reader doubles.

* P/T reuse: ``is_in_db`` and the missing sub-grid, ``set_status``,
  ``create_input`` writing only the missing sub-grid in postprocessing (full
  grid otherwise, absent ``use_automech`` byte-identical to ``False``), and
  ``recover_rslts`` appending only the missing cells with output slots mapped
  back to the real PES ids.
* ``q_up`` passes ``n_pes`` to the queue; indexed multirotor placeholders
  resolve in ``create_input``.
* The automech branch of ``create_input`` (``AutomechKinWriter`` replaced by
  a capture double): one ``{name}P{slot:02d}.py`` per PES slot and no
  ``.inp``; full grid in a normal run, the sub-grid in postprocessing.
* ``load_rates_from_db`` fills the rate arrays (zeros for empty rows).
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus
from kimeco.rate_coef import PP_KIN_ROWID_BASE, RateCo


# ===========================================================================
# P/T grid reuse: is_in_db, set_status, create_input, recover_rslts
# ===========================================================================
class _FakeSOP:
    def __init__(self, pairs, pes_ids=(0,)) -> None:
        self.pes_ids = list(pes_ids)
        self._pairs = list(pairs)

    def reaction_iterator(self):
        return iter(self._pairs)

    def species_names_in_pes(self, pes_id: int):
        return ['A', 'B']


class _FakeKinDB:
    def __init__(self, rows) -> None:
        self._rows = list(rows)

    def get_rates_for_kin_id(self, table, kin_id, pes_id=None):
        return list(self._rows)

    def pp_row_ids(self, table, kin_id, keys):
        return [PP_KIN_ROWID_BASE + i for i in range(len(keys))]


class _StatusQueue:
    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.NOT_IN_QUEUE


class _RecoverQueue:
    def pickUp(self, id: int, jtype: str) -> None:
        return None

    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.PICKED_UP


class _FakeMOR:
    """MESS output stub with a distinct A->B rate per (P,T) cell."""

    def __init__(self, filename, settings, sop, klog) -> None:
        self.tbl_map = {'A': 0, 'B': 1}
        self.rc = np.zeros((2, 2, 2, 2), dtype=float)
        self.rc[:, :, 0, 1] = np.array([[10.0, 11.0], [12.0, 13.0]])

    def read(self) -> None:
        return None


def _settings(postprocess: bool) -> dict[str, Any]:
    return {
        'rc_software': 'mess',
        'postprocess': postprocess,
        'rc_pres': [1.0, 2.0],
        'rc_temp': [300.0, 400.0],
        'pp_pres': [1.0, 2.0],
        'pp_temp': [300.0, 400.0],
        'cpu_kin': 2,
        'mem_kin': 500,
    }


def _rateco(tmp_path: Path, rows, postprocess: bool = True,
            q_sys=None) -> RateCo:
    return RateCo(
        sop=cast(Any, _FakeSOP(pairs=[(0, 'A', 'B')])),
        settings=_settings(postprocess),
        software_tpls=[['tpl0']],
        id=0,
        q_idx=1,
        name='G0000E0000',
        loc=str(tmp_path),
        q_sys=cast(Any, q_sys or _StatusQueue()),
        db=cast(Any, _FakeKinDB(rows)),
        klog=KMOLogger(filename=str(tmp_path / 'rc.log')),
    )


_FULL_ROWS = [
    (1.0, 300.0, 0, 'A', 'B', 1.0),
    (1.0, 400.0, 0, 'A', 'B', 1.0),
    (2.0, 300.0, 0, 'A', 'B', 1.0),
    (2.0, 400.0, 0, 'A', 'B', 1.0),
]


# Present only for (1,300) and (2,400): the diagonal is missing.
_PARTIAL_ROWS = [
    (1.0, 300.0, 0, 'A', 'B', 1.0),
    (2.0, 400.0, 0, 'A', 'B', 1.0),
]


# ---------------------------------------------------------------------------
# is_in_db
# ---------------------------------------------------------------------------
def test_is_in_db_full_and_partial_grid(tmp_path) -> None:
    """A full grid in KIN_DB is in the DB with an empty missing grid; a partial
    one is not, with exactly the missing cells listed."""
    _tmp_root = tmp_path
    # -- test_is_in_db_true_and_empty_missing_grid_on_full_grid
    tmp_path = _tmp_root / 'test_is_in_db_true_and_empty_missing_grid_on_full_grid'
    tmp_path.mkdir(parents=True)
    rc = _rateco(tmp_path, _FULL_ROWS)

    assert rc.is_in_db(table='G0000') is True
    assert rc.missing_grid == []

    # -- test_is_in_db_false_and_exact_missing_cells_on_partial
    tmp_path = _tmp_root / 'test_is_in_db_false_and_exact_missing_cells_on_partial'
    tmp_path.mkdir(parents=True)
    rc = _rateco(tmp_path, _PARTIAL_ROWS)

    assert rc.is_in_db(table='G0000') is False
    assert rc.missing_grid == [(1.0, 400.0), (2.0, 300.0)]


# ---------------------------------------------------------------------------
# set_status full-grid parity
# ---------------------------------------------------------------------------
def test_set_status(tmp_path) -> None:
    """set_status finishes a full-grid job and surfaces the KeyError of a
    missing generation table."""
    _tmp_root = tmp_path
    # -- test_set_status_finished_on_full_grid
    tmp_path = _tmp_root / 'test_set_status_finished_on_full_grid'
    tmp_path.mkdir(parents=True)
    rc = _rateco(tmp_path, _FULL_ROWS, q_sys=_StatusQueue())
    Path(rc.loc).mkdir(parents=True, exist_ok=True)
    for output_name in rc.output_names:
        Path(output_name).write_text('ok')

    rc.set_status(table='G0000')

    assert rc.status == JobStatus.FINISHED
    assert rc.missing_grid == []

    # -- test_set_status_surfaces_missing_generation_table_keyerror
    tmp_path = _tmp_root / 'test_set_status_surfaces_missing_generation_table_keyerror'
    tmp_path.mkdir(parents=True)
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


# ---------------------------------------------------------------------------
# create_input sub-grid
# ---------------------------------------------------------------------------
def test_create_input_grid(tmp_path, monkeypatch) -> None:
    """Postprocessing writes only the missing sub-grid; a normal run passes the
    full grid."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_create_input_writes_only_missing_sub_grid
    tmp_path = _tmp_root / 'test_create_input_writes_only_missing_sub_grid'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        captured: list[dict] = []

        class _CaptureWriter:
            def __init__(self, SOP, tpl, pres=None, temp=None) -> None:
                captured.append({'pres': pres, 'temp': temp})

            def write(self, loc, filename) -> None:
                return None

        monkeypatch.setattr('kimeco.rate_coef.MessWriter', _CaptureWriter)

        rc = _rateco(tmp_path, _PARTIAL_ROWS, postprocess=True)
        # A single missing cell -> strict sub-grid of the full 2x2 grid.
        rc.missing_grid = [(1.0, 400.0)]
        Path(rc.loc).mkdir(parents=True, exist_ok=True)

        rc.create_input()

        assert len(captured) == 1
        assert captured[0]['pres'] == [1.0]
        assert captured[0]['temp'] == [400.0]

    # -- test_create_input_normal_run_passes_full_grid
    tmp_path = _tmp_root / 'test_create_input_normal_run_passes_full_grid'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        captured: list[dict] = []

        class _CaptureWriter:
            def __init__(self, SOP, tpl, pres=None, temp=None) -> None:
                captured.append({'pres': pres, 'temp': temp})

            def write(self, loc, filename) -> None:
                return None

        monkeypatch.setattr('kimeco.rate_coef.MessWriter', _CaptureWriter)

        rc = _rateco(tmp_path, _FULL_ROWS, postprocess=False)
        Path(rc.loc).mkdir(parents=True, exist_ok=True)

        rc.create_input()

        # No override in a normal run: the writer falls back to SOP grids.
        assert captured[0]['pres'] is None
        assert captured[0]['temp'] is None


# ---------------------------------------------------------------------------
# recover_rslts additive banding
# ---------------------------------------------------------------------------
def test_recover_rslts(tmp_path, monkeypatch) -> None:
    """Partial recovery appends only the missing cells; a normal run writes the
    full grid with low row ids; output slots map back to the real PES ids."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_recover_rslts_partial_appends_only_missing_cells
    tmp_path = _tmp_root / 'test_recover_rslts_partial_appends_only_missing_cells'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(
            'kimeco.rate_coef.MessOutputReader', _FakeMOR)
        rc = _rateco(tmp_path, _PARTIAL_ROWS, postprocess=True,
                     q_sys=_RecoverQueue())
        rc.table = 'G0000'
        rc.missing_grid = [(1.0, 400.0)]
        Path(rc.loc).mkdir(parents=True, exist_ok=True)
        for output_name in rc.output_names:
            Path(output_name).write_text('ok')

        rows = rc.recover_rslts()

        # Only the single missing (P,T) cell is produced (1 reaction pair).
        assert len(rows) == 1
        row = rows[0]
        assert (row[1], row[2]) == (1.0, 400.0)
        assert row[7] == 11.0  # rc[p=1.0, t=400.0]
        # Reserved row-id band keeps additive rows from clobbering originals.
        assert row[0] >= PP_KIN_ROWID_BASE

    # -- test_recover_rslts_normal_run_writes_full_grid_low_ids
    tmp_path = _tmp_root / 'test_recover_rslts_normal_run_writes_full_grid_low_ids'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(
            'kimeco.rate_coef.MessOutputReader', _FakeMOR)
        rc = _rateco(tmp_path, _FULL_ROWS, postprocess=False,
                     q_sys=_RecoverQueue())
        Path(rc.loc).mkdir(parents=True, exist_ok=True)
        for output_name in rc.output_names:
            Path(output_name).write_text('ok')

        rows = rc.recover_rslts()

        # Every (P,T) cell present, all row ids in the normal (low) band.
        assert len(rows) == 4
        assert all(row[0] < PP_KIN_ROWID_BASE for row in rows)
        assert {(row[1], row[2]) for row in rows} == {
            (1.0, 300.0), (1.0, 400.0), (2.0, 300.0), (2.0, 400.0)}

    # -- test_recover_results_maps_output_slot_to_real_pes_id
    tmp_path = _tmp_root / 'test_recover_results_maps_output_slot_to_real_pes_id'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
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


class _PlainSOP:
    """Minimal placeholder-free SOP for the real MessWriter path."""

    def __init__(self) -> None:
        self.pes_ids = [0]
        self.parameters_names: dict[str, str] = {}
        self.items: dict[str, Any] = {}

    def reaction_iterator(self):
        return iter([])


def _plain_rateco(tmp_path: Path, use_automech) -> RateCo:
    settings: dict[str, Any] = {
        'rc_software': 'mess',
        'postprocess': False,
        'rc_pres': [1.0],
        'rc_temp': [300.0],
        'cpu_kin': 2,
        'mem_kin': 500,
    }
    if use_automech is not None:
        settings['use_automech'] = use_automech
    rc = RateCo(
        sop=cast(Any, _PlainSOP()),
        settings=settings,
        software_tpls=[['Static input line\n', 'Another line\n']],
        id=0,
        q_idx=1,
        name='G0000E0000',
        loc=str(tmp_path),
        q_sys=cast(Any, _StatusQueue()),
        db=cast(Any, _FakeKinDB([])),
        klog=KMOLogger(filename=str(tmp_path / 'plain.log')),
    )
    Path(rc.loc).mkdir(parents=True, exist_ok=True)
    return rc


def test_create_input_absent_vs_false_use_automech(tmp_path, monkeypatch) -> None:
    """An absent use_automech writes the same .inp bytes as False, through the
    real MessWriter."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_create_input_absent_vs_false_use_automech_byte_identical_inp
    tmp_path = _tmp_root / 'test_create_input_absent_vs_false_use_automech_byte_identical_inp'
    tmp_path.mkdir(parents=True)
    # The classic MESS path must be unchanged whether use_automech is absent
    # or explicitly False: both produce byte-identical P00.inp via MessWriter.
    rc_absent = _plain_rateco(tmp_path / 'absent', use_automech=None)
    rc_false = _plain_rateco(tmp_path / 'false', use_automech=False)

    rc_absent.create_input()
    rc_false.create_input()

    inp_absent = (Path(rc_absent.loc) / 'G0000E0000P00.inp').read_bytes()
    inp_false = (Path(rc_false.loc) / 'G0000E0000P00.inp').read_bytes()

    assert inp_absent == inp_false
    assert b'Static input line' in inp_absent

    # -- test_use_automech_false_writes_inp_via_real_messwriter
    tmp_path = _tmp_root / 'test_use_automech_false_writes_inp_via_real_messwriter'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        # AutomechKinWriter must never be constructed on the classic path.
        def _boom(*a, **k):
            raise AssertionError('AutomechKinWriter used with use_automech=False')
        monkeypatch.setattr('kimeco.rate_coef.AutomechKinWriter', _boom)

        rc = _am_rateco(
            tmp_path,
            _am_settings(postprocess=False, use_automech=False),
            n_pes=1, pes_ids=(0,))

        rc.create_input()

        inp = Path(rc.loc) / 'G0000E0001P00.inp'
        assert inp.exists()
        assert 'static line' in inp.read_text()
        assert list(Path(rc.loc).glob('*.py')) == []


# ===========================================================================
# q_up and create_input placeholders
# ===========================================================================
class DummySOP:
    def __init__(self) -> None:
        self.pes_ids = [0, 1, 2]

    def reaction_iterator(self):
        return iter([])


class DummyDB:
    def get_ids_from_kin_id(self, table: str, kin_id: int):
        return []

    def get_rates_for_kin_id(self, table: str, kin_id: int, pes_id=None):
        return []


class DummyDBMissingTable:
    def get_rates_for_kin_id(self, table: str, kin_id: int, pes_id=None):
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


def test_q_up_passes_n_pes_and_create_input_resolves_placeholders(rateco, monkeypatch, tmp_path) -> None:
    """q_up hands n_pes, the kin job type and the name to the queue;
    create_input resolves indexed multirotor placeholders."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_q_up_passes_n_pes_to_queue
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(rateco, "create_input", lambda: None)
        rateco.status = JobStatus.NOT_IN_QUEUE

        rateco.q_up()

        assert len(cast(Any, rateco.q_sys).calls) == 1
        call = cast(Any, rateco.q_sys).calls[0]
        assert call["n_pes"] == 3
        assert call["jtype"] == "kin"
        assert call["name"] == "G0000E0001"

    # -- test_create_input_resolves_indexed_multirotor_placeholder
    tmp_path = _tmp_root / 'test_create_input_resolves_indexed_multirotor_placeholder'
    tmp_path.mkdir(parents=True)
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


# ===========================================================================
# use_automech branch of create_input
# ===========================================================================
class _AmSOP:
    def __init__(self, pes_ids=(0, 1)) -> None:
        self.pes_ids = list(pes_ids)
        # A real placeholder-free SOP surface for the MessWriter fallback.
        self.parameters_names: dict[str, str] = {}
        self.items: dict[str, Any] = {}

    def reaction_iterator(self):
        return iter([])


class _NoQueue:
    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.NOT_IN_QUEUE


class _AmKinDB:
    def get_rates_for_kin_id(self, table, kin_id, pes_id=None):
        return []


def _am_settings(postprocess: bool, use_automech: bool | None) -> dict[str, Any]:
    s: dict[str, Any] = {
        'rc_software': 'mess',
        'postprocess': postprocess,
        'rc_pres': [1.0, 2.0],
        'rc_temp': [300.0, 400.0],
        'pp_pres': [1.0, 2.0],
        'pp_temp': [300.0, 400.0],
        'cpu_kin': 2,
        'mem_kin': 500,
    }
    if use_automech is not None:
        s['use_automech'] = use_automech
    return s


def _am_rateco(tmp_path: Path, settings: dict[str, Any], n_pes: int = 2,
            pes_ids=(0, 1)) -> RateCo:
    rc = RateCo(
        sop=cast(Any, _AmSOP(pes_ids=pes_ids)),
        settings=settings,
        software_tpls=[['static line\n'] for _ in range(n_pes)],
        id=0,
        q_idx=1,
        name='G0000E0001',
        loc=str(tmp_path),
        q_sys=cast(Any, _NoQueue()),
        db=cast(Any, _AmKinDB()),
        klog=KMOLogger(filename=str(tmp_path / 'rc.log')),
    )
    Path(rc.loc).mkdir(parents=True, exist_ok=True)
    return rc


class _CaptureAutomech:
    """Records constructor args and emitted filenames; writes a stub file."""

    def __init__(self, records: list[dict], writes: list[str]):
        self.records = records
        self.writes = writes

    def __call__(self, sop, pes_id, sub_p=None, sub_t=None, settings=None):
        self.records.append(
            {'pes_id': pes_id, 'sub_p': sub_p, 'sub_t': sub_t})
        parent = self

        def _write(loc, filename):
            parent.writes.append(filename)
            Path(loc, filename).write_text('# stub driver\n')

        return SimpleNamespace(write=_write)


def _patch_automech(monkeypatch) -> tuple[list[dict], list[str]]:
    records: list[dict] = []
    writes: list[str] = []
    monkeypatch.setattr(
        'kimeco.rate_coef.AutomechKinWriter',
        _CaptureAutomech(records, writes))
    return records, writes


def _forbid_messwriter(monkeypatch) -> None:
    def _boom(*a, **k):
        raise AssertionError('MessWriter must not be used with use_automech')
    monkeypatch.setattr('kimeco.rate_coef.MessWriter', _boom)


# ---------------------------------------------------------------------------
# use_automech=True emission
# ---------------------------------------------------------------------------
def test_automech_emits_one_py_per_slot_no_inp(
        tmp_path: Path, monkeypatch) -> None:
    records, writes = _patch_automech(monkeypatch)
    _forbid_messwriter(monkeypatch)
    rc = _am_rateco(tmp_path, _am_settings(postprocess=False, use_automech=True))

    rc.create_input()

    assert writes == ['G0000E0001P00.py', 'G0000E0001P01.py']
    assert [r['pes_id'] for r in records] == [0, 1]
    # No MESS .inp files are produced on the automech path.
    assert list(Path(rc.loc).glob('*.inp')) == []


def test_automech_grid_full_vs_sub(tmp_path, monkeypatch) -> None:
    """The automech writer receives the full grid in a normal run (sub_p/sub_t
    None) and the missing sub-grid in postprocessing."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_automech_normal_run_passes_full_grid
    tmp_path = _tmp_root / 'test_automech_normal_run_passes_full_grid'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        records, _ = _patch_automech(monkeypatch)
        _forbid_messwriter(monkeypatch)
        rc = _am_rateco(tmp_path, _am_settings(postprocess=False, use_automech=True))

        rc.create_input()

        # No override in a normal run: the writer uses the SOP grid.
        assert all(r['sub_p'] is None and r['sub_t'] is None for r in records)

    # -- test_automech_postprocess_passes_sub_grid
    tmp_path = _tmp_root / 'test_automech_postprocess_passes_sub_grid'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        records, _ = _patch_automech(monkeypatch)
        _forbid_messwriter(monkeypatch)
        rc = _am_rateco(tmp_path, _am_settings(postprocess=True, use_automech=True))
        # A single missing (P,T) cell -> strict sub-grid.
        rc.missing_grid = [(2.0, 300.0)]

        rc.create_input()

        assert all(r['sub_p'] == [2.0] and r['sub_t'] == [300.0]
                   for r in records)


# ---------------------------------------------------------------------------
# use_automech=False fallback still uses the real MessWriter
# ---------------------------------------------------------------------------


# ===========================================================================
# load_rates_from_db
# ===========================================================================
def _make_rateco(rows, pres, temp, kin_id=0):
    """Build a bare RateCo wired only for load_rates_from_db."""
    rc = RateCo.__new__(RateCo)
    rc.db = cast(Any, SimpleNamespace(
        get_rates_for_kin_id=lambda table, kin_id: rows))
    rc.sop = cast(Any, SimpleNamespace(
        pes_ids=[0],
        species_names_in_pes=lambda pes: ['A', 'B']))
    rc.pres = pres
    rc.temp = temp
    rc.id = kin_id
    return rc


def test_load_rates_from_db() -> None:
    """load_rates_from_db populates the rate attributes; empty rows yield zero
    arrays."""
    # -- test_load_rates_from_db_populates_attrs
    k_value = 1.23e12
    rows = [
        # (p, t, pes_id, from_name, to_name, k_value)
        (1.0, 300.0, 0, 'A', 'B', k_value),      # valid A->B cell
        (0.5, 300.0, 0, 'A', 'B', 9.9),          # off-grid pressure -> skipped
        (1.0, 300.0, 0, 'A', 'X', 8.8),          # unknown species -> skipped
    ]
    rc = _make_rateco(rows, pres=[1.0], temp=[300.0])

    rc.load_rates_from_db(table='G0000')

    assert rc.tbl_map_by_pes[0] == {'A': 0, 'B': 1}
    arr = rc.rc_by_pes[0]
    assert arr.shape == (1, 1, 2, 2)
    # Valid entry landed at [p_idx=0, t_idx=0, from=A(0), to=B(1)].
    assert arr[0, 0, 0, 1] == k_value
    # Everything else (incl. off-grid / unknown-species rows) stays zero.
    total_nonzero = int((arr != 0).sum())
    assert total_nonzero == 1

    # -- test_load_rates_from_db_empty_rows_yields_zero_arrays
    rc = _make_rateco(rows=[], pres=[1.0, 2.0], temp=[300.0, 400.0])

    rc.load_rates_from_db(table='G0000')

    assert rc.tbl_map_by_pes[0] == {'A': 0, 'B': 1}
    arr = rc.rc_by_pes[0]
    assert arr.shape == (2, 2, 2, 2)
    assert int((arr != 0).sum()) == 0


