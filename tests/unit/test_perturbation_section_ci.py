"""CI-safe tests for the kmo_start perturbation section
(``update_perturbation_config`` and the distribution dropdowns).

The stale ``pert`` positional argument (and its ``perturbation-pert-dropdown``
Input) was removed so the callback's parameter list lines up with its declared
Inputs (Defect A): these tests pin the signature and the happy-path contract,
the per-class distribution options, the warning for a multiplicative
parameter with a non-log distribution, and that zero scoring weights are
preserved.
"""

import inspect

from dash import html

from kimeco.enums import Distrib, Pclass
from kimeco.gui.input_sections import perturbation_section as ps
from kimeco.gui.input_sections.perturbation_section import (
    _distrib_options_for_additive,
    _distrib_options_for_multiplicative,
    _distrib_options_for_percent,
    create_perturbation_section,
    update_perturbation_config,
)


# ===========================================================================
# Callback signature (Defect A)
# ===========================================================================
def _valid_kwargs(**overrides):
    """Build a fully-valid kwargs set for update_perturbation_config."""
    additive = set(Pclass.ADDITIVE.value)          # we, be, pow(etp)
    multiplicative = set(Pclass.MULTIPLICATIVE.value)  # freq, bfc, if, sfc, mrc
    # distrib_freq maps to the 'freq' multiplicative class member.
    kwargs = {
        "max_std": 3,
        "weight_theory": 1.0,
        "weight_experiments": 1.0,
        "std_we": 1.0, "std_be": 1.0, "std_bfc": 0.1, "std_hrs": 0.1,
        "std_if": 0.1, "std_etf": 0.1, "std_etp": 1.0, "std_epsi": 0.1,
        "std_sigma": 0.1, "std_sfc": 0.1, "std_mrc": 0.1,
        "conv_we": 0.1, "conv_be": 0.1, "conv_etp": 0.1,
        "specific_std_rows": [],
    }
    # Distributions: multiplicative -> log-normal, others -> normal.
    distrib_members = {
        "distrib_we": "we", "distrib_be": "be", "distrib_freq": "freq",
        "distrib_bfc": "bfc", "distrib_hrs": "hrs", "distrib_if": "if",
        "distrib_etf": "fact", "distrib_etp": "pow", "distrib_epsi": "epsilon",
        "distrib_sigma": "sigma", "distrib_sfc": "sfc", "distrib_mrc": "mrc",
    }
    for arg, member in distrib_members.items():
        if member in multiplicative:
            kwargs[arg] = Distrib.LOGNORMAL.value
        else:
            kwargs[arg] = Distrib.NORMAL.value
    assert additive  # sanity: additive class populated
    kwargs.update(overrides)
    return kwargs


def test_callback_signature_and_valid_four_tuple() -> None:
    """update_perturbation_config has no pert parameter, max_std first, and
    returns a valid 4-tuple."""
    # -- test_signature_has_no_pert_param
    params = list(inspect.signature(update_perturbation_config).parameters)
    assert "pert" not in params

    # -- test_first_param_is_max_std
    params = list(inspect.signature(update_perturbation_config).parameters)
    assert params[0] == "max_std"

    # -- test_callback_returns_valid_four_tuple
    result = update_perturbation_config(**_valid_kwargs())
    assert isinstance(result, tuple)
    assert len(result) == 4
    config, valid, _msg, style = result
    assert isinstance(config, dict)
    assert config["max_std"] == 3
    assert valid is True
    # Fully-valid inputs -> no warning banner shown.
    assert style.get("display") == "none"


def test_no_phantom_pert_dropdown() -> None:
    """Neither the perturbation section source nor its built layout carries the
    phantom pert dropdown id."""
    # -- test_no_phantom_pert_dropdown_in_source
    src = open(ps.__file__, encoding="utf-8").read()
    assert "perturbation-pert-dropdown" not in src

    # -- test_layout_builds_without_phantom_id
    layout = create_perturbation_section()
    assert isinstance(layout, html.Div)


def test_multiplicative_non_log_distribution_warns():
    """Edge: a non-log distrib on a multiplicative param raises a warning."""
    result = update_perturbation_config(
        **_valid_kwargs(distrib_freq=Distrib.UNIFORM.value)
    )
    _config, valid, msg, style = result
    assert valid is True
    assert style.get("display") == "block"
    assert msg != ""


# ===========================================================================
# Distribution options and scoring weights
# ===========================================================================
def _values(options: list) -> set:
    return {opt["value"] for opt in options}


def test_distribution_options_per_class() -> None:
    """Additive and percent options are exactly uniform/normal, multiplicative
    exactly the log distributions, all as label/value dicts; the legacy generic
    options are gone."""
    # -- test_additive_options_are_exactly_uniform_and_normal
    values = _values(_distrib_options_for_additive())
    assert values == {Distrib.UNIFORM.value, Distrib.NORMAL.value}
    assert Distrib.LOGNORMAL.value not in values
    assert Distrib.LOGUNIFORM.value not in values

    # -- test_multiplicative_options_are_exactly_log_distributions
    values = _values(_distrib_options_for_multiplicative())
    assert values == {Distrib.LOGNORMAL.value, Distrib.LOGUNIFORM.value}
    assert Distrib.UNIFORM.value not in values
    assert Distrib.NORMAL.value not in values

    # -- test_percent_options_are_exactly_uniform_and_normal
    values = _values(_distrib_options_for_percent())
    assert values == {Distrib.UNIFORM.value, Distrib.NORMAL.value}
    assert Distrib.LOGNORMAL.value not in values
    assert Distrib.LOGUNIFORM.value not in values

    # -- test_option_helpers_use_label_value_shape
    for helper in (_distrib_options_for_additive,
                   _distrib_options_for_multiplicative,
                   _distrib_options_for_percent):
        options = helper()
        assert len(options) == 2
        for opt in options:
            assert set(opt.keys()) == {"label", "value"}
            assert opt["label"] == opt["value"]

    # -- test_legacy_generic_distrib_options_removed
    assert not hasattr(ps, "_distrib_options")


def test_update_perturbation_config_preserves_zero_weights() -> None:
    config, valid, message, style = update_perturbation_config(
        max_std=4,
        weight_theory=0.0,
        weight_experiments=0.0,
        std_we=1.0,
        std_be=1.5,
        std_bfc=1.05,
        std_hrs=0.1,
        std_if=1.1,
        std_etf=0.25,
        std_etp=0.075,
        std_epsi=0.1,
        std_sigma=0.1,
        std_sfc=2.0,
        std_mrc=1.5,
        distrib_we="normal",
        distrib_be="normal",
        distrib_freq="log-normal",
        distrib_bfc="log-normal",
        distrib_hrs="normal",
        distrib_if="log-normal",
        distrib_etf="normal",
        distrib_etp="normal",
        distrib_epsi="normal",
        distrib_sigma="normal",
        distrib_sfc="log-normal",
        distrib_mrc="log-normal",
        conv_we=0.1,
        conv_be=0.1,
        conv_etp=0.01,
        specific_std_rows=[],
    )

    assert valid is True
    assert config["weight_theory"] == 0.0
    assert config["weight_experiments"] == 0.0
    assert style["display"] == "block"
    assert message is not None



# ===========================================================================
# Per-parameter uncertainty rows: update_specific_std_store
# ===========================================================================
def test_update_specific_std_store_add_remove_edit(monkeypatch) -> None:
    from types import SimpleNamespace

    def _call(triggered, store, params=None, stds=None):
        monkeypatch.setattr(ps, "callback_context",
                            SimpleNamespace(triggered_id=triggered))
        return ps.update_specific_std_store(1, [], params or [], stds or [], store)

    row = {"parameter": "W__we", "std": 1.0}
    other = {"parameter": "B__be", "std": 2.0}

    assert _call("perturbation-specific-std-add-button", [row]) == [
        row, {"parameter": None, "std": None}]

    remove = "perturbation-specific-std-remove"
    assert _call({"type": remove, "index": 1}, [row, other]) == [row]
    assert _call({"type": remove, "index": 9}, [row, other]) == [row, other]
    assert _call({"type": remove, "index": "x"}, [row, other]) == [row, other]

    edit = {"type": "perturbation-specific-std-param", "index": 0}
    assert _call(edit, [row], params=["W__we", "B__be"], stds=[3.0]) == [
        {"parameter": "W__we", "std": 3.0}, {"parameter": "B__be", "std": None}]
    assert _call(edit, [row, other], params=["X", "Y"], stds=[]) == [
        {"parameter": "X", "std": 1.0}, {"parameter": "Y", "std": 2.0}]
    assert _call(edit, "not a list", params=[], stds=[]) == []
    assert _call("perturbation-specific-std-add-button",
                 [row, "junk", {"std": 4.0}]) == [
        row, {"parameter": None, "std": 4.0}, {"parameter": None, "std": None}]
