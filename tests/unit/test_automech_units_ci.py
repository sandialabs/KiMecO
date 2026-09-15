"""CI-safe tests for the pressure-unit pass-through in ``AutomechKinWriter``.

The SOP stores pressures in bar and ``MessOutputReader`` indexes results
against that very bar grid, so the automech writer must hand the grid to the
emitted driver **unconverted** and label it with the SOP's own unit. An
earlier bar -> atm conversion silently shifted the grid (0.01 bar -> 0.00987)
and blew up the output reader with ``ValueError: 0.00987 is not in list``.

Two families of guarantee are checked here:

* *numeric* - ``_build_payload``/``write`` pass ``SOP.pres`` through verbatim
  (no factor, no rounding), and the unit label follows ``SOP.pres_unit``;
* *structural* - the emitted driver stays a plain-literal script: the embedded
  ``PES_PAYLOAD`` and ``LUMP_PRESSURE`` are pure python literals (never
  ``Quantity`` reprs) and the file mentions no unit-registry token, so the
  driver imports on a bare compute node without cantera/pint.
"""
from __future__ import annotations

import ast
import inspect
import re
from typing import Any, cast

import pytest

from kimeco.writers import automech_kin
from kimeco.writers.automech_kin import AutomechKinWriter


class _MinimalSOP:
    """Smallest SOP surface ``_build_payload`` reads (no species needed)."""

    def __init__(self, pres: list[float], temp: list[float],
                 pres_unit: str | None = 'bar') -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = list(temp)
        self.pres = list(pres)
        if pres_unit is not None:
            self.pres_unit = pres_unit

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _writer(pres: list[float],
            temp: list[float] | None = None,
            pres_unit: str | None = 'bar') -> AutomechKinWriter:
    sop = _MinimalSOP(pres=pres, temp=temp or [500.0, 1000.0],
                      pres_unit=pres_unit)
    return AutomechKinWriter(sop=cast(Any, sop), pes_id=0)


def _emit(tmp_path, pres: list[float],
          temp: list[float] | None = None,
          pres_unit: str | None = 'bar') -> str:
    writer = _writer(pres, temp, pres_unit)
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
# Standard contract: the grid is passed through, never converted
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('pres', [
    [1.0],
    [0.01, 0.1, 1.0, 10.0],
    [1.01325, 100.0],
])
def test_grid_pres_is_the_sop_grid_unchanged(pres: list[float]) -> None:
    payload = _writer(pres)._build_payload()
    # Exact equality, not approx: no conversion factor may be applied.
    assert payload['grid_pres'] == pres


def test_grid_pres_entries_are_plain_floats() -> None:
    """Not numpy scalars, not pint Quantities - plain python floats."""
    payload = _writer([0.01, 1.0, 10.0])._build_payload()
    for value in payload['grid_pres']:
        assert type(value) is float


def test_grid_temp_is_not_converted() -> None:
    payload = _writer([1.0], temp=[500.0, 1000.0])._build_payload()
    assert payload['grid_temp'] == [500.0, 1000.0]


def test_sub_pressure_grid_override_is_also_passed_through() -> None:
    """The postprocessing sub-grid takes the same (non-)conversion path."""
    sop = _MinimalSOP(pres=[1.0], temp=[500.0])
    writer = AutomechKinWriter(
        sop=cast(Any, sop), pes_id=0, sub_p=[0.5, 5.0], sub_t=[700.0])
    assert writer._build_payload()['grid_pres'] == [0.5, 5.0]


def test_writer_takes_its_unit_from_the_sop() -> None:
    assert _writer([1.0], pres_unit='bar').pres_unit == 'bar'
    assert _writer([1.0], pres_unit='torr').pres_unit == 'torr'


def test_writer_unit_defaults_to_bar_when_the_sop_has_none() -> None:
    """SOPs built outside ``MessInputReader`` still get the documented bar."""
    assert _writer([1.0], pres_unit=None).pres_unit == 'bar'


# ---------------------------------------------------------------------------
# Emitted-script guarantees
# ---------------------------------------------------------------------------
def test_emitted_payload_round_trips_through_literal_eval(tmp_path) -> None:
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    payload = _literal(script, 'PES_PAYLOAD')
    assert isinstance(payload, dict)
    assert payload['grid_pres'] == [0.01, 1.0, 10.0]


def test_emitted_pres_unit_is_a_plain_string_literal(tmp_path) -> None:
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    node = _assign_node(script, 'PRES_UNIT')
    assert isinstance(node, ast.Constant)
    assert _literal(script, 'PRES_UNIT') == 'bar'


def test_emitted_pres_unit_follows_the_sop_unit(tmp_path) -> None:
    script = _emit(tmp_path, [1.0], pres_unit='torr')
    assert _literal(script, 'PRES_UNIT') == 'torr'


def test_emitted_lump_pressure_is_a_plain_float_literal(tmp_path) -> None:
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    node = _assign_node(script, 'LUMP_PRESSURE')
    # A bare numeric constant, not a Call such as Q_(...).to('atm').magnitude.
    assert isinstance(node, ast.Constant)
    value = _literal(script, 'LUMP_PRESSURE')
    assert type(value) is float
    # The max of the grid, in the same (bar) unit as the grid itself.
    assert value == 10.0


def test_emitted_script_has_no_quantity_or_registry_tokens(tmp_path) -> None:
    """The driver must not need pint/cantera to import."""
    script = _emit(tmp_path, [0.01, 1.0, 10.0])
    for token in ('Quantity', 'pint', 'cantera', 'ureg', 'Q_', 'magnitude'):
        assert token not in script


def test_writer_module_imports_no_unit_registry() -> None:
    """The conversion machinery is gone from the writer itself, too."""
    source = inspect.getsource(automech_kin)
    import_lines = [line for line in source.splitlines()
                    if re.match(r'\s*(import|from)\s', line)]
    for token in ('cantera', 'pint'):
        assert not any(token in line for line in import_lines), token
    for token in ('ureg', 'Q_'):
        assert re.search(rf'\b{re.escape(token)}\b', source) is None, token


def test_emitted_script_compiles(tmp_path) -> None:
    compile(_emit(tmp_path, [0.01, 1.0, 10.0]), 'units.py', 'exec')


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


def test_zero_pressure_stays_zero() -> None:
    payload = _writer([0.0, 1.0])._build_payload()
    assert payload['grid_pres'] == [0.0, 1.0]


def test_integer_pressures_are_coerced_to_float_without_rescaling() -> None:
    payload = _writer(cast(Any, [1, 10]))._build_payload()
    assert [type(p) for p in payload['grid_pres']] == [float, float]
    assert payload['grid_pres'] == [1.0, 10.0]


def test_low_pressure_point_is_bit_identical_to_the_sop_value() -> None:
    """Regression for ``ValueError: 0.00987 is not in list``.

    0.01 bar became 0.00987 atm, which ``MessOutputReader._safe_index`` then
    could not find in the (bar) rate-coefficient grid.
    """
    grid = _writer([0.01, 0.1, 1.0, 10.0])._build_payload()['grid_pres']
    assert grid[0] == 0.01
    assert repr(grid[0]) == repr(0.01)
    assert 0.00987 not in grid


def test_no_scaling_is_applied_to_any_point() -> None:
    """Every emitted point equals its input exactly, order preserved."""
    pres = [0.01, 0.1, 1.0, 10.0]
    script_grid = _writer(pres)._build_payload()['grid_pres']
    assert script_grid == pres
    assert all(a == b for a, b in zip(script_grid, pres))
