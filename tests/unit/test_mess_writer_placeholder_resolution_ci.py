from __future__ import annotations

from typing import Any, cast

import pytest

from kimeco.writers.mess import MessWriter


class _DummyRotor:
    def __init__(self) -> None:
        self._sym = 3.5
        self.iem = 1200.0
        self.file = "pes_surface.dat"
        self.qlem = 800.0

    @property
    def symFact(self) -> float:
        return self._sym


class _DummyWell:
    def __init__(self) -> None:
        self.m_rotors = [_DummyRotor()]
        self.energy = 12.0

    def __getattr__(self, name: str) -> Any:
        if name == "r_scan(0)":
            return "scan-values"
        raise AttributeError(name)


class _DummySOP:
    def __init__(self) -> None:
        self.items = {"WELL": _DummyWell()}
        self.parameters_names: dict[str, str] = {}


class _GridSOP:
    """SOP exposing the default rate-grid placeholders."""

    def __init__(self) -> None:
        self.items: dict[str, Any] = {}
        self.parameters_names: dict[str, str] = {}
        self.r_rc_temp = "DEFAULT_TEMP"
        self.r_rc_pres = "DEFAULT_PRES"


def test_resolve_plain_placeholder() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    assert writer._resolve_placeholder("WELL.energy") == 12.0


def test_resolve_indexed_placeholder() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    assert writer._resolve_placeholder("WELL.m_rotors[0].symFact") == 3.5
    assert writer._resolve_placeholder("WELL.m_rotors[0].iem") == 1200.0
    assert (
        writer._resolve_placeholder("WELL.m_rotors[0].file")
        == "pes_surface.dat"
    )
    assert writer._resolve_placeholder("WELL.m_rotors[0].qlem") == 800.0


def test_resolve_method_like_token_is_preserved() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    assert writer._resolve_placeholder("WELL.r_scan(0)") == "scan-values"


def test_resolve_invalid_index_token_raises_value_error() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    with pytest.raises(ValueError, match="Invalid indexed token"):
        writer._resolve_placeholder("WELL.m_rotors[x].symFact")


def test_resolve_out_of_bounds_index_raises_value_error() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    with pytest.raises(ValueError, match="Cannot index token"):
        writer._resolve_placeholder("WELL.m_rotors[1].symFact")


# ---------------------------------------------------------------------------
# Optional pres/temp override (postprocessing sub-grid)
# ---------------------------------------------------------------------------
def test_pres_temp_override_limits_grid() -> None:
    writer = MessWriter(
        SOP=cast(Any, _GridSOP()), tpl=[], pres=[1.0, 2.0], temp=[300.0])

    # Overrides short-circuit the SOP lookup and format the sub-grid.
    assert writer._resolve_placeholder("SOP.r_rc_pres") == (
        "  1.0000  2.0000\n")
    assert writer._resolve_placeholder("SOP.r_rc_temp") == "  300.00\n"


def test_missing_override_falls_back_to_sop_grid() -> None:
    writer = MessWriter(SOP=cast(Any, _GridSOP()), tpl=[])

    # No override -> existing SOP.r_rc_* attributes are used.
    assert writer._resolve_placeholder("SOP.r_rc_pres") == "DEFAULT_PRES"
    assert writer._resolve_placeholder("SOP.r_rc_temp") == "DEFAULT_TEMP"


def test_partial_override_only_affects_its_own_placeholder() -> None:
    # Only pres is overridden; temp still resolves from the SOP attribute.
    writer = MessWriter(SOP=cast(Any, _GridSOP()), tpl=[], pres=[5.0])

    assert writer._resolve_placeholder("SOP.r_rc_pres") == "  5.0000\n"
    assert writer._resolve_placeholder("SOP.r_rc_temp") == "DEFAULT_TEMP"


# ---------------------------------------------------------------------------
# Grid formatting: 5 significant figures whatever the magnitude
# ---------------------------------------------------------------------------
def test_override_keeps_sub_bar_pressure_precision() -> None:
    # Regression: fixed 2 decimals wrote 0.033 bar as 0.03, so the MESS
    # output pressures no longer matched the pp_pres grid.
    writer = MessWriter(
        SOP=cast(Any, _GridSOP()), tpl=[], pres=[0.01, 0.033, 0.33])

    assert writer._resolve_placeholder("SOP.r_rc_pres") == (
        "  0.010000  0.033000  0.33000\n")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "  0.0000\n"),
        (1e-5, "  0.000010000\n"),
        (0.000123456, "  0.00012346\n"),
        (3.3, "  3.3000\n"),
        (33.0, "  33.000\n"),
        (100.0, "  100.00\n"),
        (1000.0, "  1000.0\n"),
        # Rounding carries into the next magnitude: still 5 sig. figs.
        (9.99996, "  10.000\n"),
        # Beyond 5 integer digits there are no decimals left to drop.
        (123456.7, "  123457\n"),
        (-2.5, " -2.5000\n"),
    ],
)
def test_fmt_grid_five_significant_figures(
        value: float, expected: str) -> None:
    assert MessWriter._fmt_grid([value]) == expected
