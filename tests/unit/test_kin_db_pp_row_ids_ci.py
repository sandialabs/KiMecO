from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from kimeco.database.kin_db import KIN_DB, PP_KIN_ROWID_BASE
from kimeco.enums import ModelStatus
from kimeco.logger_config import KMOLogger
from kimeco.model import Model
from kimeco.q_sys import JobStatus
from kimeco.rate_coef import RateCo

TABLE = 'G0001'
PAIRS = [(0, 'A', 'B'), (0, 'B', 'A')]


class _FakeSOP:
    """SOP stub; ``tag`` makes the stub MESS rates model-specific."""

    def __init__(self, tag: int) -> None:
        self.tag = tag
        self.pes_ids = [0]
        self.pres: list[float] = []
        self.temp: list[float] = []

    def reaction_iterator(self):
        return iter(PAIRS)

    def species_names_in_pes(self, pes_id: int):
        return ['A', 'B']


def _k(tag: int, p: float, t: float, from_name: str) -> float:
    """Distinct rate for each model, cell and reaction pair."""
    return tag * 1e4 + p * 1e3 + t + (0.5 if from_name == 'B' else 0.0)


class _FakeMOR:
    """MESS output stub on the postprocessing grid of the settings."""

    def __init__(self, filename, settings, sop, klog) -> None:
        pres, temp = settings['pp_pres'], settings['pp_temp']
        self.tbl_map = {'A': 0, 'B': 1}
        self.rc = np.zeros((len(pres), len(temp), 2, 2), dtype=float)
        for pidx, p in enumerate(pres):
            for tidx, t in enumerate(temp):
                self.rc[pidx, tidx, 0, 1] = _k(sop.tag, p, t, 'A')
                self.rc[pidx, tidx, 1, 0] = _k(sop.tag, p, t, 'B')

    def read(self) -> None:
        return None


class _RecoverQueue:
    def pickUp(self, id: int, jtype: str) -> None:
        return None

    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.PICKED_UP


def _kin_db(tmp_path: Path) -> KIN_DB:
    kin_db = KIN_DB(sop=cast(Any, None), name='TEST_DB_KIN',
                    path=str(tmp_path), threads=1)
    kin_db.create_new_table(name=TABLE)
    return kin_db


def _rows(tmp_path: Path) -> dict[int, tuple]:
    """Stored rows as {id: (P, T, kin_id, pes_id, from, to, k)}."""
    with sqlite3.connect(tmp_path / 'TEST_DB_KIN.db') as conn:
        rows = conn.execute(
            f'SELECT id, P, T, kin_id, pes_id, from_name, to_name, k '
            f'FROM "{TABLE}"').fetchall()
    return {row[0]: tuple(row[1:]) for row in rows}


def _seed_pre_fix_layout(kin_db: KIN_DB, kin_ids: list[int],
                         pres: list[float], temp: list[float]) -> None:
    """Rows of an earlier postprocessing, ids laid out as before the fix."""
    n_p, n_t, n_pairs = len(pres), len(temp), len(PAIRS)
    for kin_id in kin_ids:
        for pidx, p in enumerate(pres):
            for tidx, t in enumerate(temp):
                for pair_idx, (pes_id, frm, to) in enumerate(PAIRS):
                    row_id = (PP_KIN_ROWID_BASE
                              + kin_id * n_p * n_t * n_pairs
                              + (pidx * n_t + tidx) * n_pairs + pair_idx)
                    kin_db.prepare_batch_upsert(
                        table=TABLE, id=row_id,
                        values={'P': p, 'T': t, 'kin_id': kin_id,
                                'pes_id': pes_id, 'from_name': frm,
                                'to_name': to, 'k': _k(kin_id, p, t, frm)})
    kin_db.batch_upsert()


def _postprocess(tmp_path: Path, kin_db: KIN_DB, kin_id: int,
                 pres: list[float], temp: list[float]) -> RateCo:
    """Postprocess one model as CoreRun does: is_in_db, then save_kin."""
    settings: dict[str, Any] = {
        'rc_software': 'mess',
        'postprocess': True,
        'rc_pres': [],
        'rc_temp': [],
        'pp_pres': pres,
        'pp_temp': temp,
        'cpu_kin': 1,
        'mem_kin': 500,
    }
    sop = _FakeSOP(tag=kin_id)
    rc = RateCo(
        sop=cast(Any, sop),
        settings=settings,
        software_tpls=[['tpl0']],
        id=kin_id,
        q_idx=kin_id,
        name=f'{TABLE}E{kin_id:04d}',
        loc=str(tmp_path / 'run'),
        q_sys=cast(Any, _RecoverQueue()),
        db=kin_db,
        klog=KMOLogger(filename=str(tmp_path / 'rc.log')),
    )
    rc.is_in_db(table=TABLE)
    Path(rc.loc).mkdir(parents=True, exist_ok=True)
    for output_name in rc.output_names:
        Path(output_name).write_text('ok')
    mdl = Model(sop=cast(Any, sop), id=kin_id,
                status=ModelStatus.SOP.value)
    mdl.rateCoef = rc
    mdl.save_kin(db=kin_db, table=TABLE)
    return rc


# ---------------------------------------------------------------------------
# Regression: a larger postprocessing grid must not overwrite earlier rows
# ---------------------------------------------------------------------------
def test_larger_grid_keeps_rows_of_earlier_postprocessing(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    kin_db = _kin_db(tmp_path)
    kin_ids = [0, 1, 2, 3]
    old_p, old_t = [1.0, 2.0], [300.0, 400.0]
    new_p, new_t = [1.0, 2.0], [200.0, 300.0, 400.0, 500.0]
    _seed_pre_fix_layout(kin_db, kin_ids, old_p, old_t)
    before = _rows(tmp_path)

    # The pre-fix layout of the new grid lands on the seeded rows.
    stride = len(new_p) * len(new_t) * len(PAIRS)
    pre_fix_ids = {PP_KIN_ROWID_BASE + kin_id * stride + i
                   for kin_id in kin_ids for i in range(stride)}
    assert pre_fix_ids & set(before)

    # All models prepared before a single batch upsert, as in CoreRun.run
    for kin_id in kin_ids:
        rc = _postprocess(tmp_path, kin_db, kin_id, new_p, new_t)
        assert sorted(rc.missing_grid) == [
            (p, t) for p in new_p for t in (200.0, 500.0)]
    kin_db.batch_upsert()
    after = _rows(tmp_path)

    # Earlier rows are untouched
    assert {row_id: after[row_id] for row_id in before} == before
    # Every model now holds the full grid once, with its own rates
    keys = [(row[2], row[0], row[1], row[3], row[4], row[5])
            for row in after.values()]
    assert len(keys) == len(set(keys))
    assert len(after) == len(kin_ids) * stride
    for row_id, (p, t, kin_id, _, frm, _, k) in after.items():
        assert row_id >= PP_KIN_ROWID_BASE
        assert k == _k(kin_id, p, t, frm)


def test_rewriting_partially_stored_cell_reuses_its_row_id(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    kin_db = _kin_db(tmp_path)
    _seed_pre_fix_layout(kin_db, [0], [1.0], [300.0, 400.0])
    rows = _rows(tmp_path)
    # Drop the B->A row of (1.0, 300.0): the cell is now incomplete.
    dropped = next(row_id for row_id, row in rows.items()
                   if row[1] == 300.0 and row[4] == 'B')
    kept = next(row_id for row_id, row in rows.items()
                if row[1] == 300.0 and row[4] == 'A')
    with sqlite3.connect(tmp_path / 'TEST_DB_KIN.db') as conn:
        conn.execute(f'DELETE FROM "{TABLE}" WHERE id = ?', (dropped,))

    rc = _postprocess(tmp_path, kin_db, 0, [1.0], [300.0, 400.0])
    kin_db.batch_upsert()

    assert rc.missing_grid == [(1.0, 300.0)]
    cell = {row_id: row for row_id, row in _rows(tmp_path).items()
            if row[1] == 300.0}
    assert len(cell) == len(PAIRS)
    assert kept in cell
    assert dropped not in cell


def test_recover_rslts_partial_without_is_in_db_raises(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr('kimeco.rate_coef.MessOutputReader', _FakeMOR)
    kin_db = _kin_db(tmp_path)
    rc = RateCo(
        sop=cast(Any, _FakeSOP(tag=0)),
        settings={'rc_software': 'mess', 'postprocess': True,
                  'pp_pres': [1.0], 'pp_temp': [300.0],
                  'cpu_kin': 1, 'mem_kin': 500},
        software_tpls=[['tpl0']],
        id=0,
        q_idx=0,
        name=f'{TABLE}E0000',
        loc=str(tmp_path / 'run'),
        q_sys=cast(Any, _RecoverQueue()),
        db=kin_db,
        klog=KMOLogger(filename=str(tmp_path / 'rc.log')),
    )
    rc.missing_grid = [(1.0, 300.0)]
    Path(rc.loc).mkdir(parents=True, exist_ok=True)
    for output_name in rc.output_names:
        Path(output_name).write_text('ok')

    with pytest.raises(RuntimeError, match='is_in_db'):
        rc.recover_rslts()


# ---------------------------------------------------------------------------
# KIN_DB.pp_row_ids
# ---------------------------------------------------------------------------
def _keys(n: int, p: float = 1.0) -> list[tuple[float, float, int, str, str]]:
    return [(p, 300.0 + i, 0, 'A', 'B') for i in range(n)]


def test_pp_row_ids_start_at_band_base_on_empty_or_low_band_table(
        tmp_path: Path) -> None:
    kin_db = _kin_db(tmp_path)
    # Optimisation-run rows (low ids) only
    kin_db.prepare_batch_upsert(
        table=TABLE, id=7,
        values={'P': 5.0, 'T': 600.0, 'kin_id': 0, 'pes_id': 0,
                'from_name': 'A', 'to_name': 'B', 'k': 1.0})
    kin_db.batch_upsert()

    ids = kin_db.pp_row_ids(table=TABLE, kin_id=0, keys=_keys(3))

    assert ids == [PP_KIN_ROWID_BASE + i for i in range(3)]


def test_pp_row_ids_start_above_stored_and_pending_ids(
        tmp_path: Path) -> None:
    kin_db = _kin_db(tmp_path)
    values = {'P': 9.0, 'T': 900.0, 'kin_id': 5, 'pes_id': 0,
              'from_name': 'A', 'to_name': 'B', 'k': 1.0}
    kin_db.prepare_batch_upsert(table=TABLE, id=PP_KIN_ROWID_BASE + 41,
                                values=dict(values))
    kin_db.batch_upsert()
    # Prepared but not upserted yet, id given as a string as in save_kin
    kin_db.prepare_batch_upsert(table=TABLE,
                                id=cast(Any, str(PP_KIN_ROWID_BASE + 100)),
                                values=dict(values, T=950.0))

    ids = kin_db.pp_row_ids(table=TABLE, kin_id=0, keys=_keys(2))

    assert ids == [PP_KIN_ROWID_BASE + 101, PP_KIN_ROWID_BASE + 102]


def test_pp_row_ids_reuse_ids_of_stored_and_pending_rows(
        tmp_path: Path) -> None:
    kin_db = _kin_db(tmp_path)
    keys = _keys(2)
    first = kin_db.pp_row_ids(table=TABLE, kin_id=3, keys=keys)
    # Prepared as save_kin does (numpy strings)
    for row_id, (p, t, pes_id, frm, to) in zip(first, keys):
        row = np.array([row_id, p, t, 3, pes_id, frm, to, 1.0])
        kin_db.prepare_batch_upsert(
            table=TABLE, id=row[0],
            values=dict(zip(kin_db.columns, row[1:])))

    assert kin_db.pp_row_ids(table=TABLE, kin_id=3, keys=keys) == first
    kin_db.batch_upsert()
    assert kin_db.pp_row_ids(table=TABLE, kin_id=3, keys=keys) == first
    # Same cells for another kinetics object get new ids
    other = kin_db.pp_row_ids(table=TABLE, kin_id=4, keys=keys)
    assert not set(other) & set(first)


def test_pp_row_ids_are_unique_across_threads(tmp_path: Path) -> None:
    kin_db = _kin_db(tmp_path)

    def request(kin_id: int) -> list[int]:
        return kin_db.pp_row_ids(table=TABLE, kin_id=kin_id, keys=_keys(10))

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = [i for chunk in pool.map(request, range(40)) for i in chunk]

    assert len(ids) == len(set(ids)) == 400
    assert min(ids) == PP_KIN_ROWID_BASE
