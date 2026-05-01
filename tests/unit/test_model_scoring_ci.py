from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from kimeco.model import Model


def _sop(
    parameters: dict[str, float],
    uncertainties: dict[str, float],
    scores: dict[str, float],
):
    return SimpleNamespace(
        pres=[1.0],
        temp=[300.0],
        parameters_names=parameters,
        uncertainties=uncertainties,
        scores=scores,
    )


@pytest.fixture(autouse=True)
def _reset_scoring() -> None:
    Model._score_reference_values = {}
    Model._score_reference_uncertainties = {}
    Model._score_active_params = []
    Model._score_weight_theory = 0.5
    Model._score_weight_experiments = 0.5


def test_model_score_combines_experiment_and_theory_terms() -> None:
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={"exp_0": 0.0, "exp_1": 0.0},
    )
    Model.configure_scoring(
        reference_sop=cast(Any, reference),
        settings={"active_p": ["A__we"], "weight_theory": 1.0, "weight_experiments": 3.0},
    )
    mdl = Model(
        sop=cast(Any, _sop(
            parameters={"A__we": 12.0},
            uncertainties={"A__we": 2.0},
            scores={"exp_0": 2.0, "exp_1": 6.0},
        )),
        id=0,
    )

    assert mdl.theory_score == pytest.approx(1.0)
    assert mdl.experiment_score == pytest.approx(4.0)
    assert mdl.score == pytest.approx(3.25)

def test_model_score_falls_back_to_experiment_only_without_theory_context() -> None:
    mdl = Model(
        sop=cast(Any, _sop(
            parameters={"A__we": 2.0},
            uncertainties={"A__we": 1.0},
            scores={"exp_0": 3.0, "exp_1": 5.0},
        )),
        id=3,
    )

    assert mdl.experiment_score == pytest.approx(4.0)
    assert mdl.theory_score == pytest.approx(0.0)
    assert mdl.score == pytest.approx(4.0)

def test_model_theory_score_scales_percent_and_multiplicative_types() -> None:
    reference = _sop(
        parameters={"__sigma0": 10.0, "TS__if": 100.0},
        uncertainties={"__sigma0": 0.1, "TS__if": 1.2},
        scores={"exp_0": 0.0},
    )
    Model.configure_scoring(
        reference_sop=cast(Any, reference),
        settings={
            "active_p": ["__sigma0", "TS__if"],
            "weight_theory": 1.0,
            "weight_experiments": 0.0,
        },
    )
    mdl = Model(
        sop=cast(Any, _sop(
            parameters={"__sigma0": 11.0, "TS__if": 120.0},
            uncertainties={"__sigma0": 0.1, "TS__if": 1.2},
            scores={"exp_0": 5.0},
        )),
        id=1,
    )

    assert mdl.theory_score == pytest.approx(2.0)
    assert mdl.score == pytest.approx(2.0)


def test_model_score_uses_equal_split_when_both_weights_are_zero() -> None:
    reference = _sop(
        parameters={"A__we": 1.0},
        uncertainties={"A__we": 1.0},
        scores={"exp_0": 0.0},
    )
    Model.configure_scoring(
        reference_sop=cast(Any, reference),
        settings={"active_p": ["A__we"], "weight_theory": 0.0, "weight_experiments": 0.0},
    )
    mdl = Model(
        sop=cast(Any, _sop(
            parameters={"A__we": 2.0},
            uncertainties={"A__we": 1.0},
            scores={"exp_0": 3.0},
        )),
        id=2,
    )

    assert mdl.theory_score == pytest.approx(1.0)
    assert mdl.experiment_score == pytest.approx(3.0)
    assert mdl.score == pytest.approx(2.0)