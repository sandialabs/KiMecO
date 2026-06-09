from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm


class DummyLogger:
    def info(self, msg: str) -> None:
        _ = msg

    def warning(self, msg: str) -> None:
        _ = msg


class DummySOP:
    def __init__(self) -> None:
        self.pes_ids = [0]

    def species_names_in_pes(self, pes_id: int) -> list[str]:
        assert pes_id == 0
        return ["A", "B"]

    def reaction_iterator(self):
        return iter([(0, "A", "B"), (0, "B", "A")])


class DummyKinDB:
    def __init__(self) -> None:
        self.last_query: dict[str, Any] = {}

    def get_rates_for_models(
        self,
        table_to_kin_ids: dict[str, list[int]],
        pres: list[float] | None = None,
        temp: list[float] | None = None,
        pes_ids: list[int] | None = None,
    ):
        self.last_query = {
            "table_to_kin_ids": table_to_kin_ids,
            "pres": pres,
            "temp": temp,
            "pes_ids": pes_ids,
        }
        rows = []
        for p in pres or []:
            for t in temp or []:
                rows.append(("G0000", 1, p, t, 0, "A", "B", 1.0))
                rows.append(("G0001", 3, p, t, 0, "A", "B", 9.0))
                rows.append(("G0000", 1, p, t, 0, "B", "A", 0.0))
                rows.append(("G0001", 3, p, t, 0, "B", "A", 16.0))
        return rows


class DummyGA(GeneticAlgorithm):
    def create_next_gen(self, gen):
        return {}, []


def test_geometric_mean_and_std_ignores_non_positive() -> None:
    assert DummyGA.geometric_mean_and_std([0.0, -2.0]) is None

    gm, gsd = DummyGA.geometric_mean_and_std([1.0, 9.0]) or (None, None)
    assert gm == pytest.approx(3.0)
    assert gsd == pytest.approx(3.0)


def test_write_ga_rates_output_uses_full_history_filter_and_order(
    tmp_path: Path,
) -> None:
    ga = cast(Any, object.__new__(DummyGA))
    ga.loc = str(tmp_path)
    ga.klog = DummyLogger()
    ga.settings = {
        "postprocess": False,
        "rc_pres": [1.0, 10.0],
        "rc_temp": [300.0, 500.0],
        "pres_unit": "Torr",
        "max_score": 4.0,
    }
    ga._eligible_models_for_rate_output = lambda: (
        [("G0000", 1, 2.0), ("G0001", 3, 1.0)],
        3,
    )
    ga.goats = SimpleNamespace(prefix="G")
    ga.f_mdl = SimpleNamespace(sop=DummySOP())
    ga.kin_db = DummyKinDB()

    out_file = ga.write_ga_rates_output()
    assert out_file.endswith("GA_rates.out")

    # Excluded model (0,2) must not be queried.
    assert ga.kin_db.last_query["table_to_kin_ids"] == {
        "G0000": [1],
        "G0001": [3],
    }

    content = Path(out_file).read_text(encoding="utf-8")

    # Pressure outer loop, temperature inner loop ordering.
    order = [
        "P = 1 Torr | T = 300 K",
        "P = 1 Torr | T = 500 K",
        "P = 10 Torr | T = 300 K",
        "P = 10 Torr | T = 500 K",
    ]
    indices = [content.index(token) for token in order]
    assert indices == sorted(indices)

    lines = content.splitlines()
    first_block_idx = lines.index("P = 1 Torr | T = 300 K")
    header = lines[first_block_idx + 1]
    row_a = lines[first_block_idx + 2]
    row_b = lines[first_block_idx + 3]

    # Column boundaries are fixed-width across rows.
    col2 = header.index("A", 1)
    col3 = header.index("B", col2 + 1)
    assert row_a.startswith("A")
    assert row_b.startswith("B")
    assert row_a[col2:col2 + 1] == "N"
    assert row_a[col3:col3 + 1] == "3"
    assert row_b[col2:col2 + 1] == "1"
    assert row_b[col3:col3 + 1] == "N"

    # First column width follows max-length + 2 rule.
    first_col_width = col2
    assert first_col_width == max(len("from"), len("A"), len("B")) + 2

    assert "3.00e+00 (3.00)" in content
    assert "1.60e+01 (1.00)" in content
