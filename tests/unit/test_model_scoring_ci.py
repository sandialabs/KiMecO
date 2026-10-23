"""CI-safe tests for ``Scoring`` (model score, per-type uncertainty scale,
multiplicative log-space theory score, fixed theory divider).

The last section is the theory-score anchoring of the geometric
multiplicative fix. It locks the round-trip invariant that ties the corrected multiplicative
perturbation geometry to the log-space theory scoring:

* ``get_boundaries(if, i_val=ref)`` == ``(ref / std**max_std, ref * std**max_std)``
* ``score_theory(v)`` for a multiplicative param == ``(ln(v/ref) / ln(std))**2``

Feeding a boundary value back into ``score_theory`` must therefore yield exactly
``max_std**2`` (the +/-max_std sigma edge of the log-normal), and feeding an
SA/NM derivative step ``ref*std**step`` must yield exactly ``step**2``. This ties
the Perturbator geometry, the SA/NM ``calculate_dstep`` and the Scoring log-space
sigma together into one deterministic, MESS/HPC/DB-free identity.

``Perturbator`` is instantiated directly with a ``SimpleNamespace`` logger and a
``SimpleNamespace`` i_sop; ``Linear`` and ``NelderMead`` are built with
``__new__`` carrying only the attributes ``calculate_dstep`` reads; ``Scoring``
is built with a ``SimpleNamespace`` reference SOP.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.Perturbators.perturbator import Perturbator
from kimeco.enums import Ptype
from kimeco.model import Model
from kimeco.optimizers.NelderMead.nelder_mead import NelderMead
from kimeco.scoring_f.scoring import Scoring, get_parameter_uncertainty_scale
from kimeco.sensitivity.linear import Linear


# ===========================================================================
# Scoring
# ===========================================================================
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


def test_scoring_total_and_split() -> None:
    """Scoring sets model.score as a mutable attribute, splits equally when the
    global weights are zero, and keeps a finite total with an empty active_p."""
    # -- test_scoring_sets_model_score_as_mutable_attribute
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={"exp_0": float("inf")},
    )
    settings = {
        "active_p": ["A__we"],
        "weight_theory": 1.0,
        "weight_experiments": 3.0,
        "fix_theory_divider": False,
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

    # -- test_scoring_uses_equal_split_when_global_weights_are_zero
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={"exp_0": float("inf")},
    )
    settings = {
        "active_p": ["A__we"],
        "weight_theory": 0.0,
        "weight_experiments": 0.0,
        "fix_theory_divider": False,
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

    # -- test_scoring_keeps_finite_total_when_active_p_is_empty
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={"exp_0": float("inf")},
    )
    settings = {
        "active_p": [],
        "weight_theory": 1.0,
        "weight_experiments": 1.0,
        "fix_theory_divider": False,
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


def test_uncertainty_scale_by_parameter_type() -> None:
    """The uncertainty scale applies to percent and multiplicative types;
    additive and percent scales are otherwise unchanged."""
    # -- test_uncertainty_scale_scales_percent_and_multiplicative_types
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
    assert scale_if == pytest.approx(np.log(1.2))

    # Multiplicative scale depends only on the uncertainty (ln), not on the
    # reference value: a different reference value gives the same scale.
    scale_if_other_ref = get_parameter_uncertainty_scale(
        reference_values={"TS__if": 5.0},
        reference_uncertainties={"TS__if": 1.2},
        param="TS__if",
    )
    assert scale_if_other_ref == pytest.approx(np.log(1.2))

    # -- test_additive_and_percent_scales_unchanged
    scale_additive = get_parameter_uncertainty_scale(
        reference_values={"A__we": 10.0},
        reference_uncertainties={"A__we": 2.0},
        param="A__we",
    )
    scale_percent = get_parameter_uncertainty_scale(
        reference_values={"__sigma0": 10.0},
        reference_uncertainties={"__sigma0": 0.1},
        param="__sigma0",
    )

    assert scale_additive == pytest.approx(2.0)
    assert scale_percent == pytest.approx(1.0)


def test_multiplicative_theory_score() -> None:
    """The multiplicative theory score is symmetric in the factor (x and 1/x),
    equals the unit case, and an uncertainty of 1 raises."""
    # -- test_multiplicative_theory_score_is_factor_symmetric
    reference = _sop(
        parameters={"TS__if": 100.0},
        uncertainties={"TS__if": 1.2},
        scores={},
    )
    settings = {"active_p": ["TS__if"], "fix_theory_divider": False}
    sf = Scoring(settings=settings, initial_SOP=reference)

    up_sop = _sop(
        parameters={"TS__if": 100.0 * 1.5},
        uncertainties={"TS__if": 1.2},
        scores={},
    )
    down_sop = _sop(
        parameters={"TS__if": 100.0 / 1.5},
        uncertainties={"TS__if": 1.2},
        scores={},
    )

    up_score = sf.score_theory(cast(Any, up_sop))
    down_score = sf.score_theory(cast(Any, down_sop))

    expected = (np.log(1.5) / np.log(1.2)) ** 2
    assert up_score == pytest.approx(down_score)
    assert up_score == pytest.approx(expected)

    # -- test_multiplicative_theory_score_unit_case
    reference = _sop(
        parameters={"TS__if": 1.0},
        uncertainties={"TS__if": 2.0},
        scores={},
    )
    settings = {"active_p": ["TS__if"], "fix_theory_divider": False}
    sf = Scoring(settings=settings, initial_SOP=reference)

    candidate = _sop(
        parameters={"TS__if": 2.0},
        uncertainties={"TS__if": 2.0},
        scores={},
    )

    assert sf.score_theory(cast(Any, candidate)) == pytest.approx(1.0)

    # -- test_multiplicative_uncertainty_one_raises
    with pytest.raises(ValueError):
        get_parameter_uncertainty_scale(
            reference_values={"TS__if": 100.0},
            reference_uncertainties={"TS__if": 1.0},
            param="TS__if",
        )


def test_fix_theory_divider() -> None:
    """fix_theory_divider False divides by the current active count; True locks
    the first non-empty length; __init__ seeds t_div from active_p."""
    # -- test_fix_theory_divider_false_uses_current_active_count: Regression
    #    guard: with the flag off, score_theory normalizes by the
    reference = _sop(
        parameters={"A__we": 10.0, "B__we": 20.0},
        uncertainties={"A__we": 2.0, "B__we": 2.0},
        scores={},
    )
    settings = {
        "active_p": ["A__we", "B__we"],
        "fix_theory_divider": False,
    }
    sf = Scoring(settings=settings, initial_SOP=reference)

    candidate = _sop(
        parameters={"A__we": 12.0, "B__we": 24.0},
        uncertainties={"A__we": 2.0, "B__we": 2.0},
        scores={},
    )

    # Two parameters differ -> divide by 2.
    # ((12-10)/2)**2 / 2 + ((24-20)/2)**2 / 2 = 0.5 + 2.0 = 2.5
    assert sf.score_theory(cast(Any, candidate)) == pytest.approx(2.5)

    # -- test_fix_theory_divider_true_locks_first_nonempty_length: Core
    #    behavior: with the flag on, the divider is locked to the first
    reference = _sop(
        parameters={"A__we": 10.0, "B__we": 20.0},
        uncertainties={"A__we": 2.0, "B__we": 2.0},
        scores={},
    )
    settings = {
        "active_p": ["A__we", "B__we"],
        "fix_theory_divider": True,
    }
    sf = Scoring(settings=settings, initial_SOP=reference)
    assert sf.t_div == 2

    # Later, active_p is reduced. The locked divider must NOT change.
    sf.set_active_p(["A__we"])
    assert sf.t_div == 2

    # Only one parameter actually differs, but the divider stays 2.
    candidate = _sop(
        parameters={"A__we": 12.0, "B__we": 20.0},
        uncertainties={"A__we": 2.0, "B__we": 2.0},
        scores={},
    )
    # ((12-10)/2)**2 / 2 = 0.5  (would be 1.0 if divider tracked the count)
    assert sf.score_theory(cast(Any, candidate)) == pytest.approx(0.5)

    # -- test_fix_theory_divider_init_seeds_t_div_from_active_p
    reference = _sop(
        parameters={"A__we": 10.0, "B__we": 20.0},
        uncertainties={"A__we": 2.0, "B__we": 2.0},
        scores={},
    )
    settings = {
        "active_p": ["A__we", "B__we"],
        "fix_theory_divider": True,
    }
    sf = Scoring(settings=settings, initial_SOP=reference)
    assert sf.t_div == 2


def test_fix_theory_divider_empty_and_first_nonempty() -> None:
    """With fix_theory_divider True an empty active_p gives a neutral theory
    score and the first non-empty active_p wins."""
    # -- test_fix_theory_divider_true_empty_active_p_gives_neutral_theory:
    #    Edge: flag on but active_p empty -> t_div stays 0 -> neutral 0.0.
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={},
    )
    settings = {"active_p": [], "fix_theory_divider": True}
    sf = Scoring(settings=settings, initial_SOP=reference)
    assert sf.t_div == 0

    candidate = _sop(
        parameters={"A__we": 12.0},
        uncertainties={"A__we": 2.0},
        scores={},
    )
    assert sf.score_theory(cast(Any, candidate)) == pytest.approx(0.0)

    # -- test_fix_theory_divider_first_nonempty_wins: Edge: the FIRST non-empty
    #    active_p locks the divider; empties before it
    reference = _sop(
        parameters={"A__we": 10.0},
        uncertainties={"A__we": 2.0},
        scores={},
    )
    settings = {"active_p": [], "fix_theory_divider": True}
    sf = Scoring(settings=settings, initial_SOP=reference)
    assert sf.t_div == 0

    # An empty update keeps it at 0.
    sf.set_active_p([])
    assert sf.t_div == 0

    # The first non-empty update locks the divider to 2.
    sf.set_active_p(["A__we", "B__we"])
    assert sf.t_div == 2

    # A later shorter update does not change the locked divider.
    sf.set_active_p(["A__we"])
    assert sf.t_div == 2


# ===========================================================================
# Multiplicative boundary anchoring (Perturbator, SA/NM dstep, Scoring)
# ===========================================================================
IF_P = "R__if"  # multiplicative parameter (suffix drives type dispatch)


def _make_pert(std_if: float, ref: float, max_std: int) -> Perturbator:
    """Real Perturbator whose i_sop exposes exactly one multiplicative param."""
    settings: dict[str, Any] = {
        "active_p": [], "max_std": max_std, "std_if": std_if,
    }
    klog = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    pert = Perturbator(settings, SimpleNamespace(), klog)
    pert.i_sop = SimpleNamespace(
        uncertainties={IF_P: std_if},
        parameters_names={IF_P: ref},
    )
    return pert


def _ref_scoring(ref: float, unc: float) -> Scoring:
    """Scoring anchored on a one-parameter reference SOP (ref, uncertainty)."""
    reference = SimpleNamespace(
        parameters_names={IF_P: ref},
        uncertainties={IF_P: unc},
    )
    return Scoring(
        settings={"active_p": [IF_P], "fix_theory_divider": False},
        initial_SOP=reference,
    )


def _candidate(value: float) -> Any:
    """A one-parameter SOP carrying only the perturbed multiplicative value."""
    return SimpleNamespace(parameters_names={IF_P: value})


def _make_sa(pert: Perturbator, lin_fact: float) -> Linear:
    sa = Linear.__new__(Linear)
    sa.pert = pert
    sa.lin_fact = lin_fact
    return sa


def _make_nm(pert: Perturbator, nm_dstep: float) -> NelderMead:
    nm = NelderMead.__new__(NelderMead)
    nm.pert = pert
    nm.settings = {"nm_dstep": nm_dstep}
    return nm


def test_theory_score_equals_max_std_squared_at_boundary() -> None:
    """At the sampling boundary the multiplicative theory score equals
    max_std**2; an SA/NM dstep step scores step**2."""
    # -- test_theory_score_equals_max_std_squared_at_boundary: Both
    #    multiplicative boundaries score exactly max_std**2 in log space.
    _failures = []
    for u, m, expected in [(1.2, 3, 9.0), (2.0, 4, 16.0)]:
        try:
            ref = 100.0
            pert = _make_pert(std_if=u, ref=ref, max_std=m)
            lo, hi = pert.get_boundaries(ptype=Ptype.IF.value, i_val=ref, param=IF_P)
            assert hi == pytest.approx(ref * u ** m)
            assert lo == pytest.approx(ref / u ** m)

            sf = _ref_scoring(ref=ref, unc=u)
            assert sf.score_theory(_candidate(hi)) == pytest.approx(expected)
            assert sf.score_theory(_candidate(lo)) == pytest.approx(expected)
        except AssertionError as _exc:
            _failures.append(
                f"test_theory_score_equals_max_std_squared_at_boundary"
                f"[u={u!r} m={m!r} expected={expected!r}]: {_exc}")
    assert not _failures, '\n'.join(_failures)

    # -- test_sa_nm_dstep_theory_score_equals_step_squared: SA and NM
    #    multiplicative dstep ref*u**step scores exactly step**2.
    ref, u, step = 100.0, 1.2, 0.1
    pert = _make_pert(std_if=u, ref=ref, max_std=3)
    sf = _ref_scoring(ref=ref, unc=u)

    sa = _make_sa(pert, lin_fact=step)
    sa_up = sa.calculate_dstep(uc=u, param=IF_P, side=1, value=ref)
    assert sa_up == pytest.approx(ref * u ** step)
    assert sf.score_theory(_candidate(sa_up)) == pytest.approx(step ** 2)

    nm = _make_nm(pert, nm_dstep=step)
    nm_up = nm.calculate_dstep(uc=u, param=IF_P, side=1, value=ref)
    assert nm_up == pytest.approx(ref * u ** step)
    assert sf.score_theory(_candidate(nm_up)) == pytest.approx(step ** 2)

