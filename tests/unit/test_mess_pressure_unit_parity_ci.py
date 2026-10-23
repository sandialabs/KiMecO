"""CI-safe parity test: both pipelines write the SAME MESS pressure unit.

KiMecO can produce a MESS input through two independent code paths:

* the **normal pipeline** - :class:`MessInputReader` turns a user MESS input
  into a template whose grid line is ``PressureList[{SOP.pres_unit}] ...`` and
  :class:`MessWriter` renders it;
* the **automech pipeline** - :class:`AutomechKinWriter` emits a standalone
  driver that builds its global-keyword block with ``mess_io``'s
  ``global_rates_input_v1`` (which always writes ``PressureList[atm]``) and
  then rewrites that literal to the payload's own unit.

The two must agree, because the *same* ``rc_pres`` numbers are fed to both and
the *same* :class:`MessOutputReader` grid is used to index the results. When
they disagreed (automech converting the grid to atm while the reader still
matched against the bar grid) the run died with
``ValueError: 0.00987 is not in list`` - see
``dev_tests/example2/KiMecO.log``.

The primary assertion here is a pure *equality* between the two parsed units,
with no hardcoded literal, so the test keeps its meaning if the project ever
moves off bar. Parity also cannot be faked by relabelling a converted grid:
the numeric grids are compared against ``SOP.pres`` on both sides.

Neither side needs MESS: the normal pipeline only writes text, and the
automech pipeline is exercised through the emitted driver with stubbed
``mess_io``/``phydat`` modules.

The same module closes the loop for the reader side (the payload grid
synthesized into MESS output headers is read back by the frozen
``MessOutputReader``; ``_safe_index`` still rejects the converted 0.00987,
so the fix is the unit, not a looser tolerance) and runs the upstream canary
against the *real* ``mess_io``: it still writes exactly one
``PressureList[atm]`` and never rescales the grid. The canary skips when the
``automech`` extra is missing and fails instead when ``KIMECO_REQUIRE_EXTRAS``
lists it.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_input import MessInputReader
from kimeco.readers.mess_output import MessOutputReader
from kimeco.writers.automech_kin import AutomechKinWriter
from kimeco.writers.mess import MessWriter
from tests.unit.test_installation_extras_ci import import_or_skip


# ===========================================================================
# Parity: normal pipeline vs automech pipeline
# ===========================================================================
DME_ROOT = Path(__file__).resolve().parent.parent / 'parse_pes' / 'dme'
DME_INPUT_JSON = DME_ROOT / 'input.json'


# The shared T/P grid handed to both pipelines, in bar (as stored on the SOP).
GRID_PRES = [0.01, 0.1, 1.0, 10.0]
GRID_TEMP = [500.0, 550.0, 1000.0]
_PRESSURE_LIST = re.compile(r'PressureList\[([^\]]+)\]([^\n]*)')


# ---------------------------------------------------------------------------
# Shared parsing helpers - one regex, applied to both pipelines' output
# ---------------------------------------------------------------------------
def _pressure_line(text: str) -> re.Match[str]:
    match = _PRESSURE_LIST.search(text)
    assert match is not None, 'no PressureList[...] line in:\n' + text
    return match


def _unit(text: str) -> str:
    """The unit written between the brackets of the PressureList keyword."""
    return _pressure_line(text).group(1).strip()


def _grid(text: str) -> list[float]:
    """The numeric pressure grid written on the PressureList line."""
    return [float(tok) for tok in _pressure_line(text).group(2).split()]


# ---------------------------------------------------------------------------
# Normal pipeline: real MessInputReader + real MessWriter
# ---------------------------------------------------------------------------
def _dme_settings() -> dict[str, Any]:
    user_settings = json.loads(DME_INPUT_JSON.read_text())
    return {
        'init_loc': str(DME_ROOT),
        'mess_inputs': user_settings['mess_inputs'],
        'n_exp': 1,
        'score_sp': [],
        'freq_mode': FreqMode.BATCH,
        'rc_temp': list(GRID_TEMP),
        'rc_pres': list(GRID_PRES),
        'pres_unit': user_settings['pres_unit'],
        'force_new_molecules': True,
    }


@pytest.fixture(scope='module')
def normal_pipeline(tmp_path_factory) -> tuple[Any, str]:
    """Return ``(sop, inp_text)`` produced by the normal pipeline."""
    tmp_path = tmp_path_factory.mktemp('normal_pipeline')
    reader = MessInputReader(
        settings=_dme_settings(),
        mechanism_species=[],
        klog=KMOLogger(filename=str(tmp_path / 'parity.log')),
        postprocess=False,
    )
    sop, templates = reader.read()
    MessWriter(SOP=sop, tpl=templates[0]).write(
        loc=str(tmp_path), filename='normal.inp')
    return sop, (tmp_path / 'normal.inp').read_text()


# ---------------------------------------------------------------------------
# automech pipeline: real AutomechKinWriter + emitted driver, mess_io stubbed
# ---------------------------------------------------------------------------
class _MinimalSOP:
    """Smallest SOP surface the automech serializer reads."""

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


def _mess_io_globkey(temperatures, pressures, well_extension, ktp_outname):
    """Stub shaped like the real ``mess_io.writer.global_rates_input_v1``.

    It renders the grid it is *given* under mess_io's hardcoded ``[atm]``
    label, so what the driver parses back is genuinely the payload grid.
    """
    return (
        '!===================================================\n'
        '!  GLOBAL KEYWORDS\n'
        '!===================================================\n'
        'TemperatureList[K]                     '
        + '  '.join(str(float(t)) for t in temperatures) + '\n'
        'PressureList[atm]                      '
        + '  '.join(str(float(p)) for p in pressures) + '\n'
        '!\n'
        'ModelEnergyLimit[kcal/mol]             800.00\n'
        'CalculationMethod                      well-reduction\n'
        'RateOutput                             ' + str(ktp_outname) + '\n'
    )


def _install_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    phycon = types.ModuleType('phydat.phycon')
    setattr(phycon, 'BOHR2ANG', 0.52917721092)
    setattr(phycon, 'EH2WAVEN', 219474.6313702)
    phydat = types.ModuleType('phydat')
    setattr(phydat, 'phycon', phycon)

    writer_mod = types.ModuleType('mess_io.writer')

    def _writer_getattr(name: str):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *a, **k: ''

    setattr(writer_mod, '__getattr__', _writer_getattr)
    setattr(writer_mod, 'global_rates_input_v1', _mess_io_globkey)

    mess_io = types.ModuleType('mess_io')
    setattr(mess_io, 'writer', writer_mod)
    setattr(mess_io, 'well_lumped_input_file', lambda *a, **k: '')

    for name, mod in (('phydat', phydat), ('phydat.phycon', phycon),
                      ('mess_io', mess_io), ('mess_io.writer', writer_mod)):
        monkeypatch.setitem(sys.modules, name, mod)


_counter = itertools.count()


@pytest.fixture
def automech_globkey(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """The global-keyword block the emitted automech driver would write."""
    writer = AutomechKinWriter(sop=cast(Any, _MinimalSOP()), pes_id=0)
    script = tmp_path / 'G0000E0001P03.py'
    writer.write(loc=str(tmp_path), filename=script.name)

    _install_stubs(monkeypatch)
    mod_name = f'parity_driver_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(mod_name, script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, mod_name, mod)
    spec.loader.exec_module(mod)

    return mod._globkey_str('G0000E0001P03.out', None)


# ---------------------------------------------------------------------------
# The parity contract
# ---------------------------------------------------------------------------
def test_both_pipelines_write_the_same_unconverted_pressure_grid(normal_pipeline, automech_globkey) -> None:
    """THE parity test: unit equality asserted without naming a unit, then
    pinned to bar (SOP pressures are stored in bar); both grids equal SOP.pres
    (parity cannot be faked by relabelling a converted grid); no atm anywhere;
    one source of truth, SOP.pres_unit, for both writers; exactly one
    PressureList keyword per pipeline (a stale second line would override the
    first)."""
    # -- test_both_pipelines_write_the_same_pressure_unit: THE test: unit
    #    equality, asserted without naming a unit.
    _sop, normal_inp = normal_pipeline
    assert _unit(automech_globkey) == _unit(normal_inp)

    # -- test_both_pipelines_write_bar: Pinning the shared unit: SOP pressures
    #    are stored in bar.
    _sop, normal_inp = normal_pipeline
    assert _unit(normal_inp) == 'bar'
    assert _unit(automech_globkey) == 'bar'

    # -- test_both_pipelines_write_the_unconverted_sop_grid: Parity cannot be
    #    faked by relabelling a converted grid.
    sop, normal_inp = normal_pipeline
    assert sop.pres == GRID_PRES
    assert _grid(normal_inp) == pytest.approx(sop.pres)
    assert _grid(automech_globkey) == pytest.approx(sop.pres)
    assert _grid(automech_globkey) == pytest.approx(_grid(normal_inp))

    # -- test_neither_pipeline_emits_atm: ``atm`` must not survive anywhere in
    #    either MESS input text.
    _sop, normal_inp = normal_pipeline
    assert 'atm' not in normal_inp
    assert 'atm' not in automech_globkey

    # -- test_both_pipelines_read_the_unit_from_the_same_sop_attribute:
    #    Structural parity: one source of truth, ``SOP.pres_unit``.
    sop, normal_inp = normal_pipeline
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)
    assert writer.pres_unit == sop.pres_unit == _unit(normal_inp)

    # -- test_exactly_one_pressure_list_keyword_per_pipeline: A second, stale
    #    grid line would silently override the first.
    _sop, normal_inp = normal_pipeline
    assert normal_inp.count('PressureList[') == 1
    assert automech_globkey.count('PressureList[') == 1


# ===========================================================================
# Round trip through MessOutputReader (regression for 0.00987)
# ===========================================================================
# The failing run used the GRID_PRES above: 0.01 bar is the point that became
# 0.00987 atm. Its temperatures:
RT_GRID_TEMP = [550.0, 600.0]
SPECIES = ['W1', 'W2']


#: The conversion the writer used to apply (1 bar in atm), to 5 decimals as
#: MESS prints it. Kept as a literal on purpose: it is the value in the log.
CONVERTED_LOW_PRESSURE = 0.00987


class _RoundtripSOP:
    """Smallest SOP surface ``_build_payload`` reads."""

    def __init__(self) -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = list(RT_GRID_TEMP)
        self.pres = list(GRID_PRES)
        self.pres_unit = 'bar'

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _payload_grid() -> list[float]:
    writer = AutomechKinWriter(sop=cast(Any, _RoundtripSOP()), pes_id=0)
    return writer._build_payload()['grid_pres']


def _mess_output(pressures: list[float], unit: str = 'bar') -> str:
    """MESS-shaped rate tables for every (T, P) of ``pressures``."""
    lines = ['Species-Species Rate Tables:', '']
    for p_idx, pres in enumerate(pressures):
        for t_idx, temp in enumerate(RT_GRID_TEMP):
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
        'rc_temp': list(RT_GRID_TEMP),
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
def test_payload_grid_round_trips_through_the_output_reader(tmp_path) -> None:
    """Regression for "ValueError: 0.00987 is not in list": the payload grid (==
    the settings grid) synthesized into MESS output headers (bar, no atm) is
    read back by MessOutputReader, every table landing at its own P and T."""
    _tmp_root = tmp_path
    # -- test_payload_grid_round_trips_through_the_output_reader
    tmp_path = _tmp_root / 'test_payload_grid_round_trips_through_the_output_reader'
    tmp_path.mkdir(parents=True)
    grid = _payload_grid()
    reader = _reader(tmp_path, _mess_output(grid), GRID_PRES)
    reader.read()  # used to raise ValueError: 0.00987 is not in list

    # -- test_every_table_lands_at_its_own_pressure_and_temperature: Right
    #    index, not merely "no exception".
    tmp_path = _tmp_root / 'test_every_table_lands_at_its_own_pressure_and_temperature'
    tmp_path.mkdir(parents=True)
    grid = _payload_grid()
    reader = _reader(tmp_path, _mess_output(grid), GRID_PRES)
    reader.read()

    for p_idx in range(len(GRID_PRES)):
        for t_idx in range(len(RT_GRID_TEMP)):
            expected = 100.0 * (p_idx + 1) + (t_idx + 1)
            assert reader.rc[p_idx, t_idx, 0, 1] == pytest.approx(expected)
            assert reader.rc[p_idx, t_idx, 0, 0] == pytest.approx(5.42)

    # -- test_payload_grid_is_the_settings_grid: The two grids the pipeline
    #    must keep aligned are the same list.
    tmp_path = _tmp_root / 'test_payload_grid_is_the_settings_grid'
    tmp_path.mkdir(parents=True)
    assert _payload_grid() == GRID_PRES

    # -- test_mess_output_headers_carry_the_writer_unit: The synthesized
    #    fixture is honest: it echoes the bar grid.
    tmp_path = _tmp_root / 'test_mess_output_headers_carry_the_writer_unit'
    tmp_path.mkdir(parents=True)
    text = _mess_output(_payload_grid())
    assert 'Pressure = 0.01 bar' in text
    assert 'atm' not in text


# ---------------------------------------------------------------------------
# Characterisation: the fix is the unit, not a looser tolerance
# ---------------------------------------------------------------------------
def test_safe_index_rejects_converted_pressure_but_absorbs_noise(tmp_path) -> None:
    """Characterisation: the fix is the unit, not a looser tolerance.
    _safe_index still rejects 0.00987 against a bar grid and an atm output still
    breaks the reader, while tiny float noise is absorbed."""
    _tmp_root = tmp_path
    # -- test_safe_index_still_rejects_the_converted_low_pressure
    with pytest.raises(ValueError):
        MessOutputReader._safe_index([0.01, 1.0], CONVERTED_LOW_PRESSURE)

    # -- test_converted_grid_still_breaks_the_reader: The original failure,
    #    reproduced: atm output against a bar grid.
    tmp_path = _tmp_root / 'test_converted_grid_still_breaks_the_reader'
    tmp_path.mkdir(parents=True)
    converted = [CONVERTED_LOW_PRESSURE, 0.0987, 0.98692, 9.86923]
    reader = _reader(tmp_path, _mess_output(converted, unit='atm'), GRID_PRES)
    with pytest.raises(ValueError, match=str(CONVERTED_LOW_PRESSURE)):
        reader.read()

    # -- test_safe_index_tolerance_is_unchanged_for_tiny_float_noise: Rounding
    #    noise is still absorbed; only real unit shifts fail.
    assert MessOutputReader._safe_index([0.01, 1.0], 0.0100000001) == 0
    assert MessOutputReader._safe_index([0.01, 1.0], 0.01) == 0
    assert MessOutputReader._safe_index([0.01, 1.0], 1.0) == 1


# ===========================================================================
# Upstream canary: real mess_io still writes PressureList[atm]
# ===========================================================================
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
    """The exact literal the driver replaces, exactly once (a second
    occurrence would be silently relabelled too); mess_io labels the unit
    but never rescales the grid; the driver's rewrite applied to the real
    upstream output yields the KiMecO unit line."""
    block = _globkey_str()
    assert 'PressureList[atm]' in block
    assert block.count('PressureList[') == 1
    match = re.search(r'PressureList\[[^\]]+\]([^\n]*)', block)
    assert match is not None
    assert [float(v) for v in match.group(1).split()] == PRESSURES
    rewritten = block.replace('PressureList[atm]', 'PressureList[bar]')
    assert 'PressureList[bar]' in rewritten
    assert 'atm' not in rewritten

