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


class TestSchemeRuntime:
    def test_expmc_ga_runtime(self):
        opt, ga, nms, mg = _scheme_runtime(SCHEME_EXPMC_GA, max_gen=10)
        assert opt == "ga"
        assert ga == "exp"
        assert nms == ""
        assert mg == 10

    def test_tournament_ga_runtime(self):
        opt, ga, nms, mg = _scheme_runtime(SCHEME_TOURNAMENT_GA, max_gen=5)
        assert opt == "ga"
        assert ga == "tournament"
        assert nms == ""
        assert mg == 5

    def test_nelder_mead_runtime(self):
        opt, ga, nms, mg = _scheme_runtime(SCHEME_NELDER_MEAD, max_gen=8)
        assert opt == "nelder-mead"
        assert nms == ""
        assert mg == 8

    def test_swarm_nm_forces_max_gen_1(self):
        # Even if user passes max_gen=99, swarm must lock to 1
        opt, ga, nms, mg = _scheme_runtime(SCHEME_SWARM_NM, max_gen=99)
        assert opt == "ga"
        assert ga == "exp"
        assert nms == "G0001"
        assert mg == 1

    def test_swarm_nm_goat_forces_max_gen_1(self):
        opt, ga, nms, mg = _scheme_runtime(SCHEME_SWARM_NM_GOAT, max_gen=99)
        assert opt == "ga"
        assert ga == "exp"
        assert nms == "GT-1"
        assert mg == 1

    def test_swarm_nm_nms_token(self):
        _, _, nms, _ = _scheme_runtime(SCHEME_SWARM_NM, max_gen=1)
        assert nms == "G0001"

    def test_swarm_nm_goat_nms_token(self):
        _, _, nms, _ = _scheme_runtime(SCHEME_SWARM_NM_GOAT, max_gen=1)
        assert nms == "GT-1"

    def test_swarm_always_uses_exp(self):
        for scheme in (SCHEME_SWARM_NM, SCHEME_SWARM_NM_GOAT):
            _, ga, _, _ = _scheme_runtime(scheme, max_gen=1)
            assert ga == "exp"


class TestValidateConfig:
    def test_valid_config(self):
        ok, msg = _validate_config(_config())
        assert ok is True

    def test_invalid_max_gen(self):
        ok, _ = _validate_config(_config(max_gen=0))
        assert ok is False

    def test_invalid_n_mdl(self):
        ok, _ = _validate_config(_config(n_mdl=0))
        assert ok is False

    def test_invalid_nm_fatol(self):
        ok, _ = _validate_config(_config(nm_fatol=0))
        assert ok is False

    def test_invalid_nm_maxiter_negative(self):
        ok, _ = _validate_config(_config(nm_maxiter=-1))
        assert ok is False

    def test_invalid_optimizer_string(self):
        ok, _ = _validate_config(_config(optimizer="unknown"))
        assert ok is False

    def test_invalid_ga_type_for_ga(self):
        ok, _ = _validate_config(_config(optimizer="ga", ga_type="invalid"))
        assert ok is False

    def test_nm_optimizer_any_ga_type_ignored_in_dispatch(self):
        # nelder-mead optimizer is valid regardless of ga_type placeholder
        ok, _ = _validate_config(
            _config(optimizer="nelder-mead", ga_type="tournament")
        )
        assert ok is True

    def test_valid_swarm_payload(self):
        """Swarm scheme emitted payload should pass validation."""
        opt, ga, nms, mg = _scheme_runtime(SCHEME_SWARM_NM, max_gen=1)
        cfg = _config(optimizer=opt, ga_type=ga, NMS_start=nms, max_gen=mg)
        ok, msg = _validate_config(cfg)
        assert ok is True

    def test_valid_goat_swarm_payload(self):
        opt, ga, nms, mg = _scheme_runtime(SCHEME_SWARM_NM_GOAT, max_gen=1)
        cfg = _config(optimizer=opt, ga_type=ga, NMS_start=nms, max_gen=mg)
        ok, msg = _validate_config(cfg)
        assert ok is True
