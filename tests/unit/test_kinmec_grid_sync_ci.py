from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest

from kimeco.kinmec import KiMec
from kimeco.well import Well


def _kinmec_stub(pres: list[float],
                 temp: list[float],
                 settings: dict[str, Any]) -> Any:
    """Build a KiMec without running __init__ (which needs a cantera file).

    Only the attributes used by the grid-sync logic are populated, and the
    template rebuild hook is replaced by a call counter so the test does not
    require a full SOP.
    """
    kinmec = cast(Any, KiMec.__new__(KiMec))
    kinmec.pres = pres
    kinmec.temp = temp
    kinmec.settings = settings
    kinmec.rc_tpl = kinmec._build_rc_tpl()
    kinmec.rebuilt = 0

    def _count_rebuild() -> None:
        kinmec.rebuilt += 1

    kinmec.create_reactions_templates = _count_rebuild
    return kinmec


def _settings() -> dict[str, Any]:
    return {
        "rc_pres": [1.0, 2.0],
        "rc_temp": [300.0, 400.0, 500.0],
        "pp_pres": [1.0],
        "pp_temp": [300.0, 400.0, 500.0],
        "pres_unit": "bar",
    }


def test_build_rc_tpl_emits_one_field_per_grid_point() -> None:
    kinmec = _kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    assert kinmec.rc_tpl.count("rc_") == 6
    assert "rc_0_0: {rates[0][0]}" in kinmec.rc_tpl
    assert "rc_1_2: {rates[1][2]}" in kinmec.rc_tpl


def test_sync_switches_to_pp_grid_when_rates_are_postprocess_shaped() -> None:
    # Templates default to the rc grid (2 pressures) but the injected rates
    # were evaluated on the pp grid (1 pressure): the previous code indexed
    # rates[1] on a size-1 axis and raised IndexError.
    kinmec = _kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    pp_rates = {0: np.zeros((1, 3, 2, 2))}
    kinmec._sync_grid_to_rates(pp_rates)

    assert kinmec.pres == [1.0]
    assert kinmec.temp == [300.0, 400.0, 500.0]
    assert kinmec.rc_tpl.count("rc_") == 3
    assert kinmec.rebuilt == 1


def test_sync_is_noop_when_rates_match_current_grid() -> None:
    kinmec = _kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    rc_rates = {0: np.zeros((2, 3, 2, 2))}
    kinmec._sync_grid_to_rates(rc_rates)

    assert kinmec.pres == [1.0, 2.0]
    assert kinmec.rc_tpl.count("rc_") == 6
    assert kinmec.rebuilt == 0


def test_reaction_template_labels_pressure_in_bar() -> None:
    # Grids are always stored in bar, so the Pgrid label must be 'bar'
    # regardless of the user-facing 'pres_unit' setting (the previous code
    # labelled bar values with pres_unit, e.g. '0.1 torr', breaking the
    # rate lookup at simulation time).
    kinmec = _kinmec_stub(pres=[0.1, 1.0],
                          temp=[750.0, 800.0],
                          settings={"pres_unit": "torr"})

    tpl = kinmec.create_reaction_template(
        reactant=Well(name="A", pes_ids=[0]),
        product=Well(name="B", pes_ids=[0]),
    )

    assert "torr" not in tpl
    assert "0.1 bar" in tpl
    assert "1.0 bar" in tpl
    assert "750.0 K" in tpl


def test_sync_raises_when_rates_match_no_known_grid() -> None:
    kinmec = _kinmec_stub(pres=[1.0, 2.0],
                          temp=[300.0, 400.0, 500.0],
                          settings=_settings())

    mismatched_rates = {0: np.zeros((5, 7, 2, 2))}
    with pytest.raises(ValueError):
        kinmec._sync_grid_to_rates(mismatched_rates)

