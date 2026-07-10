from __future__ import annotations

from pathlib import Path

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
    section.pp_sim_db = None
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


def test_export_results_selection_writes_expected_files(
        tmp_path: Path) -> None:
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


def test_export_results_all_writes_every_row(tmp_path: Path) -> None:
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
