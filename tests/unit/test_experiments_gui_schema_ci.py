from kimeco.gui.input_sections.experiments_section import (
    _make_empty_experiment,
)
from kimeco.gui.input_sections.save_load_write_section import (
    _build_experiments_user_settings,
)


def test_empty_experiment_store_has_no_per_experiment_scoring_func() -> None:
    exp = _make_empty_experiment(1)

    assert "scoring_func" not in exp


def test_written_experiment_payload_drops_legacy_scoring_func() -> None:
    experiments_store = [
        {
            "id": 1,
            "temp": 1000.0,
            "pres": 760.0,
            "weight": 1.0,
            "pres_unit": "torr",
            "cantera_tpl": "template.cti",
            "scoring_func": "weighteddif",
            "data_file": "exp.csv",
            "error_file": "err.csv",
            "init_mode": "ratio",
            "init_value": "H2:0.5, O2:0.5",
            "w_species": {"OH": 2.0},
        }
    ]

    payload = _build_experiments_user_settings(experiments_store)

    assert len(payload) == 1
    assert "scoring_func" not in payload[0]
