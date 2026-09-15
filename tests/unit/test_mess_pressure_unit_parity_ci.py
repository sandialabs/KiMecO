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
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import re
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_input import MessInputReader
from kimeco.writers.automech_kin import AutomechKinWriter
from kimeco.writers.mess import MessWriter

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
def test_both_pipelines_write_the_same_pressure_unit(
        normal_pipeline, automech_globkey) -> None:
    """THE test: unit equality, asserted without naming a unit."""
    _sop, normal_inp = normal_pipeline
    assert _unit(automech_globkey) == _unit(normal_inp)


def test_both_pipelines_write_bar(normal_pipeline, automech_globkey) -> None:
    """Pinning the shared unit: SOP pressures are stored in bar."""
    _sop, normal_inp = normal_pipeline
    assert _unit(normal_inp) == 'bar'
    assert _unit(automech_globkey) == 'bar'


def test_both_pipelines_write_the_unconverted_sop_grid(
        normal_pipeline, automech_globkey) -> None:
    """Parity cannot be faked by relabelling a converted grid."""
    sop, normal_inp = normal_pipeline
    assert sop.pres == GRID_PRES
    assert _grid(normal_inp) == pytest.approx(sop.pres)
    assert _grid(automech_globkey) == pytest.approx(sop.pres)
    assert _grid(automech_globkey) == pytest.approx(_grid(normal_inp))


def test_neither_pipeline_emits_atm(
        normal_pipeline, automech_globkey) -> None:
    """``atm`` must not survive anywhere in either MESS input text."""
    _sop, normal_inp = normal_pipeline
    assert 'atm' not in normal_inp
    assert 'atm' not in automech_globkey


def test_both_pipelines_read_the_unit_from_the_same_sop_attribute(
        normal_pipeline) -> None:
    """Structural parity: one source of truth, ``SOP.pres_unit``.

    The normal pipeline renders ``PressureList[{SOP.pres_unit}]``; the
    automech writer copies the same attribute into the emitted
    ``PRES_UNIT``. Asserted against the *real* parsed SOP, so the two cannot
    drift apart through a second, private default.
    """
    sop, normal_inp = normal_pipeline
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)
    assert writer.pres_unit == sop.pres_unit == _unit(normal_inp)


def test_exactly_one_pressure_list_keyword_per_pipeline(
        normal_pipeline, automech_globkey) -> None:
    """A second, stale grid line would silently override the first."""
    _sop, normal_inp = normal_pipeline
    assert normal_inp.count('PressureList[') == 1
    assert automech_globkey.count('PressureList[') == 1


# NOTE: a parity case under a *non-default* unit (e.g. 'torr') was designed
# but dropped: the normal pipeline pins ``SOP.pres_unit = 'bar'`` in
# ``MessInputReader.__init__`` (kimeco/readers/mess_input.py), which is frozen
# for this change, so no CI-reachable input makes it emit another unit. The
# automech-side half of that case (``pres_unit`` follows ``sop.pres_unit``) is
# covered in ``test_automech_units_ci.py``.
