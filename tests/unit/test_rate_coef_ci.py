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
* Prompt mode (``use_automech`` + ``prompt_reactions``): the collector script,
  the restart status, the prompt-rates file checked before any ``.out`` is
  read, then the prompt KIN rows (``to_name`` ending with
  ``PROMPT_TO_NAME_SUFFIX``, k mapped by P/T value, ids in the band from
  ``PROMPT_KIN_ROWID_BASE`` or from ``pp_row_ids`` in kmopp, the band guard,
  the duplicate-key stop) and ``is_in_db`` counting thermal and prompt rows
  apart.
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


class _CaptureCollector:
    """PromptCollectorWriter double: records its arguments and the files
    given to write()."""

    def __init__(self, records: list[dict]) -> None:
        self.records = records

    def __call__(self, **kwargs: Any) -> SimpleNamespace:
        record = dict(kwargs)
        self.records.append(record)

        def _write(files: Any) -> None:
            record['files'] = files
            Path(files.script).write_text('# stub collector\n')

        return SimpleNamespace(write=_write)


def _patch_collector(monkeypatch) -> list[dict]:
    records: list[dict] = []
    monkeypatch.setattr('kimeco.rate_coef.PromptCollectorWriter',
                        _CaptureCollector(records))
    return records


def test_automech_forwards_settings_to_writer(
        tmp_path: Path, monkeypatch) -> None:
    """RateCo hands its own settings to every AutomechKinWriter, so the
    prompt flag (read by the writer's payload) reaches each PES driver."""
    received: list[Any] = []

    def _capture(sop, pes_id, sub_p=None, sub_t=None, settings=None):
        received.append(settings)
        return SimpleNamespace(
            write=lambda loc, filename: Path(loc, filename).write_text(''))

    monkeypatch.setattr('kimeco.rate_coef.AutomechKinWriter', _capture)
    # Prompt mode also writes the collector (step 3): capture double, the
    # minimal _AmSOP has no MESS-input data to build channels from.
    collectors = _patch_collector(monkeypatch)
    settings = _am_settings(postprocess=False, use_automech=True)
    settings['prompt_reactions'] = True
    rc = _am_rateco(tmp_path, settings)

    rc.create_input()

    assert len(received) == 2
    assert all(s is rc.settings for s in received)
    assert all(s['prompt_reactions'] is True for s in received)
    assert len(collectors) == 1 and collectors[0]['settings'] is rc.settings


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




# ===========================================================================
# Prompt mode (use_automech + prompt_reactions): collector script, status,
# prompt-rates file check before any .out is read, prompt KIN rows (to_name
# suffix, k by P/T value, band ids or kmopp ids, guard, duplicate stop) and
# is_in_db counting thermal and prompt rows apart
# ===========================================================================
import json  # noqa: E402

from kimeco.q_sys import COLLECTOR_SUBMIT_FAILED, QueueingSystem  # noqa: E402
from kimeco.writers.prompt_collector import (  # noqa: E402
    PROMPT_TO_NAME_SUFFIX, PromptChannel, PromptCollectorWriter,
    PromptRatesError, PromptRatesFile)


class _PromptSOP(_FakeSOP):
    """_FakeSOP plus the MESS-input data of prompt links. Default: PES 0
    holds PEDSpecies A+B=C+D, PES 1 the HotEnergies well C (species C, E+F):
    two channels, ``C+D__prompt`` (thermalised) and ``D+E+F__prompt``.

    ``hot_pes_ids`` gives every listed PES the same hot well C (two hot
    PESs: duplicate KIN keys); ``bimol`` the fragments of the hot-PES
    bimolecular, in SOP order."""

    def __init__(self, pairs=((0, 'A', 'B'),), ped_species=('A+B=C+D',),
                 hot_pes_ids=(1,), bimol=('E', 'F')) -> None:
        super().__init__(pairs=list(pairs), pes_ids=(0, *hot_pes_ids))
        self.pes_file_data = {
            0: SimpleNamespace(ped_species=list(ped_species),
                               hot_energies=None)}
        for hot_pes_id in hot_pes_ids:
            self.pes_file_data[hot_pes_id] = SimpleNamespace(
                ped_species=None, hot_energies={'C': (-10.0, 1.0, 50.0)})
        self._hot_pes_ids = set(hot_pes_ids)
        self._bimol = tuple(bimol)
        self.pres = [1.0, 2.0]
        self.temp = [300.0, 400.0]

    def wells_in(self, pes_id: int):
        if pes_id not in self._hot_pes_ids:
            return []
        return [SimpleNamespace(name='C', dummy=False)]

    def bimols_in(self, pes_id: int):
        if pes_id not in self._hot_pes_ids:
            return []
        return [SimpleNamespace(
            name='+'.join(self._bimol), dummy=False,
            fragments=[SimpleNamespace(name=frag) for frag in self._bimol])]


# Four thermal pairs (n_pairs = 4 > n_channels = 2): thermal side of the
# row-id guard.
_PAIRS4 = [(0, 'A', 'B'), (0, 'B', 'A'), (1, 'A', 'B'), (1, 'B', 'A')]
# KIN to_names of the default _PromptSOP channels, in fixed-set order.
_PROMPT_TO = ['C+D__prompt', 'D+E+F__prompt']
_GRID = [(1.0, 300.0), (1.0, 400.0), (2.0, 300.0), (2.0, 400.0)]


class _PromptStatusQueue:
    def __init__(self, failed: bool = False) -> None:
        self.failed = failed
        self.asked: list[int] = []

    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.NOT_IN_QUEUE

    def collector_submit_failed(self, idx: int) -> bool:
        self.asked.append(idx)
        return self.failed


class _RecordingKinDB(_FakeKinDB):
    """_FakeKinDB recording every pp_row_ids call."""

    def __init__(self, rows) -> None:
        super().__init__(rows)
        self.pp_calls: list[tuple[str, int, list]] = []

    def pp_row_ids(self, table, kin_id, keys):
        self.pp_calls.append((table, kin_id, list(keys)))
        return super().pp_row_ids(table, kin_id, keys)


# Thermal rows of _FULL_ROWS plus the two prompt rows of every cell: a
# complete prompt-mode cell for _PromptSOP.
_PROMPT_FULL_ROWS = _FULL_ROWS + [
    (p, t, 0, 'A+B', to_name, 1e-13) for p, t in _GRID
    for to_name in _PROMPT_TO]


def _prompt_rc(tmp_path: Path, rows=_FULL_ROWS, q_sys=None,
               postprocess: bool = False, sop=None, model_id: int = 0,
               db=None, **extra: Any) -> RateCo:
    settings = _settings(postprocess)
    settings.update(use_automech=True, prompt_reactions=True)
    settings.update(extra)
    sop = sop or _PromptSOP()
    rc = RateCo(
        sop=cast(Any, sop),
        settings=settings,
        software_tpls=[[f'tpl{i}'] for i in range(len(sop.pes_ids))],
        id=model_id,
        q_idx=1,
        name=f'G0000E{model_id:04d}',
        loc=str(tmp_path),
        q_sys=cast(Any, q_sys or _PromptStatusQueue()),
        db=cast(Any, db or _FakeKinDB(rows)),
        klog=KMOLogger(filename=str(tmp_path / 'prompt_rc.log')),
    )
    Path(rc.loc).mkdir(parents=True, exist_ok=True)
    return rc


def _kv(ch_idx: int, p: float, t: float) -> float:
    """Distinct prompt k per channel and (P,T) value."""
    return (ch_idx + 1) * 1e-12 + p * 1e-14 + t * 1e-17


def _write_rates(rc: RateCo, pressures=None, temperatures=None, k_of=None,
                 tamper=None) -> dict:
    """A valid prompt-rates file for rc (fixed channels, rc's grid). k is
    1e-13 everywhere, or ``k_of(ch_idx, p, t)``; ``tamper(doc)`` edits the
    content before it is written."""
    grid_p, grid_t = PromptCollectorWriter.grid(rc.sop, *rc._sub_grid())
    pressures = grid_p if pressures is None else pressures
    temperatures = grid_t if temperatures is None else temperatures
    channels = PromptChannel.fixed_set(rc.sop)
    if k_of is None:
        rates = [np.full((len(pressures), len(temperatures)), 1e-13)
                 for _ in channels]
    else:
        rates = [np.array([[k_of(ch_idx, p, t) for t in temperatures]
                           for p in pressures])
                 for ch_idx in range(len(channels))]
    doc = PromptRatesFile.build(
        rc.name, rc.id, 'rovib_dos', 0.01, pressures, temperatures, channels,
        rates)
    if tamper is not None:
        tamper(doc)
    Path(rc.prompt_files.rates).write_text(json.dumps(doc))
    return doc


def _is_prompt_row(row) -> bool:
    return row[6].endswith(PROMPT_TO_NAME_SUFFIX)


def _forbid_mor(monkeypatch) -> None:
    def _boom(*a, **k):
        raise AssertionError('a .out was read before the prompt check')
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _boom)


def _outputs_present(rc: RateCo) -> None:
    for output_name in rc.output_names:
        Path(output_name).write_text('ok')


def test_prompt_create_input_removes_stale_json_then_writes_collector(
        tmp_path, monkeypatch) -> None:
    """R1: the stale JSON (and tmp) of an earlier submission is deleted
    before the drivers; one driver per slot, then one collector writer
    call with the model's name, id, PES ids, reader grid and the full grid
    (sub_p/sub_t None), writing rc.prompt_files."""
    collectors = _patch_collector(monkeypatch)
    rc = _prompt_rc(tmp_path)
    stale = [Path(rc.prompt_files.rates), Path(rc.prompt_files.rates_tmp)]
    for path in stale:
        path.write_text('stale')
    seen: list[bool] = []

    def _driver(sop, pes_id, sub_p=None, sub_t=None, settings=None):
        seen.append(any(p.exists() for p in stale))
        assert not collectors, 'collector written before the drivers'
        return SimpleNamespace(write=lambda loc, filename: Path(
            loc, filename).write_text('#'))

    monkeypatch.setattr('kimeco.rate_coef.AutomechKinWriter', _driver)
    rc.create_input()
    assert seen == [False, False]
    assert len(collectors) == 1
    call = collectors[0]
    assert call['sop'] is rc.sop and call['settings'] is rc.settings
    assert (call['kin_name'], call['model_id']) == ('G0000E0000', 0)
    assert call['output_pes_ids'] == [0, 1]
    assert call['reader_pres'] == [1.0, 2.0]
    assert call['reader_temp'] == [300.0, 400.0]
    assert (call['sub_p'], call['sub_t']) == (None, None)
    assert call['files'] is rc.prompt_files
    assert rc.prompt_files.script == f'{rc.loc}/prompt_G0000E0000.py'
    assert rc.prompt_reactions is True


def test_prompt_create_input_postprocess_sub_grid(tmp_path,
                                                  monkeypatch) -> None:
    """R2: kmopp missing cell (2.0, 300.0): drivers and collector get the
    same sub-grid."""
    records, _ = _patch_automech(monkeypatch)
    collectors = _patch_collector(monkeypatch)
    rc = _prompt_rc(tmp_path, rows=_PARTIAL_ROWS, postprocess=True)
    rc.missing_grid = [(2.0, 300.0)]
    rc.create_input()
    assert all((r['sub_p'], r['sub_t']) == ([2.0], [300.0])
               for r in records)
    assert (collectors[0]['sub_p'], collectors[0]['sub_t']) == ([2.0],
                                                                [300.0])


@pytest.mark.parametrize('prompt, use_automech', [(False, True), (True, False)],
                         ids=['prompt_off', 'no_automech'])
def test_non_prompt_create_input_writes_no_collector(tmp_path, monkeypatch,
                                                     prompt,
                                                     use_automech) -> None:
    """R3: outside prompt mode the collector writer is never built and no
    file is deleted (a JSON lying there stays)."""
    def _boom(**kwargs):
        raise AssertionError('collector written outside prompt mode')

    monkeypatch.setattr('kimeco.rate_coef.PromptCollectorWriter', _boom)
    _patch_automech(monkeypatch)

    class _Mess:
        def __init__(self, SOP, tpl, pres=None, temp=None) -> None:
            pass

        def write(self, loc, filename) -> None:
            Path(loc, filename).write_text('inp')

    monkeypatch.setattr('kimeco.rate_coef.MessWriter', _Mess)
    rc = _prompt_rc(tmp_path, prompt_reactions=prompt,
                    use_automech=use_automech)
    Path(rc.prompt_files.rates).write_text('kept')
    rc.create_input()
    assert rc.prompt_reactions is False
    assert Path(rc.prompt_files.rates).read_text() == 'kept'


def test_prompt_set_status_restart_needs_json(tmp_path) -> None:
    """R4: not in queue, outputs and full grid (thermal and prompt rows)
    present: FINISHED only with the prompt-rates file, else NOT_IN_QUEUE
    (q_up resubmits); the queue is asked about the collector sbatch. D8: a
    DB holding the thermal rows only (step-3 DB) is not complete in prompt
    mode, even with the file: NOT_IN_QUEUE, every cell missing."""
    queue = _PromptStatusQueue()
    rc = _prompt_rc(tmp_path, rows=_PROMPT_FULL_ROWS, q_sys=queue)
    _outputs_present(rc)
    rc.set_status(table='G0000')
    assert rc.status == JobStatus.NOT_IN_QUEUE
    assert queue.asked == [1]
    _write_rates(rc)
    rc.set_status(table='G0000')
    assert rc.status == JobStatus.FINISHED
    assert rc.missing_grid == []
    rc.db = cast(Any, _FakeKinDB(_FULL_ROWS))
    rc.set_status(table='G0000')
    assert rc.status == JobStatus.NOT_IN_QUEUE
    assert rc.missing_grid == _GRID


def test_non_prompt_set_status_never_asks_collector(tmp_path) -> None:
    queue = _PromptStatusQueue(failed=True)
    rc = _prompt_rc(tmp_path, q_sys=queue, prompt_reactions=False)
    _outputs_present(rc)
    rc.set_status(table='G0000')
    assert rc.status == JobStatus.FINISHED
    assert queue.asked == []


def _real_qs(tmp_path: Path, rc: RateCo) -> QueueingSystem:
    settings = {
        'max_jobs': 32, 'max_cpu': 128, 'max_mem': 64000, 'cpu_kin': 2,
        'cpu_sim': 1, 'mem_kin': 500, 'mem_sim': 500, 'n_exp': 1,
        'exclude_nodes': '', 'q_name': 'q', 'max_user_jobs': 128,
        'scratch_base': str(tmp_path) + '/', 'project_name': 'P',
        'use_automech': True, 'prompt_reactions': True}
    qs = QueueingSystem(settings=settings, nel=4, klog=KMOLogger(
        filename=str(tmp_path / 'qs.log')))
    qs.add_to_q(name=rc.name, idx=rc.q_idx, location=rc.loc, jtype='kin',
                ressources=(2, 500), n_pes=2)
    rc.q_sys = qs
    return qs


def test_prompt_set_status_running_while_collector_runs(tmp_path,
                                                        monkeypatch) -> None:
    """R4b: real queue, array gone but collector still listed: the job
    stays RUNNING (outputs, grid and JSON present do not matter); once the
    collector left, FINISHED."""
    rc = _prompt_rc(tmp_path)
    qs = _real_qs(tmp_path, rc)
    _outputs_present(rc)
    _write_rates(rc)
    qs.kin_q[rc.q_idx]['sub_id'] = 100
    qs.kin_q[rc.q_idx]['collector_id'] = 101
    qs.kin_q[rc.q_idx]['status'] = JobStatus.RUNNING.value
    squeue = [101]
    monkeypatch.setattr(qs, 'get_all_running',
                        lambda: np.array(squeue, dtype=np.int32))
    qs.actualize()
    rc.set_status(table='G0000')
    assert rc.status == JobStatus.RUNNING
    squeue.clear()
    qs.actualize()
    rc.set_status(table='G0000')
    assert rc.status == JobStatus.FINISHED


def test_prompt_set_status_raises_on_collector_sbatch_failure(
        tmp_path) -> None:
    """R5: the sentinel recorded by the queue stops the run at the next
    RateCo pass (message names the model, sbatch and squeue); a real
    collector id does not."""
    rc = _prompt_rc(tmp_path)
    qs = _real_qs(tmp_path, rc)
    qs.kin_q[rc.q_idx]['sub_id'] = 100
    qs.kin_q[rc.q_idx]['status'] = JobStatus.RUNNING.value
    qs.kin_q[rc.q_idx]['collector_id'] = COLLECTOR_SUBMIT_FAILED
    with pytest.raises(PromptRatesError) as exc:
        rc.set_status(table='G0000')
    assert isinstance(exc.value, Exception)
    for needle in ('G0000E0000', 'model 0', 'sbatch', 'squeue'):
        assert needle in str(exc.value)
    qs.kin_q[rc.q_idx]['collector_id'] = 4243
    rc.set_status(table='G0000')
    assert rc.status == JobStatus.RUNNING


def test_prompt_recover_waits_then_stops_without_json(tmp_path,
                                                      monkeypatch) -> None:
    """R6: no prompt-rates file: RateCo polls PROMPT_RATES_WAIT_S /
    PROMPT_RATES_POLL_S times (defaults 60 s / 2 s, patched to 6 s here)
    and raises PromptRatesError naming the file and the collector logs,
    before any .out is read; a file appearing during the wait is used."""
    import kimeco.rate_coef as rate_coef
    assert (rate_coef.PROMPT_RATES_WAIT_S, rate_coef.PROMPT_RATES_POLL_S) \
        == (60, 2)
    monkeypatch.setattr(rate_coef, 'PROMPT_RATES_WAIT_S', 6)
    sleeps: list[float] = []
    monkeypatch.setattr('kimeco.rate_coef.time.sleep', sleeps.append)
    _forbid_mor(monkeypatch)
    rc = _prompt_rc(tmp_path, q_sys=_RecoverQueue())
    _outputs_present(rc)
    with pytest.raises(PromptRatesError) as exc:
        rc.recover_rslts()
    assert sleeps == [2, 2, 2]
    for needle in (rc.prompt_files.rates, 'logs/prompt_G0000E0000.err',
                   'logs/prompt_G0000E0000.stdout', '--kill-on-invalid-dep'):
        assert needle in str(exc.value), needle

    sleeps.clear()
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            _write_rates(rc)

    monkeypatch.setattr('kimeco.rate_coef.time.sleep', _sleep)
    # 4 thermal rows + 2 channels x 4 cells
    assert len(rc.recover_rslts()) == 4 + 2 * 4
    assert sleeps == [2, 2]


@pytest.mark.parametrize('text, needle', [
    ('', 'cannot be read as JSON'),
    ('not json', 'cannot be read as JSON'),
    (json.dumps({'format': 'kimeco-prompt-rates', 'version': 1,
                 'pressures': [1.0, 2.0], 'temperatures': [300.0, 400.0]}),
     'None channel records, expected 2'),
], ids=['empty', 'not_json', 'no_channels'])
def test_prompt_recover_stops_on_invalid_json(tmp_path, monkeypatch, text,
                                              needle) -> None:
    """R7: an invalid prompt-rates file stops the run before any .out is
    read."""
    _forbid_mor(monkeypatch)
    rc = _prompt_rc(tmp_path, q_sys=_RecoverQueue())
    _outputs_present(rc)
    Path(rc.prompt_files.rates).write_text(text)
    with pytest.raises(PromptRatesError, match=re.escape(needle)):
        rc.recover_rslts()


def test_prompt_recover_keeps_thermal_rows_and_ids(tmp_path,
                                                  monkeypatch) -> None:
    """I3 (was R8): with a valid file, the thermal rows of prompt mode are
    exactly the rows of the same model outside prompt mode (ids, P, T,
    names, k) and come first, followed by the 8 prompt rows; over models
    0, 1, 2 and 7 every id is unique, thermal ids < PROMPT_KIN_ROWID_BASE
    <= prompt ids < PP_KIN_ROWID_BASE."""
    import kimeco.rate_coef as rate_coef
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    all_ids: list[int] = []
    for model_id in (0, 1, 2, 7):
        rc = _prompt_rc(tmp_path / f'prompt{model_id}',
                        q_sys=_RecoverQueue(), model_id=model_id)
        _outputs_present(rc)
        _write_rates(rc)
        plain = _prompt_rc(tmp_path / f'plain{model_id}',
                           q_sys=_RecoverQueue(), model_id=model_id,
                           prompt_reactions=False)
        _outputs_present(plain)
        rows = rc.recover_rslts()
        plain_rows = plain.recover_rslts()
        assert len(plain_rows) == 4 and len(rows) == 4 + 8
        assert rows[:4] == plain_rows
        assert [r for r in rows if not _is_prompt_row(r)] == plain_rows
        assert all(_is_prompt_row(r) for r in rows[4:])
        assert all(r[0] < rate_coef.PROMPT_KIN_ROWID_BASE
                   for r in plain_rows)
        assert all(rate_coef.PROMPT_KIN_ROWID_BASE <= r[0]
                   < PP_KIN_ROWID_BASE for r in rows[4:])
        all_ids.extend(r[0] for r in rows)
    assert len(all_ids) == len(set(all_ids)) == 4 * 12


def test_prompt_recover_checks_postprocess_sub_grid(tmp_path,
                                                    monkeypatch) -> None:
    """kmopp: the file must hold exactly the sub-grid of the missing cells
    (exact floats); a full-grid file is refused."""
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    rc = _prompt_rc(tmp_path, rows=_PARTIAL_ROWS, postprocess=True,
                    q_sys=_RecoverQueue())
    rc.missing_grid = [(1.0, 400.0)]
    rc.table = 'G0000'
    _outputs_present(rc)
    _write_rates(rc, pressures=[1.0, 2.0], temperatures=[300.0, 400.0])
    with pytest.raises(PromptRatesError, match=r"'pressures' is \[1.0, 2.0\]"):
        rc.recover_rslts()
    _write_rates(rc)
    assert json.loads(Path(rc.prompt_files.rates).read_text())[
        'pressures'] == [1.0]
    rows = rc.recover_rslts()
    # 1 thermal + 2 prompt rows, for the missing cell only
    assert [(r[1], r[2]) for r in rows] == [(1.0, 400.0)] * 3


# ---------------------------------------------------------------------------
# Prompt KIN rows: format, k by value, to_name from the fixed set
# ---------------------------------------------------------------------------
def test_prompt_rows_format_and_k_by_value(tmp_path, monkeypatch) -> None:
    """S1-S5: an optimisation run returns the 4 thermal rows, then one
    8-tuple ``(id, P, T, kin_id, pes_id = PED PES, from_name = PED
    reactant, to_name = products + '__prompt', k)`` per channel and cell,
    cell by cell in fixed-set order; k is the file's value at the row's
    channel and (P,T); P/T are the exact grid floats of the thermal rows;
    the thermalised channel maps to ``<ped_product>__prompt``; the suffix
    is the DB separator + 'prompt' and only prompt rows carry it. kmopp on
    the single cell (2.0, 400.0): the file holds a 1x1 grid, its [0][0]
    value lands on that cell (k mapped by value, not by grid index)."""
    from kimeco.database.kimeco_db import dbs
    _tmp_root = tmp_path
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    # -- optimisation run, full grid
    tmp_path = _tmp_root / 'full'
    rc = _prompt_rc(tmp_path, q_sys=_RecoverQueue())
    _outputs_present(rc)
    doc = _write_rates(rc, k_of=_kv)
    rows = rc.recover_rslts()
    assert len(rows) == 4 + 2 * 4
    thermal, prompt = rows[:4], rows[4:]
    assert not any(_is_prompt_row(r) for r in thermal)
    assert all(len(r) == 8 for r in prompt)
    assert [(r[1], r[2], r[6]) for r in prompt] == [
        (p, t, to_name) for p, t in _GRID for to_name in _PROMPT_TO]
    for row in prompt:
        _, p, t, kin_id, pes_id, from_name, to_name, k = row
        assert (kin_id, pes_id, from_name) == (0, 0, 'A+B')
        ch_idx = _PROMPT_TO.index(to_name)
        ip, it = rc.pres.index(p), rc.temp.index(t)
        assert k == doc['channels'][ch_idx]['k'][ip][it] == _kv(ch_idx, p, t)
        assert type(p) is float and type(t) is float
        assert p in rc.pres and t in rc.temp
    assert {(r[1], r[2]) for r in prompt} == {(r[1], r[2]) for r in thermal}
    channels = PromptChannel.fixed_set(rc.sop)
    therm = [c for c in channels if c.thermalised]
    assert [c.kin_row_to_name for c in therm] == ['C+D__prompt']
    assert therm[0].kin_row_to_name == therm[0].ped_product + '__prompt'
    assert doc['channels'][0]['thermalised'] is True
    assert {r[6] for r in thermal}.isdisjoint(_PROMPT_TO)
    assert PROMPT_TO_NAME_SUFFIX == dbs + 'prompt' == '__prompt'
    assert [c.kin_row_to_name for c in channels] == _PROMPT_TO
    # The property is not a dataclass field: payload keys unchanged.
    assert 'kin_row_to_name' not in channels[0].to_payload()

    # -- kmopp, missing cell (2.0, 400.0): file grid [2.0] x [400.0]
    tmp_path = _tmp_root / 'kmopp'
    rc = _prompt_rc(tmp_path, rows=_PARTIAL_ROWS[:1], postprocess=True,
                    q_sys=_RecoverQueue())
    rc.table = 'G0000'
    rc.missing_grid = [(2.0, 400.0)]
    _outputs_present(rc)
    doc = _write_rates(rc, k_of=_kv)
    assert (doc['pressures'], doc['temperatures']) == ([2.0], [400.0])
    rows = rc.recover_rslts()
    prompt = [r for r in rows if _is_prompt_row(r)]
    assert [(r[1], r[2], r[6], r[7]) for r in prompt] == [
        (2.0, 400.0, to_name, _kv(ch_idx, 2.0, 400.0))
        for ch_idx, to_name in enumerate(_PROMPT_TO)]


def test_prompt_rows_edge_cases(tmp_path, monkeypatch) -> None:
    """S6: to_name comes from the fixed set, never from the file (records
    with tampered product_fragments, hot_fragment and thermalised still
    pass the check and give the same names). S7: an all-zero channel is
    stored (4 rows at 0.0), a single zero cell keeps its row. S8: products
    keep mechanalyzer's order (bimolecular F+E gives D+F+E__prompt, not
    sorted)."""
    _tmp_root = tmp_path
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)

    # -- S6 to_name from the fixed set
    def _tamper(doc: dict) -> None:
        for record in doc['channels']:
            record['product_fragments'] = ['X', 'Y']
            record['hot_fragment'] = 'Z'
            record['thermalised'] = not record['thermalised']

    rc = _prompt_rc(_tmp_root / 's6', q_sys=_RecoverQueue())
    _outputs_present(rc)
    _write_rates(rc, tamper=_tamper)
    prompt = [r for r in rc.recover_rslts() if _is_prompt_row(r)]
    assert [r[6] for r in prompt] == _PROMPT_TO * 4

    # -- S7 zero channels stored
    def _zero(ch_idx: int, p: float, t: float) -> float:
        if ch_idx == 1:
            return 0.0
        return 0.0 if (p, t) == (2.0, 300.0) else _kv(ch_idx, p, t)

    rc = _prompt_rc(_tmp_root / 's7', q_sys=_RecoverQueue())
    _outputs_present(rc)
    _write_rates(rc, k_of=_zero)
    prompt = [r for r in rc.recover_rslts() if _is_prompt_row(r)]
    assert len(prompt) == 8
    assert [r[7] for r in prompt if r[6] == 'D+E+F__prompt'] == [0.0] * 4
    assert {(r[1], r[2]): r[7] for r in prompt
            if r[6] == 'C+D__prompt'}[(2.0, 300.0)] == 0.0

    # -- S8 products in mechanalyzer order
    rc = _prompt_rc(_tmp_root / 's8', q_sys=_RecoverQueue(),
                    sop=_PromptSOP(bimol=('F', 'E')))
    _outputs_present(rc)
    _write_rates(rc)
    prompt = [r for r in rc.recover_rslts() if _is_prompt_row(r)]
    assert sorted({r[6] for r in prompt}) == ['C+D__prompt',
                                              'D+F+E__prompt']


# ---------------------------------------------------------------------------
# Prompt KIN rows: ids
# ---------------------------------------------------------------------------
def test_prompt_row_ids(tmp_path, monkeypatch) -> None:
    """I1: optimisation run, model 3: prompt id of channel c at (pidx, tidx)
    = PROMPT_KIN_ROWID_BASE + 3*n_p*n_t*n_ch + (pidx*n_t + tidx)*n_ch + c,
    with PROMPT_KIN_ROWID_BASE = PP_KIN_ROWID_BASE // 2. I2: the thermal
    ids keep today's layout (3*n_p*n_t*n_pairs + ...) with prompt mode off
    and on. I4: kmopp takes every id (thermal and prompt) from one
    pp_row_ids call whose keys are the rows' natural keys, suffixed
    to_names included; no band id."""
    import kimeco.rate_coef as rate_coef
    base = rate_coef.PROMPT_KIN_ROWID_BASE
    assert base == PP_KIN_ROWID_BASE // 2 == 5 * 10**11
    _tmp_root = tmp_path
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    n_p = n_t = n_ch = 2
    # -- I1 + I2, model 3
    for prompt in (True, False):
        rc = _prompt_rc(_tmp_root / f'model3_{prompt}', model_id=3,
                        q_sys=_RecoverQueue(), prompt_reactions=prompt)
        _outputs_present(rc)
        if prompt:
            _write_rates(rc)
        rows = rc.recover_rslts()
        thermal = {(r[1], r[2], r[4], r[5], r[6]): r[0] for r in rows
                   if not _is_prompt_row(r)}
        assert thermal == {
            (p, t, 0, 'A', 'B'): 3 * n_p * n_t * 1 + (pidx * n_t + tidx)
            for pidx, p in enumerate(rc.pres)
            for tidx, t in enumerate(rc.temp)}
        got = {(r[1], r[2], r[6]): r[0] for r in rows if _is_prompt_row(r)}
        expected = {
            (p, t, to_name): (base + 3 * n_p * n_t * n_ch
                              + (pidx * n_t + tidx) * n_ch + ch_idx)
            for pidx, p in enumerate(rc.pres)
            for tidx, t in enumerate(rc.temp)
            for ch_idx, to_name in enumerate(_PROMPT_TO)}
        assert got == (expected if prompt else {})

    # -- I4 kmopp ids from pp_row_ids
    db = _RecordingKinDB(_PARTIAL_ROWS)
    rc = _prompt_rc(_tmp_root / 'kmopp', postprocess=True, db=db,
                    q_sys=_RecoverQueue())
    rc.table = 'G0000'
    rc.missing_grid = [(1.0, 400.0)]
    _outputs_present(rc)
    _write_rates(rc)
    rows = rc.recover_rslts()
    assert len(db.pp_calls) == 1
    table, kin_id, keys = db.pp_calls[0]
    assert (table, kin_id) == ('G0000', 0)
    assert keys == [(1.0, 400.0, 0, 'A', 'B'),
                    (1.0, 400.0, 0, 'A+B', 'C+D__prompt'),
                    (1.0, 400.0, 0, 'A+B', 'D+E+F__prompt')]
    assert keys == [(r[1], r[2], r[4], r[5], r[6]) for r in rows]
    assert [r[0] for r in rows] == [PP_KIN_ROWID_BASE + i for i in range(3)]


@pytest.mark.parametrize(
    'pairs, last_ok, last_index, limit_name',
    [(None, 62_499_999_999, -1, 'PP_KIN_ROWID_BASE'),
     (_PAIRS4, 31_249_999_999, 15, 'PROMPT_KIN_ROWID_BASE')],
    ids=['prompt_side', 'thermal_side'])
def test_prompt_row_id_guard(tmp_path, monkeypatch, pairs, last_ok,
                             last_index, limit_name) -> None:
    """I5/I6: real constants. Prompt side (n_pairs 1, n_ch 2, 4 cells):
    model 62_499_999_999 passes and its last prompt id is
    PP_KIN_ROWID_BASE - 1; one more model raises PromptRatesError. Thermal
    side (n_pairs 4): model 31_249_999_999 passes with its last thermal id
    PROMPT_KIN_ROWID_BASE - 1; one more raises. I7: outside prompt mode
    the same too-large model returns its rows (no guard, same layout)."""
    import kimeco.rate_coef as rate_coef
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    sop_args = {} if pairs is None else {'pairs': pairs}
    limit = getattr(rate_coef, limit_name)
    n_pairs = len(pairs or [0])
    # -- last model that fits: its last id is the limit minus one
    rc = _prompt_rc(tmp_path / 'ok', model_id=last_ok,
                    sop=_PromptSOP(**sop_args), q_sys=_RecoverQueue())
    _outputs_present(rc)
    _write_rates(rc)
    rows = rc.recover_rslts()
    assert rows[last_index][0] == limit - 1
    assert len({r[0] for r in rows}) == len(rows) == 4 * n_pairs + 8
    # -- one model more: PromptRatesError naming the model
    too_big = last_ok + 1
    rc = _prompt_rc(tmp_path / 'too_big', model_id=too_big,
                    sop=_PromptSOP(**sop_args), q_sys=_RecoverQueue())
    _outputs_present(rc)
    _write_rates(rc)
    with pytest.raises(PromptRatesError) as exc:
        rc.recover_rslts()
    assert f'model {too_big}' in str(exc.value)
    assert str(limit) in str(exc.value)
    # -- I7 prompt mode off: no guard, thermal layout unchanged
    rc = _prompt_rc(tmp_path / 'plain', model_id=too_big,
                    sop=_PromptSOP(**sop_args), q_sys=_RecoverQueue(),
                    prompt_reactions=False)
    _outputs_present(rc)
    rows = rc.recover_rslts()
    assert [r[0] for r in rows] == [too_big * 4 * n_pairs + i
                                    for i in range(4 * n_pairs)]


# ---------------------------------------------------------------------------
# is_in_db / missing_grid with prompt rows
# ---------------------------------------------------------------------------
def _cell_rows(p: float, t: float, n_thermal: int, n_prompt: int) -> list:
    thermal = [(p, t, 0, 'A', f'B{i}' if i else 'B', 1.0)
               for i in range(n_thermal)]
    prompt = [(p, t, 0, 'A+B', f'P{i}__prompt', 1e-13)
              for i in range(n_prompt)]
    return thermal + prompt


@pytest.mark.parametrize('prompt, rows, missing', [
    (True, _PROMPT_FULL_ROWS, []),
    (True, _FULL_ROWS, _GRID),
    (True, [r for p, t in _GRID for r in _cell_rows(p, t, 0, 3)], _GRID),
    (True, [r for p, t in _GRID for r in _cell_rows(p, t, 3, 0)], _GRID),
    (True, _cell_rows(1.0, 300.0, 1, 2) + _cell_rows(1.0, 400.0, 1, 1)
     + _cell_rows(2.0, 300.0, 1, 0) + _cell_rows(2.0, 400.0, 1, 0),
     [(1.0, 400.0), (2.0, 300.0), (2.0, 400.0)]),
    (False, _PROMPT_FULL_ROWS, []),
    (False, [r for r in _PROMPT_FULL_ROWS if r[4].endswith('__prompt')],
     _GRID),
], ids=['D1_prompt_full', 'D2_thermal_only', 'D3_prompt_rows_only',
        'D4_extra_thermal_no_prompt', 'D5_mixed_grid',
        'D6_plain_reads_prompt_db', 'D7_plain_prompt_rows_only'])
def test_prompt_is_in_db_counts_thermal_and_prompt_rows(
        tmp_path, prompt, rows, missing) -> None:
    """D1-D7: a cell is present when it holds n_pairs (1) thermal rows and,
    in prompt mode, n_channels (2) prompt rows, counted apart: prompt rows
    never fill a thermal gap nor thermal rows a prompt gap (a summed
    n_pairs + n_ch count would accept D3/D4); outside prompt mode the
    prompt rows are ignored (D6 complete, D7 missing everywhere)."""
    rc = _prompt_rc(tmp_path, rows=rows, prompt_reactions=prompt)
    assert rc.is_in_db(table='G0000') is (missing == [])
    assert rc.missing_grid == missing


# ---------------------------------------------------------------------------
# Duplicate prompt keys, missing .out, absent grid value, Cantera arrays
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('postprocess', [False, True],
                         ids=['optimisation', 'kmopp'])
@pytest.mark.parametrize('sop_args, clash, no_clash', [
    ({'hot_pes_ids': (1, 2)}, 'to_name C+D__prompt', None),
    ({'ped_species': ('A+B=C+D', 'A+B=D+C')}, 'to_name D+E+F__prompt',
     'to_name C+D__prompt'),
], ids=['two_hot_pes', 'swapped_ped_product'])
def test_prompt_duplicate_key_stops(tmp_path, monkeypatch, postprocess,
                                    sop_args, clash, no_clash) -> None:
    """U1: two channels with the same (PED PES, PED reactant, to_name) stop
    recover_rslts with PromptRatesError naming the to_name and PES 0, in
    both modes and before any id is asked from the DB: a PED product hot
    in two hot PESs (both channels duplicated), or A+B=C+D next to
    A+B=D+C (only D+E+F__prompt clashes, C+D and D+C differ)."""
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    db = _RecordingKinDB(_PARTIAL_ROWS)
    rc = _prompt_rc(tmp_path, postprocess=postprocess, db=db,
                    sop=_PromptSOP(**sop_args), q_sys=_RecoverQueue())
    if postprocess:
        rc.table = 'G0000'
        rc.missing_grid = [(1.0, 400.0)]
    _outputs_present(rc)
    _write_rates(rc)
    with pytest.raises(PromptRatesError) as exc:
        rc.recover_rslts()
    message = str(exc.value)
    assert clash in message and 'PES 0' in message
    assert 'G0000E0000' in message
    if no_clash:
        assert no_clash not in message
    assert db.pp_calls == []


def test_prompt_missing_out_and_absent_grid_value(tmp_path,
                                                  monkeypatch) -> None:
    """E1: prompt mode, valid file, a .out missing (all, or slot 1 only):
    recover_rslts still returns [] (no prompt row, no raise). E2: a grid
    value absent from the file's grid raises PromptRatesError naming the
    value and the model (not a bare KeyError)."""
    _tmp_root = tmp_path
    monkeypatch.setattr('kimeco.rate_coef.time.sleep', lambda s: None)
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    # -- E1
    for present in ([], [0]):
        rc = _prompt_rc(_tmp_root / f'e1_{len(present)}',
                        q_sys=_RecoverQueue())
        _write_rates(rc)
        for slot in present:
            Path(rc.output_names[slot]).write_text('ok')
        assert rc.recover_rslts() == []
    # -- E2
    rc = _prompt_rc(_tmp_root / 'e2', q_sys=_RecoverQueue())
    content = _write_rates(rc, pressures=[1.0, 3.0])
    with pytest.raises(PromptRatesError) as exc:
        rc._prompt_rows(content=content, n_pairs=1, partial=False,
                        missing=set())
    assert 'P = 2.0 bar' in str(exc.value)
    assert 'model 0' in str(exc.value)


def test_prompt_rows_never_reach_rate_arrays(tmp_path, monkeypatch) -> None:
    """C1: load_rates_from_db (the arrays the Cantera input is built from)
    gives the same tbl_map_by_pes and rc_by_pes from the rows of a prompt
    run as from its thermal rows only; an adversarial row A -> B__prompt
    changes nothing."""
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    rc = _prompt_rc(tmp_path, q_sys=_RecoverQueue())
    _outputs_present(rc)
    _write_rates(rc, k_of=_kv)
    # KIN_DB.get_rates_for_kin_id layout: (P, T, pes_id, from, to, k)
    rows = [(r[1], r[2], *r[4:]) for r in rc.recover_rslts()]
    rows.append((1.0, 300.0, 0, 'A', 'B__prompt', 9.9))
    thermal = [r for r in rows if not r[4].endswith(PROMPT_TO_NAME_SUFFIX)]
    assert len(thermal) == 4 and len(rows) == 4 + 8 + 1
    arrays = []
    for db_rows in (rows, thermal):
        rc.db = cast(Any, _FakeKinDB(db_rows))
        rc.load_rates_from_db(table='G0000')
        arrays.append((dict(rc.tbl_map_by_pes), dict(rc.rc_by_pes)))
    (maps, rcs), (maps_ref, rcs_ref) = arrays
    assert maps == maps_ref
    assert rcs.keys() == rcs_ref.keys()
    assert all(np.array_equal(rcs[k], rcs_ref[k]) for k in rcs)
    assert rcs[0][0, 0, 0, 1] == 10.0
