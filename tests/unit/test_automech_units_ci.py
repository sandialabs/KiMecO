"""CI-safe tests for the bar -> atm unit conversion in ``AutomechKinWriter``.

The SOP stores pressures in bar; MESS expects atm. The writer must perform that
conversion through the cantera/pint unit registry (no hardcoded factor) and
must still emit a *plain literal* driver script: the embedded ``PES_PAYLOAD``
and ``LUMP_PRESSURE`` have to be pure python literals, never ``Quantity``
reprs, so the driver stays importable on a compute node.

Expected values are recomputed here with the same registry rather than
compared against a magic number, so the test cannot drift into re-asserting a
hardcoded conversion factor.
"""
from __future__ import annotations

import ast
from typing import Any, cast

import cantera.with_units as ctu
import pytest

from kimeco.writers.automech_kin import AutomechKinWriter


_Q = ctu.cantera_units_registry.Quantity


def _bar_to_atm(value: float) -> float:
    """Reference conversion, computed in-test via the unit registry."""
    return float(_Q(float(value), 'bar').to('atm').magnitude)


class _MinimalSOP:
    """Smallest SOP surface ``_build_payload`` reads (no species needed)."""

    def __init__(self, pres: list[float], temp: list[float]) -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = list(temp)
        self.pres = list(pres)

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _writer(pres: list[float],
            temp: list[float] | None = None) -> AutomechKinWriter:
    sop = _MinimalSOP(pres=pres, temp=temp or [500.0, 1000.0])
    return AutomechKinWriter(sop=cast(Any, sop), pes_id=0)


def _emit(tmp_path, pres: list[float],
          temp: list[float] | None = None) -> str:
    writer = _writer(pres, temp)
    filename = 'G0000E0001P03.py'
    writer.write(loc=str(tmp_path), filename=filename)
    return (tmp_path / filename).read_text()


def _literal(script: str, name: str) -> Any:
    """Extract a module-level literal assignment from the emitted script."""
    for node in ast.parse(script).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name
                for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f'{name} not assigned at module level')


def _assign_node(script: str, name: str) -> ast.expr:
    for node in ast.parse(script).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name
                for t in node.targets):
            return node.value
    raise AssertionError(f'{name} not assigned at module level')


# ---------------------------------------------------------------------------
# Standard contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('pres', [
    [1.0],
    [0.01, 0.1, 1.0, 10.0],
    [1.01325, 100.0],
])
def test_grid_pres_converts_bar_to_atm(pres: list[float]) -> None:
    payload = _writer(pres)._build_payload()
    assert payload['grid_pres'] == pytest.approx(
        [_bar_to_atm(p) for p in pres])


def test_grid_pres_entries_are_plain_floats() -> None:
    """Not numpy scalars, not pint Quantities - plain python floats."""
    payload = _writer([0.01, 1.0, 10.0])._build_payload()
    for value in payload['grid_pres']:
        assert type(value) is float


def test_grid_temp_is_not_converted() -> None:
    """Only pressure carries a unit change; temperatures pass through."""
    payload = _writer([1.0], temp=[500.0, 1000.0])._build_payload()
    assert payload['grid_temp'] == [500.0, 1000.0]


def test_sub_pressure_grid_override_is_also_converted() -> None:
    """The postprocessing sub-grid takes the same conversion path."""
    sop = _MinimalSOP(pres=[1.0], temp=[500.0])
    writer = AutomechKinWriter(
        sop=cast(Any, sop), pes_id=0, sub_p=[0.5, 5.0], sub_t=[700.0])
    payload = writer._build_payload()
    assert payload['grid_pres'] == pytest.approx(
        [_bar_to_atm(0.5), _bar_to_atm(5.0)])


# ---------------------------------------------------------------------------
# Emitted-script literal guarantees
# ---------------------------------------------------------------------------
def test_emitted_payload_round_trips_through_literal_eval(tmp_path) -> None:
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    payload = _literal(script, 'PES_PAYLOAD')
    assert isinstance(payload, dict)
    assert payload['grid_pres'] == pytest.approx(
        [_bar_to_atm(p) for p in (0.01, 1.0, 10.0)])


def test_emitted_lump_pressure_is_a_plain_float_literal(tmp_path) -> None:
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    node = _assign_node(script, 'LUMP_PRESSURE')
    # A bare numeric constant, not a Call such as Q_(...).to('atm').magnitude.
    assert isinstance(node, ast.Constant)
    value = _literal(script, 'LUMP_PRESSURE')
    assert type(value) is float
    # It is the max of the *converted* grid.
    assert value == pytest.approx(_bar_to_atm(10.0))


def test_emitted_script_has_no_quantity_or_registry_tokens(tmp_path) -> None:
    """The driver must not need pint/cantera to import."""
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    for token in ('Quantity', 'pint', 'cantera', 'ureg', 'Q_', 'magnitude'):
        assert token not in script


def test_emitted_script_still_compiles_with_converted_grid(tmp_path) -> None:
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    compile(script, 'units.py', 'exec')


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
def test_empty_pressure_grid_yields_empty_list_and_default_lump(
        tmp_path) -> None:
    sop = _MinimalSOP(pres=[1.0], temp=[500.0])
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0, sub_p=[])
    assert writer._build_payload()['grid_pres'] == []

    writer.write(loc=str(tmp_path), filename='G0000E0001P03.py')
    script = (tmp_path / 'G0000E0001P03.py').read_text()
    assert _literal(script, 'PES_PAYLOAD')['grid_pres'] == []
    # max() of an empty grid falls back to the documented 1.0 default.
    assert _literal(script, 'LUMP_PRESSURE') == 1.0


def test_zero_pressure_converts_to_zero_atm() -> None:
    payload = _writer([0.0, 1.0])._build_payload()
    assert payload['grid_pres'][0] == 0.0
    assert payload['grid_pres'][1] == pytest.approx(_bar_to_atm(1.0))


def test_integer_pressures_are_coerced_to_float() -> None:
    payload = _writer(cast(Any, [1, 10]))._build_payload()
    assert [type(p) for p in payload['grid_pres']] == [float, float]
    assert payload['grid_pres'] == pytest.approx(
        [_bar_to_atm(1), _bar_to_atm(10)])


def test_conversion_is_strictly_increasing_and_below_bar_value() -> None:
    """1 bar < 1 atm, so every converted value shrinks but keeps order."""
    pres = [0.01, 0.1, 1.0, 10.0]
    grid = _writer(pres)._build_payload()['grid_pres']
    assert grid == sorted(grid)
    assert all(a < b for a, b in zip(grid, pres))
