"""CI-safe tests of the two MESS passes of the automech driver on a real PES.

``test_automech_driver_ci`` runs the emitted driver with mess_io stubbed; here
the real mess_io and, in the last test, the real MESS take part. The contract:
pass 1 runs with the WellExtension line of the input commented, so that wells
vanish from the rate tables; pass 2 gets that line back from mess_io, with a
WellExtensionCap for each vanished well, read at the lowest pressure of the
grid.

Fixture ``tests/unit/data/well_extension_caps/``: ``two_wells.inp`` is a
synthetic five-atom PES, WDEEP (-60 kcal/mol) and WSHAL (-35) joined by B1
(-8), WSHAL going to PROD+H (0) over B2 (+3), on 1000-1750 K and 0.01-100 bar.
WSHAL vanishes above 1250 K at 0.01 bar, above 1500 K at 1 bar and never at
100 bar, so the pressure the caps are read at changes the result.
``two_wells_pass1.out`` and ``two_wells_pass1.log`` are what MESS wrote in
pass 1 of the emitted driver (no ``.aux``: mess_io accepts an empty one).
Regenerate them with ``OMP_NUM_THREADS=1`` when ``two_wells.inp`` changes.

Skip-vs-fail policy. Every test needs mess_io (``import_or_skip``: a skip,
a failure under ``KIMECO_REQUIRE_EXTRAS=automech``). The first group patches
``subprocess.run`` and feeds the stored pass-1 files, so it needs no binary.
``test_real_two_pass_writes_caps_mess_accepts_pass2`` runs the driver as a
script with the real MESS: a skip without ``mess`` on PATH, a failure under
``KIMECO_REQUIRE_MESS=1`` (the ``test-mess-binary`` CI job). The git hook runs
it too, because ``conda run`` puts the env's ``mess`` on PATH.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from kimeco.enums import FreqMode
from kimeco.readers.mess_input import MessInputReader
from kimeco.readers.mess_output import MessOutputReader
from kimeco.writers.automech_kin import AutomechKinWriter
from tests.unit.test_installation_extras_ci import import_or_skip
from tests.unit.test_installation_mess_ci import locate_mess, mess_required
from tests.unit.test_mess_multi_pes_read_ci import SpyLog, assert_clean

_FIXTURE = Path(__file__).parent / 'data' / 'well_extension_caps'
_KEY_LINE = 'WellExtension 0.001\n'
_TEMPS = [1000.0, 1250.0, 1500.0, 1750.0]
_PRES = [0.01, 1.0, 100.0]
_BASE = 'G0000E0000P00'
_INP = f'{_BASE}.inp'
_OUT = f'{_BASE}.out'
_LOG = f'{_BASE}.log'
_PASS1 = f'_{_BASE}.out'

#: The cap of WSHAL read from the stored pass 1 at 0.01 bar. At 1 bar it would
#: be 19.10, and at 100 bar there would be none.
_CAP_LOWEST_P = '14.20'

_ACTIVE = re.compile(r'^\s*WellExtension\b(?!Cap).*$', re.M)
_CAP = re.compile(r'^\s*WellExtensionCap\[kcal/mol\]\s+(\S+)$')
_TABLE = re.compile(r'Temperature = (\S+) K\s+Pressure = (\S+) bar\n\n'
                    r'From\\To.*\n((?:.+\n)+)')


def _emit(folder: Path, key_line: str | None = _KEY_LINE) -> Path:
    """Read the fixture with ``key_line`` as its WellExtension line (no line
    when None) and emit the driver of its PES into ``folder``."""
    text = (_FIXTURE / 'two_wells.inp').read_text()
    assert text.count(_KEY_LINE) == 1
    (folder / 'f0.inp').write_text(text.replace(_KEY_LINE, key_line or ''))
    settings = {
        'init_loc': str(folder), 'mess_inputs': ['f0.inp'], 'n_exp': 1,
        'score_sp': [], 'freq_mode': FreqMode.BATCH, 'rc_temp': list(_TEMPS),
        'rc_pres': list(_PRES), 'pres_unit': 'bar',
        'force_new_molecules': False}
    reader = MessInputReader(
        settings=settings, mechanism_species=['WDEEP', 'WSHAL', 'PROD', 'H'],
        klog=SpyLog(),  # type: ignore[arg-type]
        postprocess=False)
    sop, _templates = reader.read()
    assert_clean(reader)
    AutomechKinWriter(sop=sop, pes_id=0).write(loc=str(folder),
                                               filename=f'{_BASE}.py')
    return folder / f'{_BASE}.py'


def _active_lines(text: str) -> list[str]:
    """WellExtension lines MESS would read (caps and comments excluded)."""
    return [match.group(0).strip() for match in _ACTIVE.finditer(text)]


def _cap_after(text: str, well: str) -> str | None:
    """Value of the WellExtensionCap on the line after ``Well <well>``."""
    lines = text.splitlines()
    index = next(k for k, line in enumerate(lines)
                 if line.split() == ['Well', well])
    match = _CAP.match(lines[index + 1])
    return match.group(1) if match else None


def _well_rows(text: str, well: str) -> dict[tuple[float, float], list[str]]:
    """Row of ``well`` in each Species-Species table, by (T, P)."""
    rows: dict[tuple[float, float], list[str]] = {}
    for match in _TABLE.finditer(text):
        fields = {line.split()[0]: line.split()[1:]
                  for line in match.group(3).splitlines()}
        rows[float(match.group(1)), float(match.group(2))] = fields[well]
    return rows


# ---------------------------------------------------------------------------
# Real mess_io, stored pass 1, no MESS binary
# ---------------------------------------------------------------------------
class _StoredMess:
    """``subprocess.run`` double: the first run drops the stored pass-1 output
    and log, the second a canned complete output. Keeps each input it got."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.inputs: list[str] = []

    def __call__(self, cmd, check=False, **kwargs):
        self.inputs.append((self.cwd / cmd[1]).read_text())
        if len(self.inputs) == 1:
            shutil.copy(_FIXTURE / 'two_wells_pass1.out', self.cwd / _OUT)
            shutil.copy(_FIXTURE / 'two_wells_pass1.log', self.cwd / _LOG)
        else:
            (self.cwd / _OUT).write_text(
                'Temperature-Pressure Rate Tables:\n\nPASS2\n')
        return types.SimpleNamespace(returncode=0)


def _load(script: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Import the emitted script with the real mess_io (``main`` not run)."""
    import_or_skip('automech', 'mess_io.writer')
    spec = importlib.util.spec_from_file_location(
        f'two_pass_driver_{script.parent.name}', script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


def _both_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                 key_line: str | None = _KEY_LINE) -> list[str]:
    """Run the driver on the stored pass 1; returns the two inputs."""
    mod = _load(_emit(tmp_path, key_line), monkeypatch)
    fake = _StoredMess(tmp_path)
    monkeypatch.setattr(mod.subprocess, 'run', fake)
    monkeypatch.chdir(tmp_path)
    assert mod.main() == 0
    assert len(fake.inputs) == 2
    return fake.inputs


def test_real_pass1_text_has_no_active_line(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real mess_io text is what gets commented: the line stays, inert."""
    pass1, _pass2 = _both_passes(tmp_path, monkeypatch)
    assert _active_lines(pass1) == []
    assert re.search(r'^!WellExtension\s+0\.0010$', pass1, re.M)


@pytest.mark.parametrize('key_line, value', [
    ('WellExtension 0.001\n', '0.0010'),
    ('WellExtension 0.0\n', '0.0000'),
    ('WellExtension\n', '0.0000')], ids=['0.001', '0.0', 'bare'])
def test_real_pass2_one_active_line_with_input_value(
        tmp_path, monkeypatch: pytest.MonkeyPatch, key_line, value) -> None:
    """Pass 2 has one active line, the input's value, and one
    ExtensionCorrection, the value of mess_io. A second, bare line would set
    the value to 0: MESS keeps the last line."""
    _pass1, pass2 = _both_passes(tmp_path, monkeypatch, key_line)
    assert [line.split() for line in _active_lines(pass2)] == [
        ['WellExtension', value]]
    assert '!WellExtension' not in pass2
    assert re.findall(r'^ExtensionCorrection.*$', pass2, re.M) == [
        'ExtensionCorrection    0.6']


def test_real_cap_follows_its_well_line(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WSHAL vanishes, so its cap is written right after its ``Well`` line,
    with the value read at the lowest pressure; WDEEP never vanishes."""
    _pass1, pass2 = _both_passes(tmp_path, monkeypatch)
    assert _cap_after(pass2, 'WSHAL') == _CAP_LOWEST_P
    assert _cap_after(pass2, 'WDEEP') is None
    assert pass2.count('WellExtensionCap') == 1


def test_real_lump_pressure_matches_parsed_key(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The lump pressure is the lowest key mess_io parses from the output: a
    mismatch makes every cap fall back to the lowest temperature."""
    mod = _load(_emit(tmp_path), monkeypatch)
    rates = import_or_skip('automech', 'mess_io.reader.rates')
    numpy = import_or_skip('base', 'numpy')
    out_str = (_FIXTURE / 'two_wells_pass1.out').read_text()
    keys = [key for key in rates.ktp_dct(out_str, 'WSHAL', 'WDEEP')
            if key != 'high']
    assert len(keys) == len(_PRES)
    assert numpy.isclose(mod._lump_pressure_atm(), min(keys))


def test_real_no_key_gets_bare_line(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PES without the key: nothing in pass 1, in pass 2 the bare line of
    mess_io, and its caps all the same."""
    pass1, pass2 = _both_passes(tmp_path, monkeypatch, None)
    assert 'WellExtension' not in pass1
    assert _active_lines(pass2) == ['WellExtension']
    assert _cap_after(pass2, 'WSHAL') == _CAP_LOWEST_P


def test_real_comment_marker_touches_the_word(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mess_io gives the value back only from the exact ``!WellExtension``:
    the driver writes that text, and on ``! WellExtension`` (the control)
    mess_io leaves the value commented and adds a bare line, of value 0."""
    mod = _load(_emit(tmp_path), monkeypatch)
    pass1, _pass2 = _both_passes(tmp_path, monkeypatch)
    assert '! WellExtension' not in pass1
    out_str = (_FIXTURE / 'two_wells_pass1.out').read_text()
    log_str = (_FIXTURE / 'two_wells_pass1.log').read_text()
    control = mod.well_lumped_input_file(
        pass1.replace('!WellExtension', '! WellExtension'), out_str, '',
        log_str, mod._lump_pressure_atm(), mod.LUMP_TEMP)
    assert _active_lines(control) == ['WellExtension']


# ---------------------------------------------------------------------------
# Real MESS (requested by the user): MESS accepts pass 2 with its caps
# ---------------------------------------------------------------------------
def test_real_two_pass_writes_caps_mess_accepts_pass2(tmp_path) -> None:
    """The emitted driver, run as a script with the real MESS: WSHAL vanishes
    in pass 1, pass 2 holds the input's value and the cap of WSHAL read at
    0.01 bar, and with them MESS completes and gives WSHAL a rate everywhere."""
    import_or_skip('automech', 'mess_io.writer')
    reader = import_or_skip('automech', 'mess_io.reader')
    phycon = import_or_skip('automech', 'phydat.phycon')
    if locate_mess() is None:
        message = 'mess is not on PATH'
        if mess_required():
            pytest.fail(message)
        pytest.skip(message)

    script = _emit(tmp_path)
    done = subprocess.run(
        [sys.executable, script.name], cwd=tmp_path, capture_output=True,
        text=True, timeout=300, env=dict(os.environ, OMP_NUM_THREADS='1'))

    assert done.returncode == 0, done.stdout[-2000:]
    assert done.stderr == ''
    assert 'No k(T) values found' not in done.stdout
    assert 'KiMecO automech driver' not in done.stdout
    assert not (tmp_path / f'{_OUT}.failed').exists()

    # Pass 1: WSHAL is gone at 1500 K, 0.01 bar.
    pass1_path = tmp_path / _PASS1
    assert pass1_path.is_file()
    assert MessOutputReader.well_merging(str(pass1_path))
    rows = _well_rows(pass1_path.read_text(), 'WSHAL')
    assert set(rows[1500.0, 0.01]) == {'***'}

    # Pass 2 input: the input's value, once, and the cap of WSHAL only.
    pass2 = (tmp_path / _INP).read_text()
    assert [line.split() for line in _active_lines(pass2)] == [
        ['WellExtension', '0.0010']]
    assert len(re.findall(r'^ExtensionCorrection', pass2, re.M)) == 1
    assert _cap_after(pass2, 'WDEEP') is None
    cap = _cap_after(pass2, 'WSHAL')
    assert cap is not None

    # The cap is the thermal energy at the last T where WSHAL has a k at the
    # lowest pressure, not the fallback at the lowest T.
    last_temp = max(temp for (temp, pres), row in rows.items()
                    if pres == 0.01 and set(row) != {'***'})
    log_str = (tmp_path / _LOG).read_text()
    assert float(cap) == pytest.approx(
        reader.well_thermal_energy(log_str, 'WSHAL', last_temp)
        * phycon.EH2KCAL, abs=0.005)
    assert float(cap) > (reader.well_thermal_energy(log_str, 'WSHAL', _TEMPS[0])
                         * phycon.EH2KCAL)

    # Pass 2 output: complete, and WSHAL has rates at every T and P.
    final = (tmp_path / _OUT).read_text()
    assert 'Temperature-Pressure Rate Tables:' in final
    assert not MessOutputReader.well_merging(str(tmp_path / _OUT))
    rows = _well_rows(final, 'WSHAL')
    assert set(rows) == {(temp, pres) for temp in _TEMPS for pres in _PRES}
    assert all(float(value) > 0.0 for row in rows.values() for value in row)
