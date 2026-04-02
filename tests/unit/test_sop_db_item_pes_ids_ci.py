from __future__ import annotations

from pathlib import Path
import sqlite3

import numpy as np
import pytest

from kimeco.logger_config import KMOLogger
from kimeco.parameters import SOP
from kimeco.database.sop_db import SOP_DB, SOPItemPesIdsTable


def _build_sop(swapped: bool = False) -> SOP:
    sop = SOP(score_species=[])
    sop.factor = 1.0
    sop.power = 1.0
    sop.temp = []
    sop.pres = []
    sop.pres_unit = 'atm'

    if swapped:
        left_pes_id = 1
        right_pes_id = 0
    else:
        left_pes_id = 0
        right_pes_id = 1

    sop.add_new_well(name='LEFT', pes_id=left_pes_id)
    sop.add_new_well(name='RIGHT', pes_id=right_pes_id)
    sop.check_well(name='LEFT', pes_id=right_pes_id)
    sop.add_new_bimol(name='LEFT+H', pes_id=left_pes_id)
    sop.items['LEFT+H'].add_new_frag(name='LEFT_FRAG')
    sop.items['LEFT_FRAG'] = sop.items['LEFT+H'].fragments[-1]
    sop.add_new_barrier(
        name='TS_LEFT_RIGHT',
        lside='LEFT',
        rside='RIGHT',
        pes_id=right_pes_id,
    )

    for well_name in ('LEFT', 'RIGHT', 'LEFT_FRAG'):
        sop.items[well_name]._freq = np.array([])

    sop.items['TS_LEFT_RIGHT']._freq = np.array([])
    sop.items['TS_LEFT_RIGHT']._energy = 0.0
    sop.items['TS_LEFT_RIGHT'].ifreq = 0.0
    return sop


def test_item_pes_ids_excludes_fragments_and_includes_barriers() -> None:
    sop = _build_sop()

    assert sop.item_pes_ids == {
        'LEFT': (0,),
        'RIGHT': (1,),
        'LEFT+H': (0,),
        'TS_LEFT_RIGHT': (1,),
    }


def test_sop_db_creates_and_loads_item_pes_table(tmp_path: Path) -> None:
    log_file = tmp_path / 'sop_db.log'
    sop = _build_sop()

    db = SOP_DB(
        sop=sop,
        name='TEST_DB_SOP',
        path=str(tmp_path),
        klog=KMOLogger(filename=str(log_file)),
    )

    assert db.has_item_pes_table() is True
    assert db.get_item_pes_ids() == sop.item_pes_ids
    assert SOPItemPesIdsTable.table_name not in db.tables


def test_sop_db_raises_on_item_pes_id_mismatch(tmp_path: Path) -> None:
    log_file = tmp_path / 'sop_db_mismatch.log'
    initial_sop = _build_sop(swapped=False)
    SOP_DB(
        sop=initial_sop,
        name='TEST_DB_SOP',
        path=str(tmp_path),
        klog=KMOLogger(filename=str(log_file)),
    )

    with pytest.raises(ValueError, match='item/PES_ID mapping'):
        SOP_DB(
            sop=_build_sop(swapped=True),
            name='TEST_DB_SOP',
            path=str(tmp_path),
            klog=KMOLogger(filename=str(log_file)),
        )

    assert 'does not match the current input' in log_file.read_text()
    assert 'TS_LEFT_RIGHT' in log_file.read_text()


def test_sop_db_opens_legacy_db_without_item_pes_table(tmp_path: Path) -> None:
    log_file = tmp_path / 'sop_db_legacy.log'
    sop = _build_sop()

    db = SOP_DB(
        sop=sop,
        name='TEST_DB_SOP',
        path=str(tmp_path),
        klog=KMOLogger(filename=str(log_file)),
    )
    db.create_new_table('G0000')

    with sqlite3.connect(tmp_path / 'TEST_DB_SOP.db') as conn:
        conn.execute(f'DROP TABLE {SOPItemPesIdsTable.table_name}')

    legacy_db = SOP_DB(
        sop=sop,
        name='TEST_DB_SOP',
        path=str(tmp_path),
        klog=KMOLogger(filename=str(log_file)),
    )

    assert legacy_db.has_item_pes_table() is False
    assert 'G0000' in legacy_db.tables
    assert SOPItemPesIdsTable.table_name not in legacy_db.tables
