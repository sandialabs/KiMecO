from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.feather as feather
import pytest

from kimeco.database.sim_db import SIM_DB


def _blob_from_dict(data: dict[str, list[float]]) -> bytes:
    table = pa.table(data)
    sink = pa.BufferOutputStream()
    feather.write_feather(table, sink)
    return sink.getvalue().to_pybytes()


def test_sim_db_blob_roundtrip_preserves_profile_shape(tmp_path: Path) -> None:
    db = SIM_DB(name='TEST_DB_SIM', path=str(tmp_path), threads=1)
    table_name = 'G0000'
    db.create_new_table(name=table_name)

    blob = _blob_from_dict(
        {
            'time': [0.0, 1.0, 2.0],
            'A': [1.0, 0.5, 0.25],
            'B': [0.0, 0.1, 0.2],
        }
    )

    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=7,
        experiment_id=1,
        result=blob,
    )
    db.batch_upsert()

    db.prepare_batch_select(table=table_name, mdl_id=7, experiment_id=1)
    out = db.batch_select()

    assert table_name in out
    assert 7 in out[table_name]
    assert 1 in out[table_name][7]
    rows = out[table_name][7][1]

    # decoded shape: [n_steps, mdl_id + time + species]
    assert rows.shape == (3, 4)
    assert rows[:, 0].tolist() == [7.0, 7.0, 7.0]
    assert rows[:, 1].tolist() == [0.0, 1.0, 2.0]


def test_sim_db_blob_upsert_replaces_same_model_experiment(
    tmp_path: Path,
) -> None:
    db = SIM_DB(name='TEST_DB_SIM_UPSERT', path=str(tmp_path), threads=1)
    table_name = 'G0000'
    db.create_new_table(name=table_name)

    old_blob = _blob_from_dict({'time': [0.0], 'A': [1.0]})
    new_blob = _blob_from_dict({'time': [0.0], 'A': [2.0]})

    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=3,
        experiment_id=0,
        result=old_blob,
    )
    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=3,
        experiment_id=0,
        result=new_blob,
    )
    db.batch_upsert()

    db.prepare_batch_select(table=table_name, mdl_id=3, experiment_id=0)
    out = db.batch_select()
    rows = out[table_name][3][0]
    assert rows[0, 2] == 2.0


def test_sim_db_batch_select_groups_rows_by_model_and_experiment(
    tmp_path: Path,
) -> None:
    db = SIM_DB(name='TEST_DB_SIM_SELECT', path=str(tmp_path), threads=1)
    table_name = 'G0000'
    db.create_new_table(name=table_name)

    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=2,
        experiment_id=0,
        result=_blob_from_dict({'time': [0.0, 1.0], 'A': [1.0, 0.8]}),
    )
    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=2,
        experiment_id=1,
        result=_blob_from_dict({'time': [0.0, 1.0], 'A': [0.4, 0.2]}),
    )
    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=5,
        experiment_id=0,
        result=_blob_from_dict({'time': [0.0, 1.0], 'A': [2.0, 1.5]}),
    )
    db.batch_upsert()

    db.prepare_batch_select(table=table_name, mdl_id=2, experiment_id=0)
    db.prepare_batch_select(table=table_name, mdl_id=2, experiment_id=1)
    db.prepare_batch_select(table=table_name, mdl_id=5, experiment_id=0)

    out = db.batch_select()

    assert sorted(out[table_name]) == [2, 5]
    assert sorted(out[table_name][2]) == [0, 1]
    assert sorted(out[table_name][5]) == [0]
    assert out[table_name][2][1][:, 2].tolist() == [0.4, 0.2]
    assert db.sv_species == ['A']


def test_sim_db_batch_upsert_creates_table_on_demand(tmp_path: Path) -> None:
    db = SIM_DB(name='TEST_DB_SIM_CREATE', path=str(tmp_path), threads=1)
    table_name = 'G0042'

    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=11,
        experiment_id=3,
        result=_blob_from_dict({'time': [0.0], 'A': [9.0]}),
    )
    db.batch_upsert()

    assert db.table_exists(table_name)

    db.prepare_batch_select(table=table_name, mdl_id=11, experiment_id=3)
    out = db.batch_select()

    assert out[table_name][11][3][0, 2] == 9.0


def test_sim_db_batch_select_returns_empty_when_no_requests(
    tmp_path: Path,
) -> None:
    db = SIM_DB(name='TEST_DB_SIM_EMPTY', path=str(tmp_path), threads=1)

    assert db.batch_select() == {}


def test_decode_result_blob_requires_time_column() -> None:
    blob = _blob_from_dict({'A': [1.0, 2.0]})

    with pytest.raises(ValueError, match='missing required time column'):
        SIM_DB.decode_result_blob(result=blob, mdl_id=1)


def test_get_single_result_decodes_one_row(tmp_path: Path) -> None:
    db = SIM_DB(name='TEST_DB_SIM_SINGLE', path=str(tmp_path), threads=1)
    table_name = 'G0000'
    db.create_new_table(name=table_name)

    db.prepare_batch_upsert(
        table=table_name,
        mdl_id=4,
        experiment_id=2,
        result=_blob_from_dict(
            {'time': [0.0, 1.0], 'A': [1.0, 0.5], 'B': [0.0, 0.3]}),
    )
    db.batch_upsert()

    result = db.get_single_result(
        table=table_name, mdl_id=4, experiment_id=2)

    assert result is not None
    decoded, species = result
    assert species == ['A', 'B']
    assert decoded.shape == (2, 4)
    assert decoded[:, 0].tolist() == [4.0, 4.0]
    assert decoded[:, 1].tolist() == [0.0, 1.0]
    assert decoded[:, 3].tolist() == [0.0, 0.3]


def test_get_single_result_missing_row_returns_none(tmp_path: Path) -> None:
    db = SIM_DB(name='TEST_DB_SIM_SINGLE_MISS', path=str(tmp_path), threads=1)
    table_name = 'G0000'
    db.create_new_table(name=table_name)

    assert db.get_single_result(
        table=table_name, mdl_id=99, experiment_id=0) is None
