"""CI-safe tests for the perturbation-distribution validation matrix.

These tests lock the three-way, Pclass-dependent distribution rule enforced
by ``KMOInput.set_default_values`` for every ``distrib_<ptype>`` keyword:

* ADDITIVE  parameters (we, be, pow)          -> uniform / normal only
* PERCENT   parameters (hrs, sigma, epsilon,  -> uniform / normal only
            fact)
* MULTIPLICATIVE parameters (if, freq, bfc,   -> log-uniform / log-normal only
            sfc, mrc)

Everything is exercised through the backend directly (no MESS/HPC), using a
lightweight fake logger so no real logging side effects occur.
"""

from types import SimpleNamespace
from typing import Any

from kimeco.enums import Distrib, Pclass, Ptype
from kimeco.user_input import KMOInput


# All perturbation parameter types that carry a distribution keyword, i.e.
# every Ptype that belongs to one of the three Pclass categories (SCORE has
# no distribution and is therefore excluded).
_CATEGORY_OF: dict[str, Pclass] = {}
for _pclass in Pclass:
    for _pvalue in _pclass.value:
        _CATEGORY_OF[_pvalue] = _pclass

DISTRIB_PTYPES = [p for p in Ptype if p.value in _CATEGORY_OF]
ALL_DISTRIBS = list(Distrib)

LOG_DISTRIBS = {Distrib.LOGNORMAL, Distrib.LOGUNIFORM}


def _is_allowed(ptype: Ptype, distrib: Distrib) -> bool:
    """Expected acceptance, derived from Pclass + Distrib (not hardcoded)."""
    category = _CATEGORY_OF[ptype.value]
    if category is Pclass.MULTIPLICATIVE:
        return distrib in LOG_DISTRIBS
    # ADDITIVE and PERCENT both allow only the non-log distributions.
    return distrib not in LOG_DISTRIBS


def _make_input(json_file: dict[str, Any]) -> KMOInput:
    """Build a KMOInput without running __init__ (no file/logger needed)."""
    ui = object.__new__(KMOInput)
    ui.cancel_run = False
    ui.json_file = json_file
    ui.klog = SimpleNamespace(
        warning=lambda *a, **k: None,
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    return ui


# --- Full 12 ptypes x 4 distributions matrix (48 combos) -------------------

def test_backend_distribution_matrix() -> None:
    """Every (ptype, distrib) combo is accepted iff the Pclass rule allows
    it; accepted values are coerced to the Distrib enum in place. Guards the
    intended coverage: 12 ptypes x 4 distributions."""
    assert len(DISTRIB_PTYPES) == 12
    assert len(ALL_DISTRIBS) == 4
    failures: list[str] = []
    for ptype in DISTRIB_PTYPES:
        for distrib in ALL_DISTRIBS:
            key = f"distrib_{ptype.value}"
            ui = _make_input({key: distrib.value})
            ui.set_default_values()
            allowed = _is_allowed(ptype, distrib)
            if ui.cancel_run is not (not allowed):
                failures.append(f"{key}={distrib.value} expected "
                                f"{'allowed' if allowed else 'rejected'}")
            elif allowed and ui.json_file[key] != distrib:
                failures.append(f"{key}={distrib.value} not coerced: "
                                f"{ui.json_file[key]!r}")
    assert not failures, "\n".join(failures)


# --- Standard (happy-path) cases -------------------------------------------

def test_defaults_leave_cancel_run_false() -> None:
    """Empty json_file: defaults are filled and nothing is rejected."""
    ui = _make_input({})
    ui.set_default_values()
    assert ui.cancel_run is False
    # Defaults are coerced to Distrib enums for every distribution keyword.
    for ptype in DISTRIB_PTYPES:
        assert isinstance(ui.json_file[f"distrib_{ptype.value}"], Distrib)


# --- Edge cases ------------------------------------------------------------

def test_unknown_or_miscased_distribution_values() -> None:
    """An unrecognised distribution string cancels the run (one per
    category); mixed-case values are casefolded, validated and coerced; a
    disallowed distribution is rejected regardless of casing."""
    failures: list[str] = []
    for ptype in (Ptype.WE, Ptype.IF, Ptype.HRS):
        ui = _make_input({f"distrib_{ptype.value}": "triangular"})
        ui.set_default_values()
        if ui.cancel_run is not True:
            failures.append(f"{ptype.value}=triangular not rejected")
    for ptype, raw, expected in (
            (Ptype.WE, "Normal", Distrib.NORMAL),
            (Ptype.BE, "UNIFORM", Distrib.UNIFORM),
            (Ptype.IF, "LOG-NORMAL", Distrib.LOGNORMAL),
            (Ptype.MRC, "Log-Uniform", Distrib.LOGUNIFORM),
            (Ptype.HRS, "NoRmAl", Distrib.NORMAL)):
        ui = _make_input({f"distrib_{ptype.value}": raw})
        ui.set_default_values()
        got = ui.json_file[f"distrib_{ptype.value}"]
        if ui.cancel_run is not False or got != expected:
            failures.append(f"{ptype.value}={raw!r}: cancel_run={ui.cancel_run}, "
                            f"value={got!r}, expected {expected!r}")
    ui = _make_input({f"distrib_{Ptype.WE.value}": "LOG-NORMAL"})
    ui.set_default_values()
    if ui.cancel_run is not True:
        failures.append("we='LOG-NORMAL' (disallowed, mis-cased) not rejected")
    assert not failures, "\n".join(failures)


def test_warning_invoked_on_rejected_combo() -> None:
    """The fake klog.warning is called when a combo is rejected."""
    calls: list[str] = []
    ui = _make_input({f"distrib_{Ptype.WE.value}": Distrib.LOGNORMAL.value})
    ui.klog = SimpleNamespace(
        warning=lambda msg, *a, **k: calls.append(msg),
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    ui.set_default_values()
    assert ui.cancel_run is True
    assert calls, "expected klog.warning to be invoked on rejection"
