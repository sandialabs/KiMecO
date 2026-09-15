"""CI-safe regression test for ``ValueError: 0.00987 is not in list``.

Reported in ``dev_tests/example2/KiMecO.log``: the automech pipeline converted
the bar pressure grid to atm before handing it to MESS, so MESS echoed
``Pressure = 0.00987`` in its output while ``MessOutputReader`` still indexed
against the untouched bar grid (``settings['rc_pres'] == [0.01, ...]``) and
``grid.index(...)`` failed.

This module closes the loop *inside CI*: the pressure grid built by
``AutomechKinWriter._build_payload`` is used to synthesize the MESS output
text that MESS would echo back, and the **frozen** ``MessOutputReader`` parses
it. If the writer ever re-introduces a unit conversion, the synthesized
headers stop matching ``rc_pres`` and this test fails with the original error.

The characterisation half asserts that ``_safe_index`` still rejects the
converted value 0.00987 against a bar grid: this is a *unit* fix, not a
widened matching tolerance. ``_safe_index`` is read-only here.

No MESS binary is involved: the output text is synthesized.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_output import MessOutputReader
from kimeco.writers.automech_kin import AutomechKinWriter

# The grid from the failing run: 0.01 bar is the point that became 0.00987 atm.
GRID_PRES = [0.01, 0.1, 1.0, 10.0]
GRID_TEMP = [550.0, 600.0]
SPECIES = ['W1', 'W2']

#: The conversion the writer used to apply (1 bar in atm), to 5 decimals as
#: MESS prints it. Kept as a literal on purpose: it is the value in the log.
CONVERTED_LOW_PRESSURE = 0.00987


class _MinimalSOP:
    """Smallest SOP surface ``_build_payload`` reads."""

    def __init__(self) -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = list(GRID_TEMP)
        self.pres = list(GRID_PRES)
        self.pres_unit = 'bar'

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _payload_grid() -> list[float]:
    writer = AutomechKinWriter(sop=cast(Any, _MinimalSOP()), pes_id=0)
    return writer._build_payload()['grid_pres']


def _mess_output(pressures: list[float], unit: str = 'bar') -> str:
    """MESS-shaped rate tables for every (T, P) of ``pressures``."""
    lines = ['Species-Species Rate Tables:', '']
    for p_idx, pres in enumerate(pressures):
        for t_idx, temp in enumerate(GRID_TEMP):
            value = 100.0 * (p_idx + 1) + (t_idx + 1)
            lines += [
                f'Temperature = {temp:g} K    Pressure = {pres:g} {unit}',
                '',
                'From\\To            W1        W2',
                f'W1                5.42    {value}',
                'W2            3.34e+03   2.01e+05',
                '',
            ]
    lines.append('_' * 70)
    lines.append('')
    return '\n'.join(lines)


def _reader(tmp_path: Path, text: str, grid: list[float]) -> MessOutputReader:
    out = tmp_path / 'G0000E0001P03.out'
    out.write_text(text)
    settings = {
        'postprocess': False,
        'rc_temp': list(GRID_TEMP),
        'rc_pres': list(grid),
    }
    sop = SimpleNamespace(wells_names=list(SPECIES), bimols_names=[])
    return MessOutputReader(
        filename=str(out),
        settings=settings,
        sop=cast(Any, sop),
        klog=KMOLogger(filename=str(tmp_path / 'roundtrip.log')),
    )


# ---------------------------------------------------------------------------
# The regression: writer grid -> MESS output -> reader, without a ValueError
# ---------------------------------------------------------------------------
def test_payload_grid_round_trips_through_the_output_reader(
        tmp_path) -> None:
    grid = _payload_grid()
    reader = _reader(tmp_path, _mess_output(grid), GRID_PRES)
    reader.read()  # used to raise ValueError: 0.00987 is not in list


def test_every_table_lands_at_its_own_pressure_and_temperature(
        tmp_path) -> None:
    """Right index, not merely "no exception"."""
    grid = _payload_grid()
    reader = _reader(tmp_path, _mess_output(grid), GRID_PRES)
    reader.read()

    for p_idx in range(len(GRID_PRES)):
        for t_idx in range(len(GRID_TEMP)):
            expected = 100.0 * (p_idx + 1) + (t_idx + 1)
            assert reader.rc[p_idx, t_idx, 0, 1] == pytest.approx(expected)
            assert reader.rc[p_idx, t_idx, 0, 0] == pytest.approx(5.42)


def test_payload_grid_is_the_settings_grid(tmp_path) -> None:
    """The two grids the pipeline must keep aligned are the same list."""
    assert _payload_grid() == GRID_PRES


def test_mess_output_headers_carry_the_writer_unit(tmp_path) -> None:
    """The synthesized fixture is honest: it echoes the bar grid."""
    text = _mess_output(_payload_grid())
    assert 'Pressure = 0.01 bar' in text
    assert 'atm' not in text


# ---------------------------------------------------------------------------
# Characterisation: the fix is the unit, not a looser tolerance
# ---------------------------------------------------------------------------
def test_safe_index_still_rejects_the_converted_low_pressure() -> None:
    with pytest.raises(ValueError):
        MessOutputReader._safe_index([0.01, 1.0], CONVERTED_LOW_PRESSURE)


def test_converted_grid_still_breaks_the_reader(tmp_path) -> None:
    """The original failure, reproduced: atm output against a bar grid."""
    converted = [CONVERTED_LOW_PRESSURE, 0.0987, 0.98692, 9.86923]
    reader = _reader(tmp_path, _mess_output(converted, unit='atm'), GRID_PRES)
    with pytest.raises(ValueError, match=str(CONVERTED_LOW_PRESSURE)):
        reader.read()


def test_safe_index_tolerance_is_unchanged_for_tiny_float_noise() -> None:
    """Rounding noise is still absorbed; only real unit shifts fail."""
    assert MessOutputReader._safe_index([0.01, 1.0], 0.0100000001) == 0
    assert MessOutputReader._safe_index([0.01, 1.0], 0.01) == 0
    assert MessOutputReader._safe_index([0.01, 1.0], 1.0) == 1
