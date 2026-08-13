"""Regression tests for log-space scoring of multiplicative parameters.

The theory score previously measured multiplicative deviations linearly,
dividing by `(f-1)*x0`. That makes x0*f and x0/f -- equal and opposite under
a lognormal prior -- cost different amounts, by a ratio of exactly f**2, and
bounds the total cost of shrinking a parameter to zero at 1/(f-1)**2. For
f >= 2 that ceiling is below the cost of a single f-fold increase, so the
theory term could not meaningfully restrain shrinkage.
"""

import numpy as np
import pytest

from kimeco.database.kimeco_db import dbs
from kimeco.enums import Ptype
from kimeco.scoring_f.scoring import (
    get_parameter_deviation,
    get_parameter_uncertainty_scale,
)

IF = f"TS1{dbs}{Ptype.IF.value}"
WE = f"W1{dbs}{Ptype.WE.value}"
SIG = f"{dbs}{Ptype.SIG.value}0"


def _dev(param: str, value: float, ref: float, unc: float) -> float:
    return get_parameter_deviation(
        reference_values={param: ref},
        reference_uncertainties={param: unc},
        param=param,
        value=value,
    )


@pytest.mark.parametrize("f", [1.05, 1.1, 1.5, 2.0, 3.0, 10.0])
def test_multiplicative_deviation_is_symmetric_in_log_space(f: float) -> None:
    """x0*f and x0/f are both exactly one sigma away, for every f."""
    x0 = 1000.0

    assert _dev(IF, x0 * f, x0, f) == pytest.approx(1.0)
    assert _dev(IF, x0 / f, x0, f) == pytest.approx(-1.0)
    # Equal cost once squared, which is what score_theory accumulates.
    assert _dev(IF, x0 * f, x0, f) ** 2 == \
        pytest.approx(_dev(IF, x0 / f, x0, f) ** 2)


@pytest.mark.parametrize("f", [1.1, 1.5, 2.0, 3.0])
def test_deviation_at_the_perturbation_walls_equals_max_std(f: float) -> None:
    """The walls sit at x0 * f**max_std, so they must score as max_std.

    This is the consistency the pre-fix code had for a linear prior and lost
    once the boundaries became geometric: linear scoring put the upper wall
    at f**4 * ... = 1600 sigma-squared for f = 3 while the lower wall
    saturated at 0.24.
    """
    x0, max_std = 1000.0, 4

    assert _dev(IF, x0 * f ** max_std, x0, f) == pytest.approx(max_std)
    assert _dev(IF, x0 / f ** max_std, x0, f) == pytest.approx(-max_std)


def test_shrinking_is_no_longer_bounded() -> None:
    """Driving a multiplicative parameter toward zero must cost without limit.

    Under the old linear scale the penalty saturated at 1/(f-1)**2 -- only
    0.25 for f = 3, four times cheaper than a single tripling.
    """
    x0, f = 1000.0, 3.0

    assert _dev(IF, x0 * f, x0, f) ** 2 == pytest.approx(1.0)
    penalties = [_dev(IF, x0 * r, x0, f) ** 2 for r in (1e-1, 1e-3, 1e-6)]

    assert penalties == sorted(penalties)
    assert penalties[0] > 1.0        # already dearer than one tripling
    assert penalties[-1] > 100.0     # and unbounded, not capped at 0.25


def test_non_positive_multiplicative_value_is_rejected() -> None:
    with pytest.raises(ValueError, match="must stay positive"):
        _dev(IF, 0.0, 1000.0, 1.1)


@pytest.mark.parametrize("bad", [1.0, 0.0, -1.0])
def test_unusable_uncertainty_factor_is_rejected(bad: float) -> None:
    with pytest.raises(ValueError, match="must be positive and different"):
        _dev(IF, 1100.0, 1000.0, bad)


def test_additive_and_percent_deviations_stay_linear() -> None:
    """Their priors are normal and their walls linear; only multiplicative
    parameters move to log space.
    """
    # additive: sigma is absolute
    assert _dev(WE, 12.0, 10.0, 2.0) == pytest.approx(1.0)
    assert _dev(WE, 8.0, 10.0, 2.0) == pytest.approx(-1.0)
    # percent: sigma is a fraction of the reference value
    assert _dev(SIG, 3.85, 3.5, 0.1) == pytest.approx(1.0)
    assert _dev(SIG, 3.15, 3.5, 0.1) == pytest.approx(-1.0)


def test_linear_scale_helper_is_unchanged() -> None:
    """get_parameter_uncertainty_scale still serves additive/percent and
    keeps its published linear contract for multiplicative types.
    """
    assert get_parameter_uncertainty_scale(
        reference_values={IF: 100.0},
        reference_uncertainties={IF: 1.2},
        param=IF,
    ) == pytest.approx(20.0)


def test_deviation_matches_log_ratio_over_log_factor() -> None:
    x0, f, x = 1000.0, 1.1, 1234.0
    assert _dev(IF, x, x0, f) == \
        pytest.approx(np.log(x / x0) / np.log(f))
