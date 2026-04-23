from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather

from kimeco.database.sim_db import SIM_DB
from kimeco.gui.simsection import SIMSection


def _blob_from_dict(data: dict[str, list[float]]) -> bytes:
    table = pa.table(data)
    sink = pa.BufferOutputStream()
    feather.write_feather(table, sink)
    return sink.getvalue().to_pybytes()


def test_make_figure_uses_nested_sim_db_results_for_species_trace() -> None:
    section = SIMSection.__new__(SIMSection)
    section.settings = {
        'pres_unit': 'atm',
        'rc_pres': [1.0],
        'rc_temp': [300.0],
        'experiments': [
            SimpleNamespace(
                P=1.0,
                T=300.0,
                species=['A'],
                data=np.array([[0.0, 1.0], [1.0, 0.25]], dtype=float),
                error=np.array([[0.0, 1.0], [0.1, 0.1]], dtype=float),
            )
        ],
    }

    rows = np.array(
        [
            [7.0, 0.0, 1.0],
            [7.0, 1.0, 0.25],
        ],
        dtype=float,
    )
    rendered = section.make_figure(
        gen_name='G0000',
        TPGenSP={'G0000': {7: {0: rows}}},
        sp='A',
        pres=1.0,
        temp=300.0,
        sim_db=SimpleNamespace(sv_species=['A']),
        show_exp_profile=False,
    )

    fig = rendered[-1].figure

    assert len(fig.data) == 1
    assert list(fig.data[0].x) == [0.0, 1.0]
    assert list(fig.data[0].y) == [1.0, 0.25]


def test_get_pp_condition_profiles_filters_by_experiment_id(
    tmp_path: Path,
) -> None:
    pp_db = SIM_DB(name='TEST_PP_SIM_DB', path=str(tmp_path), threads=1)
    pp_db.create_new_table(name='G0000')
    pp_db.prepare_batch_upsert(
        table='G0000',
        model_id=3,
        experiment_id=0,
        result=_blob_from_dict({'time': [0.0], 'A': [1.0]}),
    )
    pp_db.prepare_batch_upsert(
        table='G0000',
        model_id=3,
        experiment_id=1,
        result=_blob_from_dict({'time': [0.0], 'A': [2.0]}),
    )
    pp_db.batch_upsert()

    section = SIMSection.__new__(SIMSection)
    section.pp_sim_db = pp_db
    section.settings = {
        'pp_pres': [1.0],
        'pp_temp': [300.0, 400.0],
    }

    out = section.get_pp_condition_profiles(
        tables=['G0000'],
        p_idx=0,
        t_idx=1,
    )

    assert sorted(out['G0000']) == [3]
    assert sorted(out['G0000'][3]) == [1]
    assert out['G0000'][3][1][0, 2] == 2.0
