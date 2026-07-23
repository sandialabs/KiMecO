from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.model import Model
from kimeco.scoring_f.scoring import Scoring, get_parameter_uncertainty_scale


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


def _exp(
    name: str,
    data: np.ndarray,
    error: np.ndarray,
    weight: float = 1.0,
    sp_weights: np.ndarray | None = None,
):
    return SimpleNamespace(
        name=name,
        data=data,
        error=error,
        weight=weight,
        sp_weights=sp_weights,
    )


def test_scoring_sets_model_score_as_mutable_attribute() -> None:
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={"exp_0": float("inf")},
    )
    settings = {
        "active_p": ["A__we"],
        "weight_theory": 1.0,
        "weight_experiments": 3.0,
    }
    exp = _exp(
        name="exp_0",
        data=np.array([[0.0, 1.0], [2.0, 2.0]], dtype=float),
        error=np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float),
    )
    settings["experiments"] = [exp]
    sf = Scoring(settings=settings, initial_SOP=reference)

    mdl = Model(
        sop=cast(Any, _sop(
            parameters={"A__we": 12.0},
            uncertainties={"A__we": 2.0},
            scores={"exp_0": float("inf")},
        )),
        id=0,
    )
    mdl.sim = cast(Any, SimpleNamespace(
        profiles=[np.array([[0.0, 1.0], [2.0, 2.0]], dtype=float)]
    ))

    sf.score(mdl=mdl)

    assert mdl.theory_score == pytest.approx(1.0)
    assert mdl.experiment_score == pytest.approx(0.0)
    assert mdl.score == pytest.approx(0.25)
    assert mdl.sop.scores["exp_0"] == pytest.approx(0.0)


def test_scoring_uses_equal_split_when_global_weights_are_zero() -> None:
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={"exp_0": float("inf")},
    )
    settings = {
        "active_p": ["A__we"],
        "weight_theory": 0.0,
        "weight_experiments": 0.0,
    }
    exp = _exp(
        name="exp_0",
        data=np.array([[0.0, 1.0], [np.sqrt(3.0), np.sqrt(3.0)]], dtype=float),
        error=np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float),
    )
    settings["experiments"] = [exp]
    sf = Scoring(settings=settings, initial_SOP=reference)

    mdl = Model(
        sop=cast(Any, _sop(
            parameters={"A__we": 12.0},
            uncertainties={"A__we": 2.0},
            scores={"exp_0": float("inf")},
        )),
        id=1,
    )
    mdl.sim = cast(Any, SimpleNamespace(
        profiles=[np.array([[0.0, 1.0], [0.0, 0.0]], dtype=float)]
    ))

    sf.score(mdl=mdl)

    assert mdl.theory_score == pytest.approx(1.0)
    assert mdl.experiment_score == pytest.approx(3.0)
    assert mdl.score == pytest.approx(2.0)


def test_uncertainty_scale_scales_percent_and_multiplicative_types() -> None:
    scale_sigma = get_parameter_uncertainty_scale(
        reference_values={"__sigma0": 10.0},
        reference_uncertainties={"__sigma0": 0.1},
        param="__sigma0",
    )
    scale_if = get_parameter_uncertainty_scale(
        reference_values={"TS__if": 100.0},
        reference_uncertainties={"TS__if": 1.2},
        param="TS__if",
    )

    assert scale_sigma == pytest.approx(1.0)
    assert scale_if == pytest.approx(20.0)


def test_scoring_keeps_finite_total_when_active_p_is_empty() -> None:
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={"exp_0": float("inf")},
    )
    settings = {
        "active_p": [],
        "weight_theory": 1.0,
        "weight_experiments": 1.0,
    }
    exp = _exp(
        name="exp_0",
        data=np.array([[0.0, 1.0], [2.0, 2.0]], dtype=float),
        error=np.array([[1.0, 1.0], [1.0, 1.0]], dtype=float),
    )
    settings["experiments"] = [exp]
    sf = Scoring(settings=settings, initial_SOP=reference)

    mdl = Model(
        sop=cast(Any, _sop(
            parameters={"A__we": 12.0},
            uncertainties={"A__we": 2.0},
            scores={"exp_0": float("inf")},
        )),
        id=2,
    )
    mdl.sim = cast(Any, SimpleNamespace(
        profiles=[np.array([[0.0, 1.0], [2.0, 2.0]], dtype=float)]
    ))

    sf.score(mdl=mdl)

    assert mdl.theory_score == pytest.approx(1.0)
    assert np.isfinite(mdl.score)
    assert mdl.score == pytest.approx(0.5)
