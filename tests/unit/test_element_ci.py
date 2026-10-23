"""CI-safe tests for ``Element`` (``Model``) persistence: ``save_kin``
branches against a KIN_DB double, and SIM_DB profile I/O (``request_sim_profiles``,
``save_sim``) including the ``sim_offset`` banding that keeps the experiment
rows of several ensembles sharing one table apart.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.database.sim_db import SIM_DB
from kimeco.enums import ModelStatus
from kimeco.model import Model
from kimeco.q_sys import JobStatus


# ===========================================================================
# save_kin
# ===========================================================================
class DummyKINDB:
    def __init__(self) -> None:
        self.columns = ["pres", "temp"]
        self.upserts = []

    def prepare_batch_upsert(self, table: str, id: int, values: dict) -> None:
        self.upserts.append((table, id, values))


class DummyRateCo:
    def __init__(self, rows, status: JobStatus) -> None:
        self._rows = rows
        self.status = status

    def recover_rslts(self):
        return self._rows


def _kin_model() -> Model:
    sop = SimpleNamespace(pres=[1.0], temp=[300.0])
    return Model(sop=cast(Any, sop), id=0, status=ModelStatus.SOP.value)


def test_save_kin_branches() -> None:
    """Empty rows and a job still running: wait; empty rows and a failed job:
    reset; results present: write the rows and set KIN."""
    # -- test_save_kin_waits_when_rows_empty_and_job_not_failed
    mdl = _kin_model()
    db = DummyKINDB()
    mdl.rateCoef = cast(Any, DummyRateCo(rows=[], status=JobStatus.NOT_IN_QUEUE))

    mdl.save_kin(db=cast(Any, db), table="G0000")

    assert mdl.status == ModelStatus.SOP
    assert db.upserts == []

    # -- test_save_kin_resets_when_rows_empty_and_job_failed
    mdl = _kin_model()
    db = DummyKINDB()
    mdl.rateCoef = cast(Any, DummyRateCo(rows=[], status=JobStatus.FAILED))

    mdl.save_kin(db=cast(Any, db), table="G0000")

    assert mdl.status == ModelStatus.RESET
    assert db.upserts == []

    # -- test_save_kin_sets_kin_and_writes_rows_when_results_present
    mdl = _kin_model()
    db = DummyKINDB()
    mdl.rateCoef = cast(Any, DummyRateCo(rows=[(10, 1.0, 300.0)], status=JobStatus.FINISHED))

    mdl.save_kin(db=cast(Any, db), table="G0000")

    assert mdl.status == ModelStatus.KIN
    assert len(db.upserts) == 1
    table, row_id, values = db.upserts[0]
    assert table == "G0000"
    assert row_id == 10
    assert values == {"pres": 1.0, "temp": 300.0}


# ===========================================================================
# SIM_DB profile requests and save_sim
# ===========================================================================
class DummySIMDB:
    def __init__(self) -> None:
        self.requests: list[tuple[str, int, int]] = []

    def prepare_batch_select(
        self,
        table: str,
        mdl_id: int,
        experiment_id: int,
    ) -> None:
        self.requests.append((table, mdl_id, experiment_id))


def _simdb_model() -> Model:
    sop = SimpleNamespace(pres=[1.0], temp=[300.0])
    return Model(sop=cast(Any, sop), id=7, status=ModelStatus.SOP.value)


def test_request_sim_profiles_only_missing(tmp_path) -> None:
    """Only experiments missing from SIM_DB are requested, under their banded
    (offset) ids."""
    _tmp_root = tmp_path
    # -- test_request_sim_profiles_only_queues_missing_experiments
    mdl = _simdb_model()
    mdl.sim = cast(Any, SimpleNamespace(profiles=[None, object(), None]))
    db = DummySIMDB()

    mdl.request_sim_profiles(sim_db=cast(Any, db), table='G0000')

    assert db.requests == [('G0000', 7, 0), ('G0000', 7, 2)]

    # -- test_request_sim_profiles_applies_offset
    tmp_path = _tmp_root / 'test_request_sim_profiles_applies_offset'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_OFF_REQ', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    mdl = _band_model(sim_offset=5, n_exp=2)
    mdl.sim.profiles = [None, None]

    mdl.request_sim_profiles(sim_db=sim_db, table='G0000')

    assert sim_db._select['G0000'] == {(7, 5), (7, 6)}


def test_save_sim_blob_round_trip_and_offset(tmp_path) -> None:
    """save_sim persists one feather blob per experiment that reads back
    identically; the default offset keeps the legacy ids, a sim_offset shifts
    them by n_run + band."""
    _tmp_root = tmp_path
    # -- test_save_sim_persists_blob_roundtrip_for_one_experiment
    tmp_path = _tmp_root / 'test_save_sim_persists_blob_roundtrip_for_one_experiment'
    tmp_path.mkdir(parents=True)
    mdl = _simdb_model()
    db = SIM_DB(name='TEST_ELEMENT_SIM_DB', path=str(tmp_path), threads=1)
    exp = SimpleNamespace(
        species=['A', 'B'],
        data=np.array([[0.0, 1.0, 2.0]], dtype=float),
    )
    mdl.sim = cast(Any, SimpleNamespace(
        settings={'experiments': [exp]},
        profiles=[
            np.array(
                [
                    [0.0, 1.0, 2.0],
                    [1.0, 0.5, 0.25],
                    [0.0, 0.2, 0.4],
                ],
                dtype=float,
            )
        ],
    ))

    mdl.save_sim(db=db, table='G0000', sim_num=0)
    db.batch_upsert()
    db.prepare_batch_select(table='G0000', mdl_id=7, experiment_id=0)

    rows = db.batch_select()['G0000'][7][0]

    assert rows[:, 0].tolist() == [7.0, 7.0, 7.0]
    assert rows[:, 1].tolist() == [0.0, 1.0, 2.0]
    assert rows[:, 2].tolist() == [1.0, 0.5, 0.25]
    assert rows[:, 3].tolist() == [0.0, 0.2, 0.4]

    # -- test_save_sim_default_offset_parity
    tmp_path = _tmp_root / 'test_save_sim_default_offset_parity'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_OFF_DEFAULT', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    mdl = _band_model(sim_offset=0, n_exp=3)

    mdl.save_sim(db=sim_db, table='G0000', sim_num=0)
    mdl.save_sim(db=sim_db, table='G0000', sim_num=2)

    # No offset -> experiment_id equals sim_num.
    assert _band_keys(sim_db, 'G0000') == {(7, 0), (7, 2)}

    # -- test_save_sim_applies_sim_offset
    tmp_path = _tmp_root / 'test_save_sim_applies_sim_offset'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_OFF_APPLY', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    mdl = _band_model(sim_offset=5, n_exp=1)

    mdl.save_sim(db=sim_db, table='G0000', sim_num=0)

    assert _band_keys(sim_db, 'G0000') == {(7, 5)}

    # -- test_save_sim_offset_formula_n_run_plus_band
    tmp_path = _tmp_root / 'test_save_sim_offset_formula_n_run_plus_band'
    tmp_path.mkdir(parents=True)
    # Ensemble e=1 with n_run=3, n_pp=2 -> offset = 3 + 1*2 = 5.
    n_run, n_pp, e = 3, 2, 1
    sim_db = SIM_DB(name='TEST_OFF_FORMULA', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    mdl = _band_model(sim_offset=n_run + e * n_pp, n_exp=2)

    mdl.save_sim(db=sim_db, table='G0000', sim_num=0)
    mdl.save_sim(db=sim_db, table='G0000', sim_num=1)

    assert _band_keys(sim_db, 'G0000') == {(7, 5), (7, 6)}


def test_save_sim_raises_for_missing_profile(tmp_path: Path) -> None:
    mdl = _simdb_model()
    db = SIM_DB(name='TEST_ELEMENT_SIM_DB_MISSING', path=str(tmp_path))
    exp = SimpleNamespace(
        species=['A'],
        data=np.array([[0.0, 1.0]], dtype=float),
    )
    mdl.sim = cast(Any, SimpleNamespace(
        settings={'experiments': [exp]},
        profiles=[None],
    ))

    with pytest.raises(ValueError, match='Missing simulation profile 0'):
        mdl.save_sim(db=db, table='G0000', sim_num=0)


# ===========================================================================
# sim_offset banding
# ===========================================================================
def _band_exp(species=('A',)):
    return SimpleNamespace(
        species=list(species),
        data=np.array([[0.0, 1.0]], dtype=float),  # data[0] == time grid
    )


def _band_model(sim_offset: int, n_exp: int = 1, id: int = 7) -> Model:
    mdl = Model.__new__(Model)
    mdl.id = id
    mdl._sim_offset = sim_offset
    profiles = [np.array([[float(i + 1)] * 2], dtype=float)
                for i in range(n_exp)]
    mdl.sim = cast(Any, SimpleNamespace(
        settings={'experiments': [_band_exp() for _ in range(n_exp)]},
        profiles=profiles,
    ))
    return mdl


def _band_keys(sim_db: SIM_DB, table: str) -> set:
    return set(sim_db._upsert.get(table, {}).keys())


# ---------------------------------------------------------------------------
# save_sim experiment_id mapping
# ---------------------------------------------------------------------------
def test_offset_bands_are_disjoint_and_round_trip(tmp_path) -> None:
    """Band writes leave the original rows untouched, bands are disjoint, two
    ensembles sharing a table never collide, and a banded write reads back."""
    _tmp_root = tmp_path
    # -- test_band_writes_leave_originals_untouched
    tmp_path = _tmp_root / 'test_band_writes_leave_originals_untouched'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_OFF_ORIG', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')

    original = _band_model(sim_offset=0, n_exp=1)
    original.save_sim(db=sim_db, table='G0000', sim_num=0)
    original_blob = sim_db._upsert['G0000'][(7, 0)]

    banded = _band_model(sim_offset=3, n_exp=1)
    banded.save_sim(db=sim_db, table='G0000', sim_num=0)

    # Original row is still present and unchanged; band lands on a new key.
    assert (7, 0) in sim_db._upsert['G0000']
    assert (7, 3) in sim_db._upsert['G0000']
    assert sim_db._upsert['G0000'][(7, 0)] == original_blob

    # -- test_bands_are_disjoint
    tmp_path = _tmp_root / 'test_bands_are_disjoint'
    tmp_path.mkdir(parents=True)
    n_run, n_pp = 3, 2
    sim_db = SIM_DB(name='TEST_OFF_DISJOINT', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')

    band0 = _band_model(sim_offset=n_run + 0 * n_pp, n_exp=2)  # -> 3, 4
    band1 = _band_model(sim_offset=n_run + 1 * n_pp, n_exp=2)  # -> 5, 6
    for sim_num in range(2):
        band0.save_sim(db=sim_db, table='G0000', sim_num=sim_num)
        band1.save_sim(db=sim_db, table='G0000', sim_num=sim_num)

    assert _band_keys(sim_db, 'G0000') == {(7, 3), (7, 4), (7, 5), (7, 6)}

    # -- test_two_ensembles_same_table_no_collision
    tmp_path = _tmp_root / 'test_two_ensembles_same_table_no_collision'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_OFF_NOCOLL', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')

    ens_a = _band_model(sim_offset=3, n_exp=1, id=7)
    ens_b = _band_model(sim_offset=5, n_exp=1, id=7)
    ens_a.save_sim(db=sim_db, table='G0000', sim_num=0)
    ens_b.save_sim(db=sim_db, table='G0000', sim_num=0)

    # Same table + same model id, different offset -> distinct rows.
    assert _band_keys(sim_db, 'G0000') == {(7, 3), (7, 5)}

    # -- test_write_read_round_trip_with_offset
    tmp_path = _tmp_root / 'test_write_read_round_trip_with_offset'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_OFF_RT', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    mdl = _band_model(sim_offset=5, n_exp=1)
    mdl.sim.profiles = [np.array([[1.0, 0.25]], dtype=float)]

    mdl.save_sim(db=sim_db, table='G0000', sim_num=0)
    sim_db.batch_upsert()
    sim_db.prepare_batch_select(table='G0000', mdl_id=7, experiment_id=5)
    out = sim_db.batch_select()

    # Decoded columns are [mdl_id, time, species...]; the offset key resolves.
    arr = out['G0000'][7][5]
    assert arr[:, 1].tolist() == [0.0, 1.0]
    assert arr[:, 2].tolist() == [1.0, 0.25]


# ---------------------------------------------------------------------------
# request_sim_profiles + round trip
# ---------------------------------------------------------------------------

