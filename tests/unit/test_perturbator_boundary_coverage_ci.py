"""CI-safe boundary + coverage tests for ``Perturbator`` sampling internals.

These tests lock the corrected multiplicative ``get_scale`` (log-space sigma)
introduced in 1.1.2 and prove -- deterministically and statistically -- that
``+/- max_std * sigma`` reaches exactly the ``get_boundaries`` factor for every
parameter class:

* ADDITIVE       (we, be, pow)              -> sigma = std                 (linear axis)
* PERCENT        (hrs, sigma, epsilon, fact)-> sigma = std * value         (linear axis)
* MULTIPLICATIVE (if, freq, bfc, sfc, mrc)  -> sigma = ln(std); bounds value*std**(+/-ms)

Everything runs through the REAL ``Perturbator`` backend -- no MESS/HPC/DB.
The abstract-ish base class carries no abstract methods, so it is instantiated
directly with a ``SimpleNamespace`` logger, and ``i_sop`` is replaced by a
``SimpleNamespace`` exposing only ``uncertainties`` and ``parameters_names``
(the sole attributes ``get_scale`` reads).

Statistical tests use a fixed seed and N=10_000 samples drawn through the real
``get_rng``; each is paired with a deterministic identity assertion so it fails
precisely even if the numpy RNG stream ever drifts. Draws are cached per
sampling configuration and reused across ``max_std`` wherever ``get_rng`` does
not read it (normal / log-normal sampling only uses ``get_scale``, which is
``max_std``-independent); the tolerances are about 4.5-7.7 standard errors at
that N. The last section checks that ``Perturbator.select`` aliases the
settings' ``active_p`` list.

This file is complementary to ``test_perturbation_distribution_matrix_ci.py``
(which locks the *validation* rule); here we exercise the *sampling* backend on
the LEGAL cells only.
"""

from functools import lru_cache
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from kimeco.Perturbators.perturbator import Perturbator
from kimeco.enums import Distrib, Ptype
from kimeco.logger_config import KMOLogger
from kimeco.parameters import SOP


SEED = 20250820
N = 10_000
# +/-3 sigma of a standard normal -> 0.997300; +/-4 sigma -> 0.999937.
THREE_SIGMA = 0.9973002
# +/-2 sigma of a standard normal -> 0.954500.
TWO_SIGMA = 0.9544997
PARAM = "p"


def _make_pert(std_overrides: dict[str, Any],
               uncertainty: float,
               value: float) -> Perturbator:
    """Build a real Perturbator with a fake i_sop exposing exactly one param.

    ``uncertainty`` feeds ``get_scale`` (via ``i_sop.uncertainties``). Since the
    boundary fix, ``get_boundaries`` ALSO reads ``i_sop.uncertainties[param]``
    whenever a ``param`` is supplied, falling back to ``settings['std_<ptype>']``
    (from ``std_overrides``) when ``param`` is ``None`` or absent from the dict.

    The numeric cases below keep ``uncertainty == std`` and call
    ``get_boundaries`` positionally (no ``param`` -> the global-std fallback), so
    both the boundary and the ``get_rng`` sampling paths resolve to the same
    sigma and the +/-max_std*sigma identities still land exactly on the boundary.
    """
    settings: dict[str, Any] = {"active_p": []}
    settings.update(std_overrides)
    klog = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    pert = Perturbator(settings, SimpleNamespace(), klog)
    pert.i_sop = SimpleNamespace(
        uncertainties={PARAM: uncertainty},
        parameters_names={PARAM: value},
    )
    return pert


@lru_cache(maxsize=None)
def _draws(ptype: str, unc: float, value: float, std_key: str,
           distrib: Distrib, max_std: int = 3) -> tuple[Perturbator, np.ndarray]:
    """N seeded get_rng draws centred on ``value`` (cached per configuration).

    Normal / log-normal draws do not depend on ``max_std``: the coverage
    tests move ``max_std`` on the returned Perturbator to reuse them. Uniform
    draws do (they sample the boundaries), hence ``max_std`` in the key.
    """
    pert = _make_pert({"max_std": max_std, std_key: unc}, unc, value)
    np.random.seed(SEED)
    draws = np.array([
        pert.get_rng(ptype=ptype, i_val=value, c_val=value, param=PARAM,
                     distrib=distrib) for _ in range(N)])
    return pert, draws


def _coverage(ptype: str, unc: float, value: float, std_key: str,
              distrib: Distrib, max_std: int) -> float:
    """Fraction of the cached draws strictly inside the max_std bounds."""
    pert, draws = _draws(ptype, unc, value, std_key, distrib)
    pert.settings["max_std"] = max_std
    try:
        lo, hi = sorted(pert.get_boundaries(ptype=ptype, i_val=value))
    finally:
        pert.settings["max_std"] = 3
    return float(np.mean((draws > lo) & (draws < hi)))


# ===========================================================================
# Group 1 -- Boundary correctness across ALL parameter classes
# ===========================================================================

def test_get_boundaries_per_class() -> None:
    """Multiplicative bounds are value*std**(+/-max_std) (geometrically
    symmetric: lo*hi == i_val**2, lower bound > 0 even for a large std);
    additive bounds are i_val +/- std*max_std; percent bounds scale with the
    value; a percent zero-bound param clamps a negative lower bound to 0."""
    # value=1, std=1.2, max_std=3 -> bounds (1/1.2**3, 1.2**3) exactly.
    pert = _make_pert({"max_std": 3, "std_if": 1.2}, 1.2, 1.0)
    lo, hi = pert.get_boundaries(ptype=Ptype.IF.value, i_val=1.0)
    assert lo == pytest.approx(1 / 1.728)
    assert hi == pytest.approx(1.728)
    assert (lo, hi) == pytest.approx((1 / 1.2 ** 3, 1.2 ** 3))

    i_val = 800.0
    pert = _make_pert({"max_std": 4, "std_if": 1.1}, 1.1, i_val)
    lo, hi = pert.get_boundaries(ptype=Ptype.IF.value, i_val=i_val)
    factor = 1.1 ** 4  # geometric: std ** max_std == 1.4641
    assert lo == pytest.approx(i_val / factor)
    assert hi == pytest.approx(i_val * factor)
    assert lo * hi == pytest.approx(i_val ** 2)

    pert = _make_pert({"max_std": 3, "std_we": 1.0}, 1.0, 100.0)
    lo, hi = pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0)
    assert lo == pytest.approx(100.0 - 1.0 * 3)
    assert hi == pytest.approx(100.0 + 1.0 * 3)

    pert = _make_pert({"max_std": 3, "std_hrs": 0.1}, 0.1, i_val)
    lo, hi = pert.get_boundaries(ptype=Ptype.HRS.value, i_val=i_val)
    assert lo == pytest.approx(i_val - i_val * 0.1 * 3)
    assert hi == pytest.approx(i_val + i_val * 0.1 * 3)

    # Division-based lower bound: 1 / 4**5 = 1/1024.
    pert = _make_pert({"max_std": 5, "std_if": 4.0}, 4.0, 1.0)
    lo, hi = pert.get_boundaries(ptype=Ptype.IF.value, i_val=1.0)
    assert lo > 0.0
    assert hi > lo
    assert lo == pytest.approx(1 / 4 ** 5)
    assert hi == pytest.approx(4 ** 5)

    # sigma is PERCENT *and* in zero_bound. i_val*std*max_std = 1*0.1*20 = 2 > 1
    # so the raw lower bound (1-2 = -1) must be clamped to exactly 0.0.
    pert = _make_pert({"max_std": 20, "std_sigma": 0.1}, 0.1, 1.0)
    lo, hi = pert.get_boundaries(ptype=Ptype.SIG.value, i_val=1.0)
    assert lo == 0.0
    assert hi == pytest.approx(1.0 + 1.0 * 0.1 * 20)


def test_within_boundaries_matches_get_boundaries_strictly() -> None:
    """within_boundaries uses STRICT comparisons against get_boundaries."""
    pert = _make_pert({"max_std": 3, "std_we": 1.0}, 1.0, 100.0)
    lo, hi = pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0)
    # Inside -> True.
    assert pert.within_boundaries(
        perturbed_val=100.0, ptype=Ptype.WE.value, initial_val=100.0) is True
    # Exactly on the boundary -> False (strict).
    assert pert.within_boundaries(
        perturbed_val=lo, ptype=Ptype.WE.value, initial_val=100.0) is False
    assert pert.within_boundaries(
        perturbed_val=hi, ptype=Ptype.WE.value, initial_val=100.0) is False
    # Outside -> False.
    assert pert.within_boundaries(
        perturbed_val=hi + 1e-6, ptype=Ptype.WE.value,
        initial_val=100.0) is False


# ===========================================================================
# Group 2 -- get_scale identities (deterministic halves of the coverage tests)
# ===========================================================================

def test_get_scale_identities() -> None:
    """max_std * get_scale is the boundary half-width on the linear axis
    (additive, percent) and the log of the boundary factor on the log axis:
    get_scale is ln(std) for a multiplicative param (small, canonical and
    max_std 4 cases), value-independent, and NOT the pre-fix (std-1)*value."""
    pert = _make_pert({"max_std": 3, "std_we": 1.0}, 1.0, 100.0)
    scale = pert.get_scale(ptype=Ptype.WE.value, param=PARAM)
    lo, hi = pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0)
    assert 3 * scale == pytest.approx((hi - lo) / 2)

    i_val = 800.0
    pert = _make_pert({"max_std": 3, "std_hrs": 0.1}, 0.1, i_val)
    scale = pert.get_scale(ptype=Ptype.HRS.value, param=PARAM)
    lo, hi = pert.get_boundaries(ptype=Ptype.HRS.value, i_val=i_val)
    assert 3 * scale == pytest.approx((hi - lo) / 2)

    pert = _make_pert({"max_std": 3, "std_if": 1.2}, 1.2, 1.0)
    scale = pert.get_scale(ptype=Ptype.IF.value, param=PARAM)
    assert scale == pytest.approx(np.log(1.2))
    assert 3 * scale == pytest.approx(np.log(1.2 ** 3))
    assert 4 * scale == pytest.approx(np.log(1.2 ** 4))
    # Regression guard: ln(std) == log(upper / i_val) / max_std ~ 0.18232,
    # not the old arithmetic (std - 1) * value == 0.2.
    lo, hi = pert.get_boundaries(ptype=Ptype.IF.value, i_val=1.0)
    assert scale == pytest.approx(np.log(hi / 1.0) / 3)
    assert scale == pytest.approx(0.18232156, abs=1e-6)
    assert abs(scale - (1.2 - 1) * 1.0) > 0.01

    pert = _make_pert({"max_std": 3, "std_if": 1.1}, 1.1, 1.0)
    scale = pert.get_scale(ptype=Ptype.IF.value, param=PARAM)
    assert 3 * scale == pytest.approx(np.log(1.1 ** 3))

    # Value independence: if=800 gives the same sigma as value=1.
    p_one = _make_pert({"max_std": 4, "std_if": 1.1}, 1.1, 1.0)
    p_big = _make_pert({"max_std": 4, "std_if": 1.1}, 1.1, 800.0)
    s_one = p_one.get_scale(ptype=Ptype.IF.value, param=PARAM)
    s_big = p_big.get_scale(ptype=Ptype.IF.value, param=PARAM)
    assert s_one == pytest.approx(s_big)
    lo, hi = p_big.get_boundaries(ptype=Ptype.IF.value, i_val=800.0)
    assert s_big == pytest.approx(np.log(hi / 800.0) / 4)


# ===========================================================================
# Group 3 -- Distribution x class matrix on the SAMPLING backend (get_rng),
#            LEGAL cells only. Complements the validation-matrix test file.
# ===========================================================================

# (ptype, uncertainty, value, std key, distrib); i_val == value.
_LEGAL_CELLS = [
    # ADDITIVE -> normal / uniform
    (Ptype.WE.value, 1.0, 100.0, "std_we", Distrib.NORMAL),
    (Ptype.WE.value, 1.0, 100.0, "std_we", Distrib.UNIFORM),
    # PERCENT -> normal / uniform
    (Ptype.HRS.value, 0.1, 800.0, "std_hrs", Distrib.NORMAL),
    (Ptype.HRS.value, 0.1, 800.0, "std_hrs", Distrib.UNIFORM),
    # MULTIPLICATIVE -> log-normal / log-uniform
    (Ptype.IF.value, 1.2, 1.0, "std_if", Distrib.LOGNORMAL),
    (Ptype.IF.value, 1.2, 1.0, "std_if", Distrib.LOGUNIFORM),
]


def test_legal_cells_sample_finite_and_uniform_family_within_bounds() -> None:
    """Every legal (class, distribution) cell yields finite draws; UNIFORM /
    LOG-UNIFORM draws are ALL within [lo, hi]."""
    failures: list[str] = []
    for ptype, unc, value, std_key, distrib in _LEGAL_CELLS:
        label = f"{ptype}-{distrib.value}"
        pert, draws = _draws(ptype, unc, value, std_key, distrib)
        if not np.all(np.isfinite(draws)):
            failures.append(f"{label}: non-finite draws")
        if distrib in (Distrib.UNIFORM, Distrib.LOGUNIFORM):
            lo, hi = pert.get_boundaries(ptype=ptype, i_val=value)
            if draws.min() < lo or draws.max() > hi:
                failures.append(f"{label}: draws [{draws.min()}, "
                                f"{draws.max()}] outside [{lo}, {hi}]")
    assert not failures, "\n".join(failures)


def test_loguniform_is_uniform_on_log_axis() -> None:
    """LOG-UNIFORM draws are uniform in log-space: mean(log) ~ log midpoint
    and std(log) ~ width/sqrt(12) (0.316 here, vs 0.182 for log-normal)."""
    pert, draws = _draws(Ptype.IF.value, 1.2, 1.0, "std_if",
                         Distrib.LOGUNIFORM)
    lo, hi = pert.get_boundaries(ptype=Ptype.IF.value, i_val=1.0)
    logs = np.log(draws)
    mid = (np.log(lo) + np.log(hi)) / 2  # == 0 for symmetric (1/1.728, 1.728)
    expected_std = (np.log(hi) - np.log(lo)) / np.sqrt(12)
    assert logs.mean() == pytest.approx(mid, abs=1.5e-2)
    assert logs.std() == pytest.approx(expected_std, rel=2e-2)


# ===========================================================================
# Group 4 -- Coverage on the LINEAR axis (additive + percent) and the LOG
#            axis (multiplicative)
# ===========================================================================

def test_linear_normal_coverage() -> None:
    """Additive and percent normal draws land inside the +/-3 sigma bounds
    ~99.73% of the time; additive at max_std=4 covers >99.9%."""
    frac = _coverage(Ptype.WE.value, 1.0, 100.0, "std_we", Distrib.NORMAL, 3)
    assert abs(frac - THREE_SIGMA) < 0.004, f"additive 3 sigma: {frac}"
    frac = _coverage(Ptype.HRS.value, 0.1, 800.0, "std_hrs", Distrib.NORMAL, 3)
    assert abs(frac - THREE_SIGMA) < 0.004, f"percent 3 sigma: {frac}"
    frac = _coverage(Ptype.WE.value, 1.0, 100.0, "std_we", Distrib.NORMAL, 4)
    assert frac > 0.999, f"additive 4 sigma: {frac}"


def test_multiplicative_lognormal_coverage() -> None:
    """value=1, std=1.2: log-normal ~99.73% within (1/1.728, 1.728) at
    max_std=3 (headline), ~95.45% within (1/1.44, 1.44) at max_std=2, >99.9%
    at the default max_std=4; a LARGE std (4, bounds (1/64, 64)) still gives
    ~99.73% at max_std=3."""
    pert = _make_pert({"max_std": 2, "std_if": 1.2}, 1.2, 1.0)
    assert pert.get_boundaries(ptype=Ptype.IF.value, i_val=1.0) == \
        pytest.approx((1 / 1.44, 1.44))
    pert = _make_pert({"max_std": 3, "std_if": 4.0}, 4.0, 1.0)
    assert pert.get_boundaries(ptype=Ptype.IF.value, i_val=1.0) == \
        pytest.approx((1 / 64, 64.0))

    cell = (Ptype.IF.value, 1.2, 1.0, "std_if", Distrib.LOGNORMAL)
    frac = _coverage(*cell, 3)
    assert abs(frac - THREE_SIGMA) < 0.004, f"headline 3 sigma: {frac}"
    frac = _coverage(*cell, 2)
    assert abs(frac - TWO_SIGMA) < 0.01, f"2 sigma: {frac}"
    frac = _coverage(*cell, 4)
    assert frac > 0.999, f"max_std 4: {frac}"
    frac = _coverage(Ptype.IF.value, 4.0, 1.0, "std_if", Distrib.LOGNORMAL, 3)
    assert abs(frac - THREE_SIGMA) < 0.004, f"large std 3 sigma: {frac}"


# ===========================================================================
# Group 5 -- Parameter-specific uncertainty overrides in get_boundaries.
#
# get_boundaries(..., param=P) resolves the sigma from
# i_sop.uncertainties[P] when present, else falls back to
# settings['std_<ptype>']. Here _make_pert seeds uncertainties[PARAM] with the
# OVERRIDE, and std_overrides carries the (different) GLOBAL std, so the two
# code paths diverge and can be compared head to head.
# ===========================================================================

def test_specific_std_overrides() -> None:
    """An override wider (we 2.0 vs 1.0) or narrower (be 0.5 vs 1.0) than
    the global std widens or narrows the additive band; a percent override
    (hrs 0.3 vs 0.1) widens the value-scaled band; a multiplicative override
    (mrc 1.5 vs 1.2) keeps the log symmetry lo*hi == i_val**2."""
    pert = _make_pert({"max_std": 3, "std_we": 1.0}, 2.0, 100.0)
    lo_o, hi_o = pert.get_boundaries(
        ptype=Ptype.WE.value, i_val=100.0, param=PARAM)
    lo_g, hi_g = pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0)
    assert (lo_o, hi_o) == pytest.approx((100.0 - 6.0, 100.0 + 6.0))
    assert (lo_g, hi_g) == pytest.approx((100.0 - 3.0, 100.0 + 3.0))
    assert (hi_o - lo_o) > (hi_g - lo_g)

    pert = _make_pert({"max_std": 3, "std_be": 1.0}, 0.5, 50.0)
    lo_o, hi_o = pert.get_boundaries(
        ptype=Ptype.BE.value, i_val=50.0, param=PARAM)
    lo_g, hi_g = pert.get_boundaries(ptype=Ptype.BE.value, i_val=50.0)
    assert (lo_o, hi_o) == pytest.approx((50.0 - 1.5, 50.0 + 1.5))
    assert (hi_o - lo_o) < (hi_g - lo_g)

    i_val = 800.0
    pert = _make_pert({"max_std": 3, "std_hrs": 0.1}, 0.3, i_val)
    lo_o, hi_o = pert.get_boundaries(
        ptype=Ptype.HRS.value, i_val=i_val, param=PARAM)
    lo_g, hi_g = pert.get_boundaries(ptype=Ptype.HRS.value, i_val=i_val)
    assert (lo_o, hi_o) == pytest.approx(
        (i_val - i_val * 0.3 * 3, i_val + i_val * 0.3 * 3))
    assert (hi_o - lo_o) > (hi_g - lo_g)

    i_val = 500.0
    pert = _make_pert({"max_std": 3, "std_mrc": 1.2}, 1.5, i_val)
    lo_o, hi_o = pert.get_boundaries(
        ptype=Ptype.MRC.value, i_val=i_val, param=PARAM)
    factor = 1.5 ** 3  # = 3.375, using the OVERRIDE not the global 1.2.
    assert lo_o == pytest.approx(i_val / factor)
    assert hi_o == pytest.approx(i_val * factor)
    assert lo_o * hi_o == pytest.approx(i_val ** 2)
    lo_g, hi_g = pert.get_boundaries(ptype=Ptype.MRC.value, i_val=i_val)
    assert (hi_o - lo_o) > (hi_g - lo_g)


def test_fallbacks_to_global_std() -> None:
    """When uncertainty == global std the param path matches the global
    path (we, hrs, mrc); param=None and a param absent from
    i_sop.uncertainties both use settings['std_<ptype>']."""
    failures: list[str] = []
    for ptype, std_key, std_val, i_val in (
            (Ptype.WE.value, "std_we", 1.0, 100.0),
            (Ptype.HRS.value, "std_hrs", 0.1, 800.0),
            (Ptype.MRC.value, "std_mrc", 1.2, 500.0)):
        pert = _make_pert({"max_std": 3, std_key: std_val}, std_val, i_val)
        with_param = pert.get_boundaries(ptype=ptype, i_val=i_val, param=PARAM)
        global_path = pert.get_boundaries(ptype=ptype, i_val=i_val)
        if with_param != pytest.approx(global_path):
            failures.append(f"{ptype}: {with_param} != {global_path}")
    assert not failures, "\n".join(failures)

    pert = _make_pert({"max_std": 3, "std_we": 1.0}, 9.0, 100.0)
    # Explicit global expectation (std_we = 1.0), NOT the 9.0 override.
    assert pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0,
                               param=None) == pytest.approx((97.0, 103.0))
    # 'ghost' is absent from i_sop.uncertainties (which only holds PARAM).
    assert pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0,
                               param="ghost") == pytest.approx((97.0, 103.0))


def test_param_forwarded_to_within_boundaries_and_get_rng() -> None:
    """A value inside the widened override band (91, 109) but outside the
    global band (97, 103) is accepted only when param is supplied; UNIFORM
    get_rng samples the widened band (draws exceed the global upper bound,
    impossible without forwarding param)."""
    pert = _make_pert({"max_std": 3, "std_we": 1.0}, 3.0, 100.0)
    assert pert.within_boundaries(
        perturbed_val=105.0, ptype=Ptype.WE.value, initial_val=100.0,
        param=PARAM) is True
    assert pert.within_boundaries(
        perturbed_val=105.0, ptype=Ptype.WE.value, initial_val=100.0) is False

    global_hi = pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0)[1]
    widened_lo, widened_hi = pert.get_boundaries(
        ptype=Ptype.WE.value, i_val=100.0, param=PARAM)
    np.random.seed(SEED)
    draws = np.array([
        pert.get_rng(ptype=Ptype.WE.value, i_val=100.0, c_val=100.0,
                     param=PARAM, distrib=Distrib.UNIFORM)
        for _ in range(2_000)])
    assert draws.max() > global_hi
    assert draws.max() <= widened_hi
    assert draws.min() >= widened_lo


# ===========================================================================
# Group 6 -- Seed rescaling: the out-of-bounds "seed" value each perturb_*
#            method uses to force at least one get_rng draw must itself be
#            rescaled by the parameter-specific uncertainty.
# ===========================================================================

def _instrument(pert: Perturbator, in_bounds: float):
    """Record first within_boundaries perturbed_val + count get_rng calls.

    get_rng is stubbed to return an in-bounds value so the seeding loop exits
    after exactly one draw, leaving the initial seed observable in wb[0].
    """
    wb: list[float] = []
    calls = {"rng": 0}
    orig_wb = pert.within_boundaries

    def spy_wb(**kw: Any) -> bool:
        wb.append(kw["perturbed_val"])
        return orig_wb(**kw)

    def stub_rng(**kw: Any) -> float:
        calls["rng"] += 1
        return in_bounds

    pert.within_boundaries = spy_wb  # type: ignore[method-assign]
    pert.get_rng = stub_rng          # type: ignore[method-assign]
    return wb, calls


def test_perturb_seeds_rescaled_to_specific_std() -> None:
    """perturb_energy seeds E0 - 3*max_std*sigma (override widened and
    narrowed), perturb_hindered_rotors and perturb_multi_rotors seed
    1 - 3*max_std*sigma, all with the override sigma, below the lower bound."""
    e0, max_std = 100.0, 3
    param = f"LEFT__{Ptype.WE.value}"
    for glob, spec in ((1.0, 5.0), (1.0, 0.5)):
        pert = _make_pert({"max_std": max_std, f"std_{Ptype.WE.value}": glob},
                          spec, e0)
        pert.select = [param]
        pert.i_sop.items = {"LEFT": SimpleNamespace(energy=e0)}
        pert.i_sop.uncertainties = {param: spec}
        pert.settings["distrib_we"] = Distrib.NORMAL
        item = SimpleNamespace(name="LEFT", pert_e=True, energy=e0, _energy=e0)
        wb, calls = _instrument(pert, in_bounds=e0)
        pert.perturb_energy(item=item)
        seed = wb[0]
        assert seed == pytest.approx(e0 - 3 * max_std * spec), spec
        lo = min(pert.get_boundaries(
            ptype=Ptype.WE.value, i_val=e0, param=param))
        assert seed < lo, spec
        assert calls["rng"] >= 1, spec

    glob, spec = 0.1, 0.3
    param = f"W__{Ptype.HRS.value}0"
    pert = _make_pert({"max_std": max_std, f"std_{Ptype.HRS.value}": glob},
                      spec, 1.0)
    pert.select = [param]
    pert.i_sop.uncertainties = {param: spec}
    pert.settings["distrib_hrs"] = Distrib.NORMAL
    rot = SimpleNamespace(pert=0.0)
    wb, calls = _instrument(pert, in_bounds=1.0)
    pert.perturb_hindered_rotors(well=SimpleNamespace(name="W", h_rotors=[rot]))
    seed = wb[0]
    assert seed == pytest.approx(1 - 3 * max_std * spec)
    assert seed < min(pert.get_boundaries(
        ptype=Ptype.HRS.value, i_val=1.0, param=param))
    assert calls["rng"] >= 1
    assert rot.pert == pytest.approx(1.0)

    glob, spec = 1.2, 1.5
    param = f"W__{Ptype.MRC.value}0"
    pert = _make_pert({"max_std": max_std, f"std_{Ptype.MRC.value}": glob},
                      spec, 1.0)
    pert.select = [param]
    pert.i_sop.uncertainties = {param: spec}
    pert.settings["distrib_mrc"] = Distrib.LOGNORMAL
    rot = SimpleNamespace(sfc=0.0)
    wb, calls = _instrument(pert, in_bounds=1.0)
    pert.perturb_multi_rotors(well=SimpleNamespace(name="W", m_rotors=[rot]))
    seed = wb[0]
    assert seed == pytest.approx(1 - 3 * max_std * spec)
    assert seed < min(pert.get_boundaries(
        ptype=Ptype.MRC.value, i_val=1.0, param=param))
    assert calls["rng"] >= 1
    assert rot.sfc == pytest.approx(1.0)


# ===========================================================================
# Group 7 -- Perturbator.select aliases the settings' active_p list
# ===========================================================================

def test_active_parameters_alias_the_original_settings_list(tmp_path) -> None:
    """Reassigning settings['active_p'] does not refresh Perturbator.select;
    an in-place mutation of the original list is followed."""
    settings: dict[str, Any] = {"active_p": ["old_param"]}
    pert = Perturbator(settings=settings, initial_SOP=SOP(n_exp=1),
                       klog=KMOLogger(filename=str(tmp_path / "pert.log")))
    settings["active_p"] = ["new_param"]
    assert pert.select == ["old_param"]
    assert pert.select != settings["active_p"]

    original_active = ["p0"]
    settings = {"active_p": original_active}
    pert = Perturbator(settings=settings, initial_SOP=SOP(n_exp=1),
                       klog=KMOLogger(filename=str(tmp_path / "pert2.log")))
    original_active.append("p1")
    assert settings["active_p"] == ["p0", "p1"]
    assert pert.select == ["p0", "p1"]


# ===========================================================================
# perturb / perturb_vibrations (rejection loop, call order, error paths)
# ===========================================================================
from kimeco.bimolecular import Bimolecular  # noqa: E402
from kimeco.enums import FreqMode  # noqa: E402
from typing import cast  # noqa: E402

_PERT_STD = {'std_fact': 0.1, 'std_pow': 0.5, 'std_sigma': 0.1,
             'std_epsilon': 0.1, 'std_bfc': 1.1, 'std_freq': 1.1, 'max_std': 3,
             'distrib_fact': Distrib.NORMAL, 'distrib_pow': Distrib.NORMAL,
             'distrib_sigma': Distrib.NORMAL, 'distrib_epsilon': Distrib.NORMAL,
             'distrib_bfc': Distrib.LOGNORMAL, 'distrib_freq': Distrib.LOGNORMAL}


def _scripted_pert(select: list[str], i_sop: Any) -> tuple[Perturbator, list]:
    """Real Perturbator whose get_rng returns -1, 1e9, then i_val*1.01."""
    settings = dict(_PERT_STD, active_p=list(select))
    klog = SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None,
                           warning=lambda *a, **k: None)
    pert = Perturbator(settings, SimpleNamespace(), klog)
    pert.i_sop = i_sop
    draws: list[tuple[str, Any]] = []
    attempts: dict[str, int] = {}

    def _rng(ptype, i_val, c_val, param, distrib):
        draws.append((param, distrib))
        attempts[param] = attempts.get(param, 0) + 1
        return {1: -1.0, 2: 1e9}.get(attempts[param], i_val * 1.01)

    pert.get_rng = _rng
    return pert, draws


def test_perturb_rejection_samples_global_parameters_then_items() -> None:
    def _i_sop() -> Any:
        return SimpleNamespace(factor=1.0, power=0.8, sigmas=[3.0, 4.0],
                               epsilons=[100.0, 200.0], uncertainties={})

    select = ['__fact', '__pow', '__sigma0', '__epsilon1']
    pert, draws = _scripted_pert(select, _i_sop())
    order: list[str] = []
    pert.perturb_well = lambda w: order.append(f'well:{w}')
    pert.perturb_bimolecular = lambda b: order.append(f'bim:{b}')
    pert.perturb_barrier = lambda b: order.append(f'bar:{b}')
    sop = SimpleNamespace(factor=1.0, power=0.8, sigmas=[3.0, 4.0],
                          epsilons=[100.0, 200.0], wells=['W1', 'W2'],
                          bimolecular=['B1'], barriers=['TS1'])
    out = pert.perturb(cast(Any, sop))
    assert out is sop
    assert sop.factor == pytest.approx(1.01)
    assert sop.power == pytest.approx(0.808)
    assert sop.sigmas == pytest.approx([3.03, 4.0])
    assert sop.epsilons == pytest.approx([100.0, 202.0])
    assert [p for p, _ in draws] == [p for p in select for _ in range(3)]
    assert {d for _, d in draws} == {Distrib.NORMAL}
    assert order == ['well:W1', 'well:W2', 'bim:B1', 'bar:TS1']

    pert, draws = _scripted_pert([], _i_sop())
    pert.perturb_well = pert.perturb_bimolecular = pert.perturb_barrier = lambda x: None
    sop = SimpleNamespace(factor=1.0, power=0.8, sigmas=[3.0], epsilons=[100.0],
                          wells=[], bimolecular=[], barriers=[])
    pert.perturb(cast(Any, sop))
    assert draws == []
    assert (sop.factor, sop.power, sop.sigmas, sop.epsilons) == (1.0, 0.8, [3.0], [100.0])


def test_perturb_vibrations_batch_individual_and_errors() -> None:
    def _setup(select: list[str], mode: Any):
        i_sop = SimpleNamespace(uncertainties={}, items={
            'W': SimpleNamespace(bfc=1.0, ifc=[1.0, 1.0]),
            'BM': Bimolecular('BM', [0])})
        pert, draws = _scripted_pert(select, i_sop)
        pert.settings['freq_mode'] = mode
        return pert, draws

    well = SimpleNamespace(name='W', bfc=1.0, ifc=[1.0, 1.0])
    pert, draws = _setup(['W__bfc'], FreqMode.BATCH)
    pert.perturb_vibrations(cast(Any, well))
    assert well.bfc == pytest.approx(1.01)
    assert draws == [('W__bfc', Distrib.LOGNORMAL)] * 3

    well = SimpleNamespace(name='W', bfc=1.0, ifc=[1.0, 1.0])
    pert, draws = _setup([], FreqMode.BATCH)
    pert.perturb_vibrations(cast(Any, well))
    assert well.bfc == 1.0 and draws == []

    pert, _ = _setup(['BM__bfc'], FreqMode.BATCH)
    with pytest.raises(TypeError, match='Unexpected BFC'):
        pert.perturb_vibrations(cast(Any, SimpleNamespace(name='BM', bfc=1.0)))

    well = SimpleNamespace(name='W', bfc=1.0, ifc=[1.0, 1.0])
    pert, draws = _setup(['W__freq01'], FreqMode.INDIVIDUAL)
    pert.perturb_vibrations(cast(Any, well))
    assert well.ifc == pytest.approx([1.0, 1.01])
    assert [p for p, _ in draws] == ['W__freq01'] * 3

    pert, _ = _setup(['BM__freq00'], FreqMode.INDIVIDUAL)
    with pytest.raises(TypeError, match='Unexpected IFC'):
        pert.perturb_vibrations(cast(Any, SimpleNamespace(name='BM', ifc=[1.0])))

    pert, _ = _setup([], 'other')
    with pytest.raises(TypeError, match='Unknown frequency perturbation mode'):
        pert.perturb_vibrations(cast(Any, well))
