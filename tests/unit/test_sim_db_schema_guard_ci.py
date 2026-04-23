from __future__ import annotations

from pathlib import Path

import pytest

from kimeco.database.kimeco_db import Kimeco_db
from kimeco.database.sim_db import SIM_DB


def test_sim_db_rejects_legacy_table_schema(tmp_path: Path) -> None:
    base = Kimeco_db(name='LEGACY_SIM', path=str(tmp_path), threads=1)
    base.create_table(
        name='G0000',
        columns=['sim_id', 'time', 'A'],
        types=[int, float, float],
    )

    with pytest.raises(ValueError, match='Unsupported SIM_DB schema'):
        SIM_DB(name='LEGACY_SIM', path=str(tmp_path), tbl_name='G0000')
