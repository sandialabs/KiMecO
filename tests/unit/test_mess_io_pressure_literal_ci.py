"""Upstream canary: ``mess_io`` still writes ``PressureList[atm]``.

The emitted automech driver relabels mess_io's hardcoded ``[atm]`` pressure
keyword to KiMecO's own unit with a plain ``str.replace`` of the exact literal
``PressureList[atm]`` (it raises if the literal is absent, rather than
shipping a MESS input whose declared unit contradicts the grid).

That contract rests on an assumption about a third-party package. This module
checks the assumption against the *real* ``mess_io`` so an upstream change
shows up here, as an actionable failure, instead of as a raised driver on a
compute node halfway through an optimization.

``mess_io`` is an optional (``automech`` extra) dependency: these cases skip
when it is missing, and fail instead when ``KIMECO_REQUIRE_EXTRAS`` lists
``automech`` (as the ``test-automech-extra`` CI job does). No MESS binary is
executed - only the input writer is called.
"""
from __future__ import annotations

import re

import pytest

from tests.unit.test_installation_extras_ci import import_or_skip

TEMPERATURES = [500.0, 1000.0]
PRESSURES = [0.01, 0.1, 1.0, 10.0]


def _globkey_str() -> str:
    writer = import_or_skip('automech', 'mess_io.writer')
    return writer.global_rates_input_v1(
        temperatures=TEMPERATURES,
        pressures=PRESSURES,
        well_extension=None,
        ktp_outname='G0000E0001P03.out')


def test_mess_io_still_emits_the_expected_atm_literal() -> None:
    """The exact literal the driver replaces."""
    assert 'PressureList[atm]' in _globkey_str()


def test_mess_io_emits_exactly_one_pressure_list_keyword() -> None:
    """A second occurrence would be silently relabelled too."""
    assert _globkey_str().count('PressureList[') == 1


def test_mess_io_writes_the_pressures_it_is_given() -> None:
    """mess_io labels the unit but never rescales the grid."""
    match = re.search(r'PressureList\[[^\]]+\]([^\n]*)', _globkey_str())
    assert match is not None
    assert [float(v) for v in match.group(1).split()] == PRESSURES


def test_replacing_the_literal_yields_the_kimeco_unit_line() -> None:
    """The driver's rewrite, applied to the real upstream output."""
    rewritten = _globkey_str().replace(
        'PressureList[atm]', 'PressureList[bar]')
    assert 'PressureList[bar]' in rewritten
    assert 'atm' not in rewritten
