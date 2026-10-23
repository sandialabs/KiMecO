from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather

from kimeco.database.sim_db import SIM_DB
from kimeco.gui.dbsection import DBSection


def _blob_from_dict(data: dict[str, list[float]]) -> bytes:
    table = pa.table(data)
    sink = pa.BufferOutputStream()
    feather.write_feather(table, sink)
    return sink.getvalue().to_pybytes()


def _make_section(tmp_path: Path, db: SIM_DB) -> DBSection:
    section = DBSection.__new__(DBSection)
    section.sim_db = db
    section.settings = {'workdir': str(tmp_path)}
    return section


def _populate(db: SIM_DB, table: str) -> None:
    db.create_new_table(name=table)
    db.prepare_batch_upsert(
        table=table, mdl_id=1, experiment_id=0,
        result=_blob_from_dict(
            {'time': [0.0, 1.0], 'A': [1.0, 0.5], 'B': [0.0, 0.2]}))
    db.prepare_batch_upsert(
        table=table, mdl_id=2, experiment_id=1,
        result=_blob_from_dict(
            {'time': [0.0, 1.0], 'A': [2.0, 1.5], 'B': [0.1, 0.3]}))
    db.batch_upsert()


def test_export_results_selection_and_all(tmp_path) -> None:
    """Exporting a selection writes the expected files; exporting all writes
    every row."""
    _tmp_root = tmp_path
    # -- test_export_results_selection_writes_expected_files
    tmp_path = _tmp_root / 'test_export_results_selection_writes_expected_files'
    tmp_path.mkdir(parents=True)
    db = SIM_DB(name='KMO_DB_SIM', path=str(tmp_path), threads=1)
    _populate(db, 'G0000')
    section = _make_section(tmp_path, db)

    count, folder = section.export_results(
        db_file='KMO_DB_SIM.db', table='G0000', pairs=[(1, 0)])

    assert count == 1
    assert Path(folder) == tmp_path / 'KMO_DB_SIM_G0000'
    csv_path = Path(folder) / 'G0000_1_0.csv'
    assert csv_path.is_file()

    frame = pd.read_csv(csv_path)
    assert list(frame.columns) == ['time', 'A', 'B']
    assert frame['A'].tolist() == [1.0, 0.5]
    assert frame['B'].tolist() == [0.0, 0.2]
    # The unselected row must not be exported.
    assert not (Path(folder) / 'G0000_2_1.csv').exists()

    # -- test_export_results_all_writes_every_row
    tmp_path = _tmp_root / 'test_export_results_all_writes_every_row'
    tmp_path.mkdir(parents=True)
    db = SIM_DB(name='KMO_DB_SIM', path=str(tmp_path), threads=1)
    _populate(db, 'G0000')
    section = _make_section(tmp_path, db)

    count, folder = section.export_results(
        db_file='KMO_DB_SIM.db', table='G0000', pairs=None)

    assert count == 2
    assert (Path(folder) / 'G0000_1_0.csv').is_file()
    assert (Path(folder) / 'G0000_2_1.csv').is_file()


def test_export_results_rejects_non_sim_db(tmp_path: Path) -> None:
    db = SIM_DB(name='KMO_DB_SIM', path=str(tmp_path), threads=1)
    _populate(db, 'G0000')
    section = _make_section(tmp_path, db)

    try:
        section.export_results(
            db_file='KMO_DB_KIN.db', table='G0000', pairs=None)
    except ValueError as exc:
        assert 'not a SIM database' in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError('Expected ValueError for non-SIM database')


# ---------------------------------------------------------------------------
# _experiment_label (offset / band decoding)
# ---------------------------------------------------------------------------
def _label_section(experiments, pp_experiments, n_run) -> DBSection:
    section = DBSection.__new__(DBSection)
    section.sim_db = cast(Any, SimpleNamespace(name='KMO_DB_SIM'))
    section.settings = {
        'experiments': experiments,
        'pp_experiments': pp_experiments,
        'n_run_exp': n_run,
        'pres_unit': 'bar',
    }
    return section


def test_experiment_label() -> None:
    """Labels: regular below n_run, extrapolated for the band, guarded without
    pp experiments."""
    # -- test_experiment_label_regular_below_n_run
    exp = SimpleNamespace(exp_type='Time profile', P=101325.0, T=300.0)
    section = _label_section([exp], [], n_run=1)

    assert section._experiment_label('KMO_DB_SIM.db', 0) == 'Time profile #0'

    # -- test_experiment_label_extrapolated_band
    exp = SimpleNamespace(exp_type='TP', P=101325.0, T=300.0)
    pp = SimpleNamespace(exp_type='PP', P=202650.0, T=500.0)
    section = _label_section([exp], [pp], n_run=1)

    # id = n_run + band*n_pp + local = 1 + 0*1 + 0 -> band 0, local 0.
    label = section._experiment_label('KMO_DB_SIM.db', 1)

    assert 'Extrapolated (band 0)' in label
    assert 'PP' in label
    assert '500 K' in label

    # -- test_experiment_label_guard_no_pp_experiments
    exp = SimpleNamespace(exp_type='TP', P=101325.0, T=300.0)
    section = _label_section([exp], [], n_run=1)

    # n_pp == 0 -> falls back to the generic descriptor.
    assert section._experiment_label('KMO_DB_SIM.db', 5) == 'Simulation #5'


