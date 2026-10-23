"""Unit tests for optimizer section scheme mapping and constraint logic."""

from kimeco.gui.input_sections.optimizer_section import (
    SCHEME_EXPMC_GA,
    SCHEME_NELDER_MEAD,
    SCHEME_SWARM_NM,
    SCHEME_SWARM_NM_GOAT,
    SCHEME_TOURNAMENT_GA,
    _scheme_runtime,
    _validate_config,
)


def _config(**overrides) -> dict:
    """Build minimal valid config with optional overrides."""
    base = {
        "optimizer": "ga",
        "ga_type": "exp",
        "NMS_start": "",
        "max_gen": 10,
        "n_mdl": 500,
        "goat_length": 250,
        "max_score": 4.0,
        "score_conv": 2,
        "param_conv": 0.01,
        "SA_freq": 1000,
        "SA_start": 1,
        "nm_fatol": 1.0,
        "nm_xatol": 0.5,
        "nm_maxiter": 0,
        "nm_maxfev": 0,
        "nm_dstep": 0.5,
        "nm_adaptive": False,
        "nm_final_fatol": 0.05,
        "nm_final_xatol": 0.005,
        "nm_final_maxiter": 0,
        "nm_final_maxfev": 0,
        "nm_final_adaptive": False,
    }
    base.update(overrides)
    return base


def test_ga_scheme_runtime() -> None:
    """Exponential-MC and tournament GA schemes map to the GA optimizer with
    their ga_type, no NM start and the user's max_gen."""
    failures: list[str] = []
    for scheme, ga_type, max_gen in ((SCHEME_EXPMC_GA, "exp", 10),
                                     (SCHEME_TOURNAMENT_GA, "tournament", 5)):
        got = _scheme_runtime(scheme, max_gen=max_gen)
        if got != ("ga", ga_type, "", max_gen):
            failures.append(f"{scheme}: {got}")
    assert not failures, "\n".join(failures)


def test_nm_and_swarm_scheme_runtime() -> None:
    """Nelder-Mead keeps max_gen; the swarm NM scheme locks max_gen to 1
    (even if the user passes 99) and starts from G0001; the GOAT swarm keeps
    max_gen and starts from GT-1; both swarms always use the exp GA."""
    opt, _ga, nms, mg = _scheme_runtime(SCHEME_NELDER_MEAD, max_gen=8)
    assert (opt, nms, mg) == ("nelder-mead", "", 8)
    assert _scheme_runtime(SCHEME_SWARM_NM, max_gen=99) == ("ga", "exp", "G0001", 1)
    assert _scheme_runtime(SCHEME_SWARM_NM_GOAT, max_gen=99) == (
        "ga", "exp", "GT-1", 99)
    for scheme, token in ((SCHEME_SWARM_NM, "G0001"),
                          (SCHEME_SWARM_NM_GOAT, "GT-1")):
        _, ga, nms, _ = _scheme_runtime(scheme, max_gen=1)
        assert nms == token, scheme
        assert ga == "exp", scheme


def test_validate_config_accepts() -> None:
    """The default config, nelder-mead with any ga_type placeholder, and the
    user_settings emitted by both swarm schemes are valid."""
    cases = {"default": _config(),
             "nelder-mead any ga_type": _config(optimizer="nelder-mead",
                                                ga_type="tournament")}
    for scheme in (SCHEME_SWARM_NM, SCHEME_SWARM_NM_GOAT):
        opt, ga, nms, mg = _scheme_runtime(scheme, max_gen=1)
        cases[scheme] = _config(optimizer=opt, ga_type=ga, NMS_start=nms,
                                max_gen=mg)
    rejected = {label: msg for label, cfg in cases.items()
                for ok, msg in [_validate_config(cfg)] if ok is not True}
    assert not rejected, rejected


def test_validate_config_rejects() -> None:
    """max_gen 0, n_mdl 0, nm_fatol 0, a negative nm_maxiter, an unknown
    optimizer and an invalid ga_type for the GA are rejected."""
    cases = {"max_gen=0": _config(max_gen=0),
             "n_mdl=0": _config(n_mdl=0),
             "nm_fatol=0": _config(nm_fatol=0),
             "nm_maxiter=-1": _config(nm_maxiter=-1),
             "optimizer=unknown": _config(optimizer="unknown"),
             "ga_type=invalid": _config(optimizer="ga", ga_type="invalid")}
    accepted = [label for label, cfg in cases.items()
                if _validate_config(cfg)[0] is not False]
    assert not accepted, f"accepted invalid configs: {accepted}"


# ===========================================================================
# Sensitivity section: update_sensitivity_config
# ===========================================================================
def test_update_sensitivity_config_merges_restart_defaults_and_warns() -> None:
    from kimeco.default_settings import default_settings
    from kimeco.gui.input_sections.sensitivity_section import update_sensitivity_config

    hidden = {"display": "none"}
    assert update_sensitivity_config(None, 0.9, [], 1, 2, 1, [], []) == ({}, False, "", hidden)

    restart = [{"generation": 2, "parameters": ["a"]},
               {"generation": 2, "parameters": ["b"]},
               {"generation": None, "parameters": ["c"]},
               {"generation": 3, "parameters": []},
               {"generation": 4, "parameters": ["d"]}]
    config, valid, msg, style = update_sensitivity_config(
        0.1, 0.9, ["W__we"], None, None, None, restart, ["on"])
    assert (valid, msg, style) == (True, "", hidden)
    assert config == {
        "sensi_d": 0.1, "cumul_sensi": 0.9, "active_p": ["W__we"],
        "SA_start": default_settings["SA_start"], "SA_end": default_settings["SA_end"],
        "SA_freq": default_settings["SA_freq"], "SA_restart": {2: ["a", "b"], 4: ["d"]},
        "fix_theory_divider": True}

    config, valid, msg, style = update_sensitivity_config(
        1, 0.5, None, 1, 5, 2, None, [])
    assert config["SA_restart"] == {} and config["active_p"] == []
    assert config["fix_theory_divider"] is False
    assert (valid, msg) == (True, "")

    config, valid, msg, style = update_sensitivity_config(
        0, 1.5, [], 5, 5, 0, [], [])
    assert valid is True and style["display"] == "block"
    items = msg.children[1].children
    assert [li.children for li in items] == [
        "SA_start must be < SA_end", "SA_freq must be >= 1",
        "Derivative step size must be > 0",
        "Cumulative sensitivity must be between 0 and 1"]
