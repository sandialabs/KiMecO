"""Regression tests for multiplicative perturbation in log space.

Two bugs previously used ``f - 1`` (the first-order expansion of the correct
expression around ``f = 1``) where ``ln f`` belongs:

* ``get_boundaries`` placed the n-sigma wall at ``1 + n*(f-1)`` instead of
  ``f**n``, which narrows the trusted region as ``f`` grows.
* the LOGNORMAL branch of ``get_rng`` passed ``get_scale``'s linear-space
  spread ``(f-1)*x`` as the scale of a normal in log space, so the sigma
  actually used scaled with the parameter's magnitude.
"""

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Distrib, Ptype
from kimeco.logger_config import KMOLogger
from kimeco.parameters import SOP


def _build_perturbator(log_path: str,
                       uncertainties: dict[str, float],
                       values: dict[str, float],
                       **settings: float) -> Perturbator:
    """Perturbator over a stub SOP exposing only what the maths reads."""
    sop = SimpleNamespace(
        parameters_names=dict(values),
        uncertainties=dict(uncertainties),
    )
    return Perturbator(
        settings={"active_p": list(uncertainties), **settings},
        initial_SOP=cast(SOP, cast(Any, sop)),
        klog=KMOLogger(filename=log_path),
    )


def test_multiplicative_boundaries_are_geometric(tmp_path) -> None:
    """The n-sigma wall of a lognormal prior is f**n, not 1 + n*(f-1)."""
    f, i_val, max_std = 2.0, 1000.0, 4
    pert = _build_perturbator(
        log_path=str(tmp_path / "bounds.log"),
        uncertainties={},
        values={},
        max_std=max_std,
        **{f"std_{Ptype.IF.value}": f},
    )

    low, high = pert.get_boundaries(ptype=Ptype.IF.value, i_val=i_val)

    assert high == pytest.approx(i_val * f ** max_std)
    assert low == pytest.approx(i_val / f ** max_std)
    # The old linear walls sat at 1 + 4*(2-1) = 5x, only 2.32 sigma out.
    assert high > i_val * (1 + (f - 1) * max_std)


def test_lognormal_sigma_is_independent_of_parameter_magnitude(
    tmp_path,
) -> None:
    """`if` carries a physical value (~1000 cm-1), not a coefficient.

    Under the old code its log-space sigma was ``(f-1)*value = 100``, so the
    draws spanned tens of orders of magnitude and the rejection loop in
    ``perturb_ifreq`` reduced them to a log-uniform band, at a cost of some
    370 rejected draws per accepted sample.
    """
    f, ifreq = 1.1, 1000.0
    param = f"TS1{dbs}{Ptype.IF.value}"
    pert = _build_perturbator(
        log_path=str(tmp_path / "sigma.log"),
        uncertainties={param: f},
        values={param: ifreq},
        max_std=4,
        **{f"std_{Ptype.IF.value}": f},
    )

    assert pert.get_log_scale(ptype=Ptype.IF.value, param=param) == \
        pytest.approx(np.log(f))

    np.random.seed(20260812)
    draws = np.array([
        pert.get_rng(ptype=Ptype.IF.value,
                     i_val=ifreq,
                     c_val=ifreq,
                     param=param,
                     distrib=Distrib.LOGNORMAL)
        for _ in range(20000)
    ])

    # MC error on the std of 20000 draws is ~sigma/sqrt(2N), well under 5%.
    assert np.std(np.log(draws)) == pytest.approx(np.log(f), rel=0.05)
    assert np.mean(np.log(draws)) == pytest.approx(np.log(ifreq), abs=0.01)

    # Nearly every draw clears the walls; the old sigma needed ~370 tries.
    low, high = pert.get_boundaries(ptype=Ptype.IF.value, i_val=ifreq)
    assert np.mean((draws > low) & (draws < high)) > 0.99


def test_percent_log_scale_uses_one_plus_uncertainty(tmp_path) -> None:
    """Percent types default to NORMAL, but the GUI exposes lognormal."""
    u = 0.1
    param = f"W1{dbs}{Ptype.SIG.value}0"
    pert = _build_perturbator(
        log_path=str(tmp_path / "pct.log"),
        uncertainties={param: u},
        values={param: 3.5},
    )

    assert pert.get_log_scale(ptype=Ptype.SIG.value, param=param) == \
        pytest.approx(np.log(1 + u))


def test_lognormal_rejects_additive_parameters(tmp_path) -> None:
    """Additive parameters are energies; log() of a negative value is nan."""
    param = f"W1{dbs}{Ptype.WE.value}"
    pert = _build_perturbator(
        log_path=str(tmp_path / "add.log"),
        uncertainties={param: 1.0},
        values={param: -5.0},
    )

    with pytest.raises(TypeError, match="not defined for additive"):
        pert.get_log_scale(ptype=Ptype.WE.value, param=param)


def test_get_scale_still_returns_linear_spread(tmp_path) -> None:
    """get_scale is unchanged: the NORMAL branch and the derivative-step
    helpers in linear.py / nelder_mead.py depend on its linear-space units.
    """
    f, ifreq = 1.1, 1000.0
    param = f"TS1{dbs}{Ptype.IF.value}"
    pert = _build_perturbator(
        log_path=str(tmp_path / "linear.log"),
        uncertainties={param: f},
        values={param: ifreq},
    )

    assert pert.get_scale(ptype=Ptype.IF.value, param=param) == \
        pytest.approx((f - 1) * ifreq)
