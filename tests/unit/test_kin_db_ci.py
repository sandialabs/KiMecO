"""CI-safe tests for ``KIN_DB`` on a real SQLite file under ``tmp_path``:
``batch_select`` / ``get_rates_for_kin_id`` / ``get_rates_for_models``
filtering, and the postprocessing row-id band (``pp_row_ids``) that keeps
the rows of earlier postprocessing runs and stays unique across threads.
"""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.database.kin_db import KIN_DB, PP_KIN_ROWID_BASE
from kimeco.enums import ModelStatus
from kimeco.logger_config import KMOLogger
from kimeco.model import Model
from kimeco.q_sys import JobStatus
from kimeco.rate_coef import RateCo


# ===========================================================================
# batch_select and rate queries
# ===========================================================================
class DummySOP:
    def __init__(self) -> None:
        self.pes_ids = [0, 1]


def test_batch_select_keeps_unfiltered_rows_when_filtered_request_exists(
    tmp_path: Path,
) -> None:
    kin_db = KIN_DB(
        sop=cast(Any, DummySOP()),
        name="TEST_DB_KIN",
        path=str(tmp_path),
        threads=1,
    )
    table = "G0000"
    kin_db.create_new_table(name=table)

    kin_db.prepare_batch_upsert(
        table=table,
        id=0,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 1.0,
        },
    )
    kin_db.prepare_batch_upsert(
        table=table,
        id=1,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 1,
            "from_name": "A",
            "to_name": "B",
            "k": 2.0,
        },
    )
    kin_db.batch_upsert()

    # Mixed request set: one unfiltered and one filtered on pes_id=1.
    kin_db.prepare_batch_select(
        table=table,
        kin_id=1,
        p=1.0,
        t=300.0,
        from_name="A",
        to_name="B",
    )
    kin_db.prepare_batch_select(
        table=table,
        kin_id=1,
        p=1.0,
        t=300.0,
        from_name="A",
        to_name="B",
        pes_id=1,
    )

    results = kin_db.batch_select()

    kin_results = results[table][1]
    assert (1.0, 300.0, 0, "A", "B") in kin_results
    assert (1.0, 300.0, 1, "A", "B") in kin_results
    assert kin_results[(1.0, 300.0, 0, "A", "B")] == 1.0
    assert kin_results[(1.0, 300.0, 1, "A", "B")] == 2.0


def test_get_rates_for_kin_id_respects_pes_filter(tmp_path: Path) -> None:
    kin_db = KIN_DB(
        sop=cast(Any, DummySOP()),
        name="TEST_DB_KIN_FILTER",
        path=str(tmp_path),
        threads=1,
    )
    table = "G0000"
    kin_db.create_new_table(name=table)

    kin_db.prepare_batch_upsert(
        table=table,
        id=0,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 2,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 1.5,
        },
    )
    kin_db.prepare_batch_upsert(
        table=table,
        id=1,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 2,
            "pes_id": 1,
            "from_name": "A",
            "to_name": "B",
            "k": 2.5,
        },
    )
    kin_db.batch_upsert()

    all_rows = kin_db.get_rates_for_kin_id(table=table, kin_id=2)
    pes1_rows = kin_db.get_rates_for_kin_id(table=table, kin_id=2, pes_id=1)

    assert len(all_rows) == 2
    assert len(pes1_rows) == 1
    assert pes1_rows[0][2] == 1
    assert pes1_rows[0][-1] == 2.5


def test_get_rates_for_models_filters_by_table_ids_and_conditions(
    tmp_path: Path,
) -> None:
    kin_db = KIN_DB(
        sop=cast(Any, DummySOP()),
        name="TEST_DB_KIN_MULTI",
        path=str(tmp_path),
        threads=1,
    )
    g0 = "G0000"
    g1 = "G0001"
    kin_db.create_new_table(name=g0)
    kin_db.create_new_table(name=g1)

    kin_db.prepare_batch_upsert(
        table=g0,
        id=0,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 1.2,
        },
    )
    kin_db.prepare_batch_upsert(
        table=g0,
        id=1,
        values={
            "P": 10.0,
            "T": 300.0,
            "kin_id": 1,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 9.9,
        },
    )
    kin_db.prepare_batch_upsert(
        table=g1,
        id=2,
        values={
            "P": 1.0,
            "T": 300.0,
            "kin_id": 3,
            "pes_id": 0,
            "from_name": "A",
            "to_name": "B",
            "k": 2.4,
        },
    )
    kin_db.batch_upsert()

    rows = kin_db.get_rates_for_models(
        table_to_kin_ids={g0: [1], g1: [3]},
        pres=[1.0],
        temp=[300.0],
        pes_ids=[0],
    )

    assert len(rows) == 2
    assert (g0, 1, 1.0, 300.0, 0, "A", "B", 1.2) in rows
    assert (g1, 3, 1.0, 300.0, 0, "A", "B", 2.4) in rows


# ===========================================================================
# Postprocessing row ids
# ===========================================================================
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
def test_postprocessing_keeps_and_reuses_row_ids(tmp_path, monkeypatch) -> None:
    """A later postprocessing on a larger grid keeps the rows of the earlier
    one; rewriting a partially stored cell reuses its row id."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_larger_grid_keeps_rows_of_earlier_postprocessing
    tmp_path = _tmp_root / 'test_larger_grid_keeps_rows_of_earlier_postprocessing'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
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

    # -- test_rewriting_partially_stored_cell_reuses_its_row_id
    tmp_path = _tmp_root / 'test_rewriting_partially_stored_cell_reuses_its_row_id'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
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


def test_pp_row_ids_start_at_band_base_or_above_stored_and_pending(tmp_path) -> None:
    """New pp row ids start at the band base on an empty or low-band table, and
    above every stored and pending id otherwise."""
    _tmp_root = tmp_path
    # -- test_pp_row_ids_start_at_band_base_on_empty_or_low_band_table
    tmp_path = _tmp_root / 'test_pp_row_ids_start_at_band_base_on_empty_or_low_band_table'
    tmp_path.mkdir(parents=True)
    kin_db = _kin_db(tmp_path)
    # Optimisation-run rows (low ids) only
    kin_db.prepare_batch_upsert(
        table=TABLE, id=7,
        values={'P': 5.0, 'T': 600.0, 'kin_id': 0, 'pes_id': 0,
                'from_name': 'A', 'to_name': 'B', 'k': 1.0})
    kin_db.batch_upsert()

    ids = kin_db.pp_row_ids(table=TABLE, kin_id=0, keys=_keys(3))

    assert ids == [PP_KIN_ROWID_BASE + i for i in range(3)]

    # -- test_pp_row_ids_start_above_stored_and_pending_ids
    tmp_path = _tmp_root / 'test_pp_row_ids_start_above_stored_and_pending_ids'
    tmp_path.mkdir(parents=True)
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


def test_pp_row_ids_reused_and_unique_across_threads(tmp_path) -> None:
    """Stored and pending rows keep their ids; ids handed out concurrently are
    unique across threads."""
    _tmp_root = tmp_path
    # -- test_pp_row_ids_reuse_ids_of_stored_and_pending_rows
    tmp_path = _tmp_root / 'test_pp_row_ids_reuse_ids_of_stored_and_pending_rows'
    tmp_path.mkdir(parents=True)
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

    # -- test_pp_row_ids_are_unique_across_threads
    tmp_path = _tmp_root / 'test_pp_row_ids_are_unique_across_threads'
    tmp_path.mkdir(parents=True)
    kin_db = _kin_db(tmp_path)

    def request(kin_id: int) -> list[int]:
        return kin_db.pp_row_ids(table=TABLE, kin_id=kin_id, keys=_keys(10))

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = [i for chunk in pool.map(request, range(40)) for i in chunk]

    assert len(ids) == len(set(ids)) == 400
    assert min(ids) == PP_KIN_ROWID_BASE



# ===========================================================================
# migrate_legacy_table (wide legacy layout -> long format)
# ===========================================================================
def _legacy_kin_db(tmp_path: Path, name: str, pes_ids: list[int]) -> KIN_DB:
    """Create the legacy tables with sqlite3 first: KIN_DB loads them at init."""
    con = sqlite3.connect(str(tmp_path / f'{name}.db'))
    con.execute('CREATE TABLE G0000 (id INTEGER PRIMARY KEY, P REAL, T REAL, '
                'kin_id INTEGER, specie TEXT, A REAL, B REAL)')
    con.executemany('INSERT INTO G0000 VALUES (?, ?, ?, ?, ?, ?, ?)',
                    [(0, 1.0, 300.0, 1, 'A', 0.0, 2.5),
                     (1, 1.0, 300.0, 1, 'B', None, 0.0)])
    con.execute('CREATE TABLE NOSPEC (id INTEGER PRIMARY KEY, P REAL, T REAL, '
                'kin_id INTEGER, specie TEXT)')
    con.execute('CREATE TABLE NOTLEG (id INTEGER PRIMARY KEY, x REAL)')
    con.commit()
    con.close()
    return KIN_DB(sop=cast(Any, SimpleNamespace(pes_ids=pes_ids)), name=name,
                  path=str(tmp_path), threads=1)


def test_migrate_legacy_table_dry_run_migrate_and_overwrite(tmp_path: Path) -> None:
    db = _legacy_kin_db(tmp_path, 'LEGACY_KIN', [0])
    counts = {'legacy_rows': 2, 'species_columns': 2, 'migrated_rows': 4,
              'nonzero_rows': 1, 'missing_rows': 1}

    assert db.migrate_legacy_table('G0000', dry_run=True) == counts
    assert not db.table_exists('G0000_v2')

    assert db.migrate_legacy_table('G0000') == counts
    rows = sorted(tuple(r) for r in db.get_table('G0000_v2'))
    assert rows == [(0, 1.0, 300.0, 1, 0, 'A', 'A', 0.0),
                    (1, 1.0, 300.0, 1, 0, 'A', 'B', 2.5),
                    (2, 1.0, 300.0, 1, 0, 'B', 'A', 0.0),
                    (3, 1.0, 300.0, 1, 0, 'B', 'B', 0.0)]

    with pytest.raises(ValueError, match='already exists'):
        db.migrate_legacy_table('G0000')
    assert db.migrate_legacy_table('G0000', dry_run=True) == counts
    assert db.migrate_legacy_table('G0000', overwrite=True) == counts
    assert len(db.get_table('G0000_v2')) == 4

    assert db.migrate_legacy_table('G0000', target_table='LEG') == counts
    assert len(db.get_table('LEG')) == 4


def test_migrate_legacy_table_guards(tmp_path: Path) -> None:
    db = _legacy_kin_db(tmp_path, 'LEGACY_KIN_MULTI', [0, 1])
    with pytest.raises(ValueError, match='single-PES'):
        db.migrate_legacy_table('G0000')

    db = _legacy_kin_db(tmp_path, 'LEGACY_KIN_GUARDS', [0])
    for table, msg in (('MISSING', 'does not exist'),
                       ('NOTLEG', 'not a legacy'),
                       ('NOSPEC', 'no species columns')):
        with pytest.raises(ValueError, match=msg):
            db.migrate_legacy_table(table)
