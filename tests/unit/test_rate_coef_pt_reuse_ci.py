from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus
from kimeco.rate_coef import PP_KIN_ROWID_BASE, RateCo


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
def test_is_in_db_true_and_empty_missing_grid_on_full_grid(
        tmp_path: Path) -> None:
    rc = _rateco(tmp_path, _FULL_ROWS)

    assert rc.is_in_db(table='G0000') is True
    assert rc.missing_grid == []


def test_is_in_db_false_and_exact_missing_cells_on_partial(
        tmp_path: Path) -> None:
    rc = _rateco(tmp_path, _PARTIAL_ROWS)

    assert rc.is_in_db(table='G0000') is False
    assert rc.missing_grid == [(1.0, 400.0), (2.0, 300.0)]


# ---------------------------------------------------------------------------
# set_status full-grid parity
# ---------------------------------------------------------------------------
def test_set_status_finished_on_full_grid(tmp_path: Path) -> None:
    rc = _rateco(tmp_path, _FULL_ROWS, q_sys=_StatusQueue())
    Path(rc.loc).mkdir(parents=True, exist_ok=True)
    for output_name in rc.output_names:
        Path(output_name).write_text('ok')

    rc.set_status(table='G0000')

    assert rc.status == JobStatus.FINISHED
    assert rc.missing_grid == []


# ---------------------------------------------------------------------------
# create_input sub-grid
# ---------------------------------------------------------------------------
def test_create_input_writes_only_missing_sub_grid(
        tmp_path: Path, monkeypatch) -> None:
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


def test_create_input_normal_run_passes_full_grid(
        tmp_path: Path, monkeypatch) -> None:
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
def test_recover_rslts_partial_appends_only_missing_cells(
        tmp_path: Path, monkeypatch) -> None:
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


def test_create_input_absent_vs_false_use_automech_byte_identical_inp(
        tmp_path: Path) -> None:
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


def test_recover_rslts_normal_run_writes_full_grid_low_ids(
        tmp_path: Path, monkeypatch) -> None:
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
