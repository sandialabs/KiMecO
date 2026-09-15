"""CI-safe tests for ``_globkey_str`` in the emitted automech driver.

``mess_io.writer.global_rates_input_v1`` hardcodes ``PressureList[atm]``.
KiMecO's pressure grid is in bar (``SOP.pres``) and ``MessOutputReader``
indexes the results against that same bar grid, so the driver relabels the
block to ``PressureList[<PRES_UNIT>]`` instead of converting the numbers.

The contract exercised here:

* the exact ``PressureList[atm]`` literal is replaced by the payload unit, and
  nothing else in the mess_io block is touched;
* if that literal is absent - because upstream mess_io changed its unit or its
  formatting - the driver **raises** instead of writing a MESS input whose
  declared unit contradicts the grid. A silent pass-through would reproduce
  the original ``ValueError: 0.00987 is not in list`` failure mode further
  down the pipeline;
* the guard is a ``raise``, not an ``assert``, so it survives ``python -O``
  (compute nodes may run the driver optimized).

No MESS binary and no real automech install are needed: ``mess_io``/``phydat``
are stubbed and only ``_globkey_str`` is called (``main`` never runs).
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import re
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from kimeco.writers.automech_kin import AutomechKinWriter

_FILENAME = 'G0000E0001P03.py'
_OUT = 'G0000E0001P03.out'

_PRES = [0.01, 0.1, 1.0, 10.0]
_TEMP = [500.0, 1000.0]

#: mess_io-shaped global-keyword block (the real writer's layout).
_GLOBKEY_ATM = (
    '!===================================================\n'
    '!  GLOBAL KEYWORDS\n'
    '!===================================================\n'
    'TemperatureList[K]                     500.0  1000.0\n'
    'PressureList[atm]                      0.01  0.1  1.0  10.0\n'
    '!\n'
    'ModelEnergyLimit[kcal/mol]             800.00\n'
    'CalculationMethod                      well-reduction\n'
    'RateOutput                             ' + _OUT + '\n'
)


class _MinimalSOP:
    """Smallest SOP surface the serializer reads (no species needed here)."""

    def __init__(self, pres_unit: str = 'bar') -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = list(_TEMP)
        self.pres = list(_PRES)
        self.pres_unit = pres_unit

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _emit(tmp_path: Path, pres_unit: str = 'bar') -> Path:
    writer = AutomechKinWriter(
        sop=cast(Any, _MinimalSOP(pres_unit)), pes_id=0)
    writer.write(loc=str(tmp_path), filename=_FILENAME)
    return tmp_path / _FILENAME


def _install_stubs(monkeypatch: pytest.MonkeyPatch, globkey: Any) -> None:
    """Stub phydat/mess_io; ``global_rates_input_v1`` returns ``globkey``."""
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
    setattr(writer_mod, 'global_rates_input_v1', lambda *a, **k: globkey)

    mess_io = types.ModuleType('mess_io')
    setattr(mess_io, 'writer', writer_mod)
    setattr(mess_io, 'well_lumped_input_file', lambda *a, **k: '')

    for name, mod in (('phydat', phydat), ('phydat.phycon', phycon),
                      ('mess_io', mess_io), ('mess_io.writer', writer_mod)):
        monkeypatch.setitem(sys.modules, name, mod)


_counter = itertools.count()


def _load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
          globkey: Any = _GLOBKEY_ATM, pres_unit: str = 'bar') -> Any:
    script = _emit(tmp_path, pres_unit)
    _install_stubs(monkeypatch, globkey)
    mod_name = f'globkey_driver_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(mod_name, script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, mod_name, mod)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Standard contract: the unit label is rewritten, the numbers are not
# ---------------------------------------------------------------------------
def test_globkey_rewrites_atm_to_the_payload_unit(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load(tmp_path, monkeypatch)
    block = mod._globkey_str(_OUT, None)
    assert 'PressureList[bar]' in block
    assert 'PressureList[atm]' not in block
    assert 'atm' not in block


def test_globkey_changes_nothing_but_the_unit(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Byte-for-byte equality with the mess_io block, unit label aside."""
    mod = _load(tmp_path, monkeypatch)
    block = mod._globkey_str(_OUT, None)
    assert block == _GLOBKEY_ATM.replace(
        'PressureList[atm]', 'PressureList[bar]')
    # The grid itself is untouched: same numbers, no conversion.
    numbers = re.search(r'PressureList\[[^\]]+\]([^\n]*)', block)
    assert numbers is not None
    assert [float(v) for v in numbers.group(1).split()] == _PRES


def test_globkey_follows_a_non_default_pres_unit(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rewritten label is ``PRES_UNIT``, not a second hardcoded 'bar'."""
    mod = _load(tmp_path, monkeypatch, pres_unit='torr')
    assert mod.PRES_UNIT == 'torr'
    assert 'PressureList[torr]' in mod._globkey_str(_OUT, None)


def test_globkey_rewrite_is_idempotent(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two pass-1/pass-2 calls produce the identical block."""
    mod = _load(tmp_path, monkeypatch)
    assert mod._globkey_str(_OUT, None) == mod._globkey_str(_OUT, None)


# ---------------------------------------------------------------------------
# Edge cases: the driver fails loudly rather than writing a wrong unit
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('bad', [
    _GLOBKEY_ATM.replace('PressureList[atm]', 'PressureList[torr]'),
    _GLOBKEY_ATM.replace('PressureList[atm]', 'PressureList[bar]'),
    _GLOBKEY_ATM.replace('PressureList[atm]', 'PressureList [atm]'),
    _GLOBKEY_ATM.replace('PressureList[atm]', 'PRESSURELIST[ATM]'),
    '',
    'TemperatureList[K] 500.0\n',
])
def test_missing_expected_atm_literal_raises(
        tmp_path, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    """Anything but the exact expected literal aborts the driver.

    The rewrite is a plain ``str.replace`` of ``PressureList[atm]``; if
    upstream mess_io ever stops emitting it, a silent no-op would ship a MESS
    input whose declared unit contradicts the grid.
    """
    mod = _load(tmp_path, monkeypatch, globkey=bad)
    with pytest.raises(RuntimeError) as info:
        mod._globkey_str(_OUT, None)
    message = str(info.value)
    assert 'PressureList[atm]' in message
    assert 'bar' in message


def test_guard_is_a_raise_not_an_assert(tmp_path) -> None:
    """``python -O`` strips ``assert``; the guard must survive it."""
    source = _emit(tmp_path).read_text()
    func = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == '_globkey_str')
    assert any(isinstance(n, ast.Raise) for n in ast.walk(func))
    assert not any(isinstance(n, ast.Assert) for n in ast.walk(func))


def test_guard_still_raises_under_python_O(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Behavioral counterpart: the compiled-with-optimization driver raises."""
    script = _emit(tmp_path)
    _install_stubs(monkeypatch, 'PressureList[torr] 1.0\n')
    code = compile(script.read_text(), str(script), 'exec', optimize=2)
    namespace: dict[str, Any] = {'__name__': 'globkey_optimized'}
    exec(code, namespace)
    with pytest.raises(RuntimeError):
        namespace['_globkey_str'](_OUT, None)


def test_globkey_forwards_the_payload_grid_and_outname(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The unit rewrite does not disturb the call it wraps."""
    seen: dict[str, Any] = {}

    def _spy(**kwargs):
        seen.update(kwargs)
        return _GLOBKEY_ATM

    mod = _load(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, 'global_rates_input_v1', _spy)
    mod._globkey_str(_OUT, 'WELLEXT')
    assert seen['pressures'] == _PRES
    assert seen['temperatures'] == _TEMP
    assert seen['well_extension'] == 'WELLEXT'
    assert seen['ktp_outname'] == _OUT
