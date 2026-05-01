from kimeco.gui.input_sections.perturbation_section import (
    update_perturbation_config,
)


def test_update_perturbation_config_preserves_zero_weights() -> None:
    config, valid, message, style = update_perturbation_config(
        pert="normal",
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
