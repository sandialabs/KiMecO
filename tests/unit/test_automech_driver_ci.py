"""CI-safe tests for the emitted automech MESS driver (runtime half).

The driver script produced by ``AutomechKinWriter`` is loaded as a module with
``mess_io``/``phydat`` replaced by one shared set of recording stubs (installed
in ``sys.modules`` first, so the behaviour is identical with or without a real
automech install), and with ``subprocess.run`` patched: no MESS binary is
needed. Three families of guarantees:

* Merged-well gate, prompt mode and pass-1 guard (``main``). The driver runs
  MESS (pass 1); if ``<name>P<slot>.out`` is absent it prints a message and
  returns cleanly, so ``q_sys._pickup_kin``'s ``len(p_outs) != n_pes`` gate
  leaves the job unpicked for retry; otherwise it ``os.replace``s the output
  to the leading-underscore pass-1 copy and runs pass 2
  (``well_lumped_input_file`` + WellExtension caps) when the payload carries
  ``prompt_reactions`` (prompt mode: always, keeping every output) or when
  ``MessOutputReader.well_merging`` reports missing T/P coefficients, else it
  moves the pass-1 copy back. Both the emitted source structure (AST) and
  the runtime behaviour are checked.
* ``_globkey_str`` unit relabel. ``mess_io.writer.global_rates_input_v1``
  hardcodes ``PressureList[atm]`` while the grid is in bar (the grid
  ``MessOutputReader`` indexes against), so the driver relabels the block to
  ``PressureList[<PRES_UNIT>]`` instead of converting the numbers, and raises
  (never asserts, so it survives ``python -O``) when the literal is absent.
* Helpers fed by the parsed MESS input: ``_hind_rot_str`` forwards ``geo=``
  (angstrom -> bohr) only for rotors carrying a geometry; the rotd branch of
  ``_barrier_str`` passes its rotors to ``molecule(hind_rot=...)`` (phasespace
  does not); ``_globkey_str`` forwards the header keys only when set.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import re
import string
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from kimeco.writers import automech_kin
from kimeco.writers.automech_kin import AutomechKinWriter

_NAME = 'G0000E0001'
_SLOT = 3
_BASE = f'{_NAME}P{_SLOT:02d}'
_FILENAME = f'{_BASE}.py'
_OUT = f'{_BASE}.out'
_INP = f'{_BASE}.inp'
_AUX = f'{_BASE}.aux'
_LOG = f'{_BASE}.log'
_PASS1 = f'_{_BASE}.out'

#: phydat.phycon conversion factors (the ones mess_io's reader applies).
_BOHR2ANG = 0.52917721092
_BAR2ATM = 0.9869232667160128
_TORR2ATM = 0.0013157894736842105

_MERGING_OUT = """Species-Species Rate Tables:

Temperature = 550 K    Pressure = 1 bar

From\\To            W1        W2
W1                5.42        ***
W2            3.34e+03   2.01e+05

______________________________________________________________________
"""

_HEALTHY_OUT = """Species-Species Rate Tables:

Temperature = 550 K    Pressure = 1 bar

From\\To            W1        W2
W1                5.42    0.00363
W2            3.34e+03   2.01e+05

______________________________________________________________________
"""

#: Shaped like the real ``mess_io.writer.global_rates_input_v1`` output for
#: the default minimal grid: the driver rewrites the hardcoded ``[atm]``
#: label to the payload unit, so the stub must contain that literal or the
#: driver refuses to write the input.
_GLOBKEY_ATM = (
    '!===================================================\n'
    '!  GLOBAL KEYWORDS\n'
    '!===================================================\n'
    'TemperatureList[K]                     500.0  1000.0\n'
    'PressureList[atm]                      1.0  10.0\n'
    '!\n'
    'RateOutput                             ' + _OUT + '\n'
)

#: Same layout on the four-point grid used by the unit-relabel tests.
_PRES4 = [0.01, 0.1, 1.0, 10.0]
_GLOBKEY4_ATM = (
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


# ---------------------------------------------------------------------------
# Shared recording stubs for phydat / mess_io
# ---------------------------------------------------------------------------
class _Recorder:
    """Records every stubbed mess_io call as ``(args, kwargs)`` by name.

    Every stub returns a ``str``: the emitted driver does string surgery on
    the global-keyword block, so a non-string return would blow up in the
    driver rather than in the code under test. Generic writer functions
    return ``'<name>'`` so callers can see which builder produced a value.
    """

    def __init__(self) -> None:
        self.calls: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {}

    def fn(self, name: str, ret: str | None = None):
        def _stub(*args, **kwargs):
            self.calls.setdefault(name, []).append((args, dict(kwargs)))
            return f'<{name}>' if ret is None else ret
        return _stub

    def count(self, name: str) -> int:
        return len(self.calls.get(name, []))

    def kwargs(self, name: str) -> list[dict[str, Any]]:
        return [kw for _args, kw in self.calls.get(name, [])]

    def last(self, name: str) -> dict[str, Any]:
        return self.calls[name][-1][1]


def _install_stubs(monkeypatch: pytest.MonkeyPatch,
                   globkey: Any = _GLOBKEY_ATM) -> _Recorder:
    """Stub phydat/mess_io; ``global_rates_input_v1`` returns ``globkey``."""
    rec = _Recorder()

    phycon = types.ModuleType('phydat.phycon')
    setattr(phycon, 'BOHR2ANG', _BOHR2ANG)
    setattr(phycon, 'EH2WAVEN', 219474.6313702)
    setattr(phycon, 'BAR2ATM', _BAR2ATM)
    setattr(phycon, 'TORR2ATM', _TORR2ATM)
    phydat = types.ModuleType('phydat')
    setattr(phydat, 'phycon', phycon)

    writer_mod = types.ModuleType('mess_io.writer')

    def _writer_getattr(name: str):
        if name.startswith('__'):
            raise AttributeError(name)
        return rec.fn(name)

    # PEP 562 fallback: any mess_io.writer name resolves to a recording stub.
    setattr(writer_mod, '__getattr__', _writer_getattr)
    setattr(writer_mod, 'messrates_inp_str',
            rec.fn('messrates_inp_str', ret='BASE_INP\n'))
    setattr(writer_mod, 'global_rates_input_v1',
            rec.fn('global_rates_input_v1', ret=globkey))

    mess_io = types.ModuleType('mess_io')
    setattr(mess_io, 'writer', writer_mod)
    setattr(mess_io, 'well_lumped_input_file',
            rec.fn('well_lumped_input_file', ret='EXTENDED_INP\n'))

    for name, mod in (('phydat', phydat), ('phydat.phycon', phycon),
                      ('mess_io', mess_io), ('mess_io.writer', writer_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    return rec


_counter = itertools.count()


def _load_driver(script: Path, monkeypatch: pytest.MonkeyPatch,
                 globkey: Any = _GLOBKEY_ATM) -> tuple[Any, _Recorder]:
    """Import the emitted script as a module (its ``main`` is not run)."""
    rec = _install_stubs(monkeypatch, globkey)
    mod_name = f'emitted_driver_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(mod_name, script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, mod_name, mod)
    spec.loader.exec_module(mod)
    return mod, rec


def _case_dir(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir()
    return path


# ---------------------------------------------------------------------------
# Emission helpers
# ---------------------------------------------------------------------------
class _MinimalSOP:
    """Smallest SOP surface the serializer reads (no species needed here)."""

    def __init__(self, pres: list[float], pres_unit: str | None) -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = [500.0, 1000.0]
        self.pres = list(pres)
        if pres_unit is not None:
            self.pres_unit = pres_unit

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _emit(tmp_path: Path, pres_unit: str | None = None,
          pres: list[float] | None = None, prompt: bool = False) -> Path:
    sop = _MinimalSOP(pres if pres is not None else [1.0, 10.0], pres_unit)
    # Prompt mode reaches the writer through its settings only.
    settings = {'prompt_reactions': True} if prompt else None
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0,
                               settings=settings)
    writer.write(loc=str(tmp_path), filename=_FILENAME)
    return tmp_path / _FILENAME


class _FakeMess:
    """``subprocess.run`` double writing a canned output per invocation."""

    def __init__(self, cwd: Path, outputs: list[str | None]) -> None:
        self.cwd = cwd
        self.outputs = list(outputs)
        self.calls: list[list[str]] = []

    def __call__(self, cmd, check=False, **kwargs):
        self.calls.append(list(cmd))
        content = self.outputs.pop(0) if self.outputs else None
        if content is not None:
            (self.cwd / _OUT).write_text(content)
        return types.SimpleNamespace(returncode=0)


def _run_driver(tmp_path: Path,
                monkeypatch: pytest.MonkeyPatch,
                outputs: list[str | None],
                pres_unit: str | None = None,
                prompt: bool = False
                ) -> tuple[Any, _Recorder, _FakeMess]:
    script = _emit(tmp_path, pres_unit=pres_unit, prompt=prompt)
    mod, rec = _load_driver(script, monkeypatch)
    fake = _FakeMess(tmp_path, outputs)
    monkeypatch.setattr(mod.subprocess, 'run', fake)
    monkeypatch.chdir(tmp_path)
    assert mod.main() is None
    return mod, rec, fake


# ===========================================================================
# Merged-well gate and pass-1 guard
# ===========================================================================
def _main_def(script_text: str) -> ast.FunctionDef:
    for node in ast.parse(script_text).body:
        if isinstance(node, ast.FunctionDef) and node.name == 'main':
            return node
    raise AssertionError('emitted driver has no main()')


def _called_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(func.attr)
    return names


def _merging_if(main: ast.FunctionDef) -> ast.If:
    for node in ast.walk(main):
        if isinstance(node, ast.If) and 'well_merging' in _called_names(
                node.test):
            return node
    raise AssertionError('no well_merging branch in main()')


def test_emitted_main_structure(tmp_path) -> None:
    """AST of ``main``: one ``not os.path.isfile(out_name)`` guard returns
    (with a message) before the merging branch; the branch test is
    ``prompt_mode or MessOutputReader.well_merging(...)``, with
    ``prompt_mode`` read from the payload key ``prompt_reactions`` first so
    that the merged-well check is skipped in prompt mode, and the branch
    has both arms; pass 2
    (``well_lumped_input_file`` + one ``_run_mess``) lives only in the merging
    arm, the other arm only renames back; MESS runs twice in source, the
    second call nested deeper; ``os.replace`` both ways, never shutil. The
    template keeps exactly its six str.format placeholders and no other
    brace."""
    script = _emit(tmp_path).read_text()
    main = _main_def(script)

    guards = [
        node for node in main.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.UnaryOp)
        and isinstance(node.test.op, ast.Not)
        and 'isfile' in _called_names(node.test)
    ]
    assert len(guards) == 1
    guard = guards[0]
    assert any(isinstance(s, ast.Return) and s.value is None
               for s in guard.body)
    assert 'print' in _called_names(guard)
    # The guard runs before the pass-1 rename and before the merging branch.
    branch = _merging_if(main)
    assert main.body.index(guard) < main.body.index(branch)

    # Branch test: `prompt_mode or MessOutputReader.well_merging(...)`, the
    # prompt flag first (short-circuit), the merged-well call last.
    assert isinstance(branch.test, ast.BoolOp)
    assert isinstance(branch.test.op, ast.Or)
    assert len(branch.test.values) == 2
    flag, merging = branch.test.values
    assert isinstance(flag, ast.Name) and flag.id == 'prompt_mode'
    assert isinstance(merging, ast.Call)
    func = merging.func
    assert isinstance(func, ast.Attribute) and func.attr == 'well_merging'
    assert isinstance(func.value, ast.Name)
    assert func.value.id == 'MessOutputReader'
    # prompt_mode is assigned once, before the branch, from
    # PES_PAYLOAD.get("prompt_reactions").
    flag_sets = [
        node for node in main.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'prompt_mode'
                for t in node.targets)
    ]
    assert len(flag_sets) == 1
    assert main.body.index(flag_sets[0]) < main.body.index(branch)
    payload_gets = [
        sub for sub in ast.walk(flag_sets[0].value)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute) and sub.func.attr == 'get'
        and isinstance(sub.func.value, ast.Name)
        and sub.func.value.id == 'PES_PAYLOAD'
    ]
    assert len(payload_gets) == 1
    assert [ast.literal_eval(arg) for arg in payload_gets[0].args] == [
        'prompt_reactions']
    # Both arms exist: pass 2 on merging, plain restore otherwise.
    assert branch.body and branch.orelse

    body_calls = [c for stmt in branch.body for c in _called_names(stmt)]
    else_calls = [c for stmt in branch.orelse for c in _called_names(stmt)]
    assert 'well_lumped_input_file' in body_calls
    assert body_calls.count('_run_mess') == 1
    # The non-merging arm only renames the pass-1 copy back.
    assert 'well_lumped_input_file' not in else_calls
    assert '_run_mess' not in else_calls
    assert 'replace' in else_calls
    assert _called_names(main).count('_run_mess') == 2

    # Text-level two-pass structure: the pass-1 output moves to a
    # leading-underscore intermediate; pass 2 sits one level deeper.
    assert 'well_lumped_input_file(' in script
    assert 'pass1_copy = "_" + base' in script
    assert 'os.replace(out_name, pass1_copy)' in script
    assert 'os.replace(pass1_copy, out_name)' in script
    assert 'shutil' not in script
    run_lines = [ln for ln in script.splitlines()
                 if ln.strip() == '_run_mess(inp_name)']
    assert len(run_lines) == 2
    indent = [len(ln) - len(ln.lstrip()) for ln in run_lines]
    assert indent[1] > indent[0]

    # Template integrity: exactly six placeholders, str.format-safe body.
    tpl = automech_kin.automech_kin_tpl
    fields = {name for _, name, _, _ in string.Formatter().parse(tpl)
              if name is not None}
    assert fields == {'payload', 'name', 'slot', 'pres_unit',
                      'lump_pressure', 'lump_temp'}
    body = tpl
    for token in ('{payload}', '{name}', '{slot}', '{pres_unit}',
                  '{lump_pressure}', '{lump_temp}'):
        body = body.replace(token, '')
    assert '{' not in body and '}' not in body


def test_merging_output_triggers_second_pass(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass 2 gets the base input, pass-1 output, aux and log texts and the
    lump pressure in atm; the input is rewritten with the capped version;
    the pass-1 result is kept at ``_<base>.out`` and pass 2 at the final
    name. Only the .out is renamed: .aux/.log are read in place."""
    (tmp_path / _AUX).write_text('AUX-DATA')
    (tmp_path / _LOG).write_text('LOG-DATA')

    mod, rec, fake = _run_driver(
        tmp_path, monkeypatch, [_MERGING_OUT, 'PASS2-OUTPUT'])

    assert fake.calls == [['mess', _INP], ['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 1
    args, _kwargs = rec.calls['well_lumped_input_file'][0]
    assert args[0] == 'BASE_INP\n'          # base input string
    assert args[1] == _MERGING_OUT          # pass-1 output text
    assert args[2] == 'AUX-DATA'            # aux text
    assert args[3] == 'LOG-DATA'            # log text
    assert args[4] == pytest.approx(mod.LUMP_PRESSURE * _BAR2ATM)
    assert args[5] == mod.LUMP_TEMP

    # The input was rewritten with the WellExtension-capped version.
    assert (tmp_path / _INP).read_text() == 'EXTENDED_INP\n'
    # Pass-1 result preserved, pass-2 result at the final name.
    assert (tmp_path / _PASS1).read_text() == _MERGING_OUT
    assert (tmp_path / _OUT).read_text() == 'PASS2-OUTPUT'
    # .aux/.log untouched and not renamed.
    assert (tmp_path / _AUX).read_text() == 'AUX-DATA'
    assert (tmp_path / _LOG).read_text() == 'LOG-DATA'
    assert not (tmp_path / f'_{_BASE}.aux').exists()
    assert not (tmp_path / f'_{_BASE}.log').exists()


def test_merging_branch_tolerates_absent_aux_and_log(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing .aux/.log degrade to empty strings, not an exception."""
    _mod, rec, _fake = _run_driver(
        tmp_path, monkeypatch, [_MERGING_OUT, 'PASS2-OUTPUT'])

    args, _kwargs = rec.calls['well_lumped_input_file'][0]
    assert args[2] == ''
    assert args[3] == ''


def test_lump_pressure_reaches_mess_io_in_atm(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mess_io compares the lump pressure with output pressures in atm: the
    emitted literal stays in the grid unit, only the call converts."""
    failures: list[str] = []
    for pres_unit, to_atm in (('bar', _BAR2ATM), ('torr', _TORR2ATM),
                              ('atm', 1.0)):
        with monkeypatch.context() as mp:
            mod, rec, _fake = _run_driver(
                _case_dir(tmp_path, pres_unit), mp,
                [_MERGING_OUT, 'PASS2-OUTPUT'], pres_unit=pres_unit)
            args, _kwargs = rec.calls['well_lumped_input_file'][0]
            if mod.LUMP_PRESSURE != 10.0:
                failures.append(f'{pres_unit}: LUMP_PRESSURE {mod.LUMP_PRESSURE}')
            if args[4] != pytest.approx(10.0 * to_atm):
                failures.append(f'{pres_unit}: lump pressure {args[4]} '
                                f'!= {10.0 * to_atm} atm')
    assert not failures, '\n'.join(failures)


def test_lump_pressure_matches_mess_io_output_pressure(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The lump pressure must equal (numpy.isclose) the key mess_io gives
    the max grid pressure when it parses the MESS output; a mismatch makes
    well_energies fall back to the lowest temperature of the run."""
    rates = pytest.importorskip('mess_io.reader.rates')
    numpy = pytest.importorskip('numpy')
    failures: list[str] = []
    for pres_unit in ('bar', 'torr', 'atm'):
        parsed = rates._convert_pressure(10.0, pres_unit)
        with monkeypatch.context() as mp:
            _mod, rec, _fake = _run_driver(
                _case_dir(tmp_path, pres_unit), mp,
                [_MERGING_OUT, 'PASS2-OUTPUT'], pres_unit=pres_unit)
            args, _kwargs = rec.calls['well_lumped_input_file'][0]
            if not numpy.isclose(args[4], parsed):
                failures.append(f'{pres_unit}: {args[4]} vs mess_io {parsed}')
    assert not failures, '\n'.join(failures)


def test_healthy_output_skips_the_second_pass(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One MESS run; the pass-1 result moves back under the real name; input,
    aux and log untouched. Pass 1 asks for no well extension, its globkey
    block reaches messrates_inp_str relabelled to the payload unit (no
    ``atm`` left, nothing else changed) and carries the unconverted grid."""
    (tmp_path / _AUX).write_text('AUX-DATA')
    (tmp_path / _LOG).write_text('LOG-DATA')

    mod, rec, fake = _run_driver(tmp_path, monkeypatch, [_HEALTHY_OUT])

    assert fake.calls == [['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 0
    # Pass-1 result is the final result, moved back under the real name.
    assert (tmp_path / _OUT).read_text() == _HEALTHY_OUT
    assert not (tmp_path / _PASS1).exists()
    # The input is left as written by pass 1.
    assert (tmp_path / _INP).read_text() == 'BASE_INP\n'
    assert (tmp_path / _AUX).read_text() == 'AUX-DATA'
    assert (tmp_path / _LOG).read_text() == 'LOG-DATA'

    kwargs = rec.last('global_rates_input_v1')
    assert kwargs['well_extension'] is None
    assert kwargs['ktp_outname'] == _OUT
    assert kwargs['pressures'] == mod.PES_PAYLOAD['grid_pres']
    assert kwargs['pressures'] == [1.0, 10.0]
    assert mod.LUMP_PRESSURE == 10.0

    globkey = rec.calls['messrates_inp_str'][0][0][0]
    assert 'PressureList[' + mod.PRES_UNIT + ']' in globkey
    assert 'PressureList[atm]' not in globkey
    assert 'atm' not in globkey
    assert globkey == _GLOBKEY_ATM.replace(
        'PressureList[atm]', 'PressureList[' + mod.PRES_UNIT + ']')


def test_missing_pass1_output_exits_cleanly(
        tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """No output after pass 1 -> message, return, no rename, no pass 2, the
    gate is never consulted, aux/log untouched. Neither the final output nor
    the pass-1 copy exists: the job stays unpicked (q_sys._pickup_kin counts
    len(p_outs) != n_pes) and is retried."""
    (tmp_path / _AUX).write_text('AUX-DATA')
    (tmp_path / _LOG).write_text('LOG-DATA')
    script = _emit(tmp_path)
    mod, rec = _load_driver(script, monkeypatch)

    seen: list[str] = []

    def _spy(filename: str) -> bool:
        seen.append(filename)
        return False

    monkeypatch.setattr(mod.MessOutputReader, 'well_merging',
                        staticmethod(_spy))
    fake = _FakeMess(tmp_path, [None])
    monkeypatch.setattr(mod.subprocess, 'run', fake)
    monkeypatch.chdir(tmp_path)

    assert mod.main() is None
    out = capsys.readouterr().out
    assert f'MESS pass 1 produced no output {_OUT}, aborting.' in out
    assert fake.calls == [['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 0
    assert seen == []
    assert not (tmp_path / _OUT).exists()
    assert not (tmp_path / _PASS1).exists()
    assert (tmp_path / _AUX).read_text() == 'AUX-DATA'
    assert (tmp_path / _LOG).read_text() == 'LOG-DATA'


# ===========================================================================
# Prompt mode: pass 2 always runs, every output is kept
# ===========================================================================
_PED = f'{_BASE}_ped.out'
_KE = f'{_BASE}_ke.out'


class _FakeMessSides(_FakeMess):
    """``_FakeMess`` that also writes the side outputs of a MESS run (.log,
    .aux, _ped.out, _ke.out), tagged with the pass number, whenever the run
    produces its .out (a failed run writes nothing)."""

    def __call__(self, cmd, check=False, **kwargs):
        writes = bool(self.outputs) and self.outputs[0] is not None
        result = super().__call__(cmd, check=check, **kwargs)
        if writes:
            tag = f'PASS{len(self.calls)}'
            for name, kind in ((_LOG, 'LOG'), (_AUX, 'AUX'), (_PED, 'PED'),
                               (_KE, 'KE')):
                (self.cwd / name).write_text(f'{tag}-{kind}')
        return result


def _run_prompt_driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                       outputs: list[str | None],
                       payload: dict[str, Any] | None = None
                       ) -> tuple[Any, _Recorder, _FakeMessSides, list[str]]:
    """Emit the prompt-mode driver, spy ``well_merging`` (always False),
    run ``main`` with ``_FakeMessSides``; ``payload`` items are set on
    ``PES_PAYLOAD`` before the run."""
    script = _emit(tmp_path, prompt=True)
    mod, rec = _load_driver(script, monkeypatch)
    for key, value in (payload or {}).items():
        monkeypatch.setitem(mod.PES_PAYLOAD, key, value)
    seen: list[str] = []

    def _spy(filename: str) -> bool:
        seen.append(filename)
        return False

    monkeypatch.setattr(mod.MessOutputReader, 'well_merging',
                        staticmethod(_spy))
    fake = _FakeMessSides(tmp_path, outputs)
    monkeypatch.setattr(mod.subprocess, 'run', fake)
    monkeypatch.chdir(tmp_path)
    assert mod.main() is None
    return mod, rec, fake, seen


def test_prompt_mode_forces_second_pass_on_healthy_output(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prompt mode, healthy pass-1 output and well_merging reporting no
    merged well: pass 2 still runs (two MESS calls), fed with the base
    input, the pass-1 output, aux and log of pass 1, the lump pressure in
    atm and the lump temperature; the input becomes the capped one; the
    pass-1 copy keeps pass 1, the final output is pass 2."""
    mod, rec, fake, _seen = _run_prompt_driver(
        tmp_path, monkeypatch, [_HEALTHY_OUT, 'PASS2-OUTPUT'])

    assert mod.PES_PAYLOAD['prompt_reactions'] is True
    assert fake.calls == [['mess', _INP], ['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 1
    args, _kwargs = rec.calls['well_lumped_input_file'][0]
    assert args[0] == 'BASE_INP\n'
    assert args[1] == _HEALTHY_OUT
    assert args[2] == 'PASS1-AUX'
    assert args[3] == 'PASS1-LOG'
    assert args[4] == pytest.approx(mod.LUMP_PRESSURE * _BAR2ATM)
    assert args[5] == mod.LUMP_TEMP
    assert (tmp_path / _INP).read_text() == 'EXTENDED_INP\n'
    assert (tmp_path / _PASS1).read_text() == _HEALTHY_OUT
    assert (tmp_path / _OUT).read_text() == 'PASS2-OUTPUT'


def test_prompt_mode_keeps_every_output(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a prompt-mode run the directory holds exactly the driver, the
    pass-2 input, output, .log, .aux, _ped.out and _ke.out, and the pass-1
    copy of the output: the driver deletes nothing."""
    _run_prompt_driver(tmp_path, monkeypatch,
                       [_HEALTHY_OUT, 'PASS2-OUTPUT'])

    files = {p.name for p in tmp_path.iterdir() if p.is_file()}
    assert files == {_FILENAME, _INP, _OUT, _LOG, _AUX, _PED, _KE, _PASS1}
    for name in (_LOG, _AUX, _PED, _KE):
        assert (tmp_path / name).read_text().startswith('PASS2-'), name
    assert (tmp_path / _OUT).read_text() == 'PASS2-OUTPUT'
    assert (tmp_path / _PASS1).read_text() == _HEALTHY_OUT


def test_prompt_mode_merging_output_runs_pass2_once(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prompt mode with merged wells: pass 2 runs once, not twice."""
    _mod, rec, fake = _run_driver(tmp_path, monkeypatch,
                                  [_MERGING_OUT, 'PASS2-OUTPUT'],
                                  prompt=True)
    assert fake.calls == [['mess', _INP], ['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 1
    assert (tmp_path / _PASS1).read_text() == _MERGING_OUT
    assert (tmp_path / _OUT).read_text() == 'PASS2-OUTPUT'


def test_prompt_mode_missing_pass1_output_exits_cleanly(
        tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Prompt mode keeps the pass-1 guard: no output after pass 1 ->
    message, return, no pass 2, neither the final output nor the pass-1
    copy exists."""
    _mod, rec, fake, _seen = _run_prompt_driver(tmp_path, monkeypatch,
                                                [None])
    assert f'MESS pass 1 produced no output {_OUT}, aborting.' in \
        capsys.readouterr().out
    assert fake.calls == [['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 0
    assert not (tmp_path / _OUT).exists()
    assert not (tmp_path / _PASS1).exists()


def test_prompt_mode_pass2_failure_returns_cleanly(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass 2 writes no output: main returns without an exception, the
    pass-1 copy is kept and the final output stays absent (the job is not
    picked up)."""
    _mod, _rec, fake, _seen = _run_prompt_driver(tmp_path, monkeypatch,
                                                 [_HEALTHY_OUT, None])
    assert len(fake.calls) == 2
    assert (tmp_path / _PASS1).read_text() == _HEALTHY_OUT
    assert not (tmp_path / _OUT).exists()


def test_prompt_mode_forced_pass_keeps_input_well_extension(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PES with its own WellExtension value: the forced pass 2 drops the
    bare WellExtension line mess_io inserts, so the value stays."""
    script = _emit(tmp_path, prompt=True)
    mod, _rec = _load_driver(script, monkeypatch)
    monkeypatch.setitem(mod.PES_PAYLOAD, 'well_extension', 0.5)
    monkeypatch.setattr(
        mod, 'well_lumped_input_file',
        lambda *args: 'WellExtension 0.5\nWellExtension\nModel\nEnd\n')
    monkeypatch.setattr(mod.subprocess, 'run',
                        _FakeMessSides(tmp_path, [_HEALTHY_OUT, 'PASS2']))
    monkeypatch.chdir(tmp_path)
    mod.main()
    final = (tmp_path / _INP).read_text()
    assert final == 'WellExtension 0.5\nModel\nEnd\n'
    assert (tmp_path / _OUT).read_text() == 'PASS2'


def test_prompt_flag_reaches_driver_only_through_payload(tmp_path) -> None:
    """The prompt script differs from the plain one only on the
    ``PES_PAYLOAD = `` line, whose literal carries ``prompt_reactions:
    True``; settings None, {} or prompt_reactions False emit byte-identical
    scripts without the key; the template never mentions mechanalyzer."""
    sop = cast(Any, _MinimalSOP([1.0, 10.0], None))
    texts: dict[str, str] = {}
    for label, settings in (('none', None), ('empty', {}),
                            ('off', {'prompt_reactions': False}),
                            ('on', {'prompt_reactions': True})):
        out = _case_dir(tmp_path, label)
        AutomechKinWriter(sop=sop, pes_id=0, settings=settings).write(
            loc=str(out), filename=_FILENAME)
        texts[label] = (out / _FILENAME).read_text()

    assert texts['none'] == texts['empty'] == texts['off']
    plain = texts['none'].splitlines()
    prompt = texts['on'].splitlines()
    assert len(plain) == len(prompt)
    changed = [(a, b) for a, b in zip(plain, prompt) if a != b]
    assert len(changed) == 1
    before, after = changed[0]
    assert before.startswith('PES_PAYLOAD = ')
    assert after.startswith('PES_PAYLOAD = ')
    off = ast.literal_eval(before.removeprefix('PES_PAYLOAD = '))
    on = ast.literal_eval(after.removeprefix('PES_PAYLOAD = '))
    assert 'prompt_reactions' not in off
    assert on == {**off, 'prompt_reactions': True}
    assert 'mechanalyzer' not in automech_kin.automech_kin_tpl


# ===========================================================================
# _globkey_str: PressureList[atm] relabelled to the payload unit
# ===========================================================================
def _load_globkey(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                  globkey: Any = _GLOBKEY4_ATM,
                  pres_unit: str = 'bar') -> tuple[Any, _Recorder]:
    script = _emit(tmp_path, pres_unit=pres_unit, pres=_PRES4)
    return _load_driver(script, monkeypatch, globkey)


def test_globkey_relabels_atm_to_the_payload_unit_only(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact ``PressureList[atm]`` literal becomes the payload unit and
    nothing else changes (byte-for-byte, same numbers, no conversion); a
    non-default unit is used, not a second hardcoded 'bar'; the rewrite is
    idempotent across passes; the wrapped call still gets the payload grid,
    the temperatures, the well extension and the output name."""
    mod, rec = _load_globkey(_case_dir(tmp_path, 'bar'), monkeypatch)
    block = mod._globkey_str(_OUT, None)
    assert 'PressureList[bar]' in block
    assert 'PressureList[atm]' not in block
    assert 'atm' not in block
    assert block == _GLOBKEY4_ATM.replace(
        'PressureList[atm]', 'PressureList[bar]')
    numbers = re.search(r'PressureList\[[^\]]+\]([^\n]*)', block)
    assert numbers is not None
    assert [float(v) for v in numbers.group(1).split()] == _PRES4
    # Two pass-1/pass-2 calls produce the identical block.
    assert mod._globkey_str(_OUT, None) == block

    mod._globkey_str(_OUT, 'WELLEXT')
    seen = rec.last('global_rates_input_v1')
    assert seen['pressures'] == _PRES4
    assert seen['temperatures'] == [500.0, 1000.0]
    assert seen['well_extension'] == 'WELLEXT'
    assert seen['ktp_outname'] == _OUT

    with monkeypatch.context() as mp:
        mod, _rec = _load_globkey(_case_dir(tmp_path, 'torr'), mp,
                                  pres_unit='torr')
        assert mod.PRES_UNIT == 'torr'
        assert 'PressureList[torr]' in mod._globkey_str(_OUT, None)


def test_missing_expected_atm_literal_raises(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Anything but the exact expected literal aborts the driver.

    The rewrite is a plain ``str.replace`` of ``PressureList[atm]``; if
    upstream mess_io ever stops emitting it, a silent no-op would ship a MESS
    input whose declared unit contradicts the grid (the original
    ``ValueError: 0.00987 is not in list`` failure mode further down).
    """
    failures: list[str] = []
    for idx, bad in enumerate((
            _GLOBKEY4_ATM.replace('PressureList[atm]', 'PressureList[torr]'),
            _GLOBKEY4_ATM.replace('PressureList[atm]', 'PressureList[bar]'),
            _GLOBKEY4_ATM.replace('PressureList[atm]', 'PressureList [atm]'),
            _GLOBKEY4_ATM.replace('PressureList[atm]', 'PRESSURELIST[ATM]'),
            '',
            'TemperatureList[K] 500.0\n')):
        with monkeypatch.context() as mp:
            mod, _rec = _load_globkey(_case_dir(tmp_path, f'bad{idx}'), mp,
                                      globkey=bad)
            try:
                mod._globkey_str(_OUT, None)
            except RuntimeError as exc:
                message = str(exc)
                if 'PressureList[atm]' not in message or 'bar' not in message:
                    failures.append(f'case {idx}: message {message!r}')
            else:
                failures.append(f'case {idx} ({bad[:60]!r}): no RuntimeError')
    assert not failures, '\n'.join(failures)


def test_guard_survives_python_O(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -O`` strips ``assert``: the guard is a ``raise`` in the AST,
    and the driver compiled with ``optimize=2`` still raises."""
    script = _emit(tmp_path, pres_unit='bar', pres=_PRES4)
    func = next(
        node for node in ast.parse(script.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == '_globkey_str')
    assert any(isinstance(n, ast.Raise) for n in ast.walk(func))
    assert not any(isinstance(n, ast.Assert) for n in ast.walk(func))

    _install_stubs(monkeypatch, 'PressureList[torr] 1.0\n')
    code = compile(script.read_text(), str(script), 'exec', optimize=2)
    namespace: dict[str, Any] = {'__name__': 'globkey_optimized'}
    exec(code, namespace)
    with pytest.raises(RuntimeError):
        namespace['_globkey_str'](_OUT, None)


# ===========================================================================
# Helpers fed by the parsed MESS input: rotor geometry, rotd rotors, keys
# ===========================================================================
class _FakeStruct:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)
        self._positions = [[float(i), 0.1, 0.2] for i in range(len(symbols))]
        self._masses = [12.0 for _ in symbols]

    def get_chemical_symbols(self) -> list[str]:
        return list(self._symbols)

    def get_positions(self) -> list[list[float]]:
        return [list(p) for p in self._positions]

    def get_masses(self) -> list[float]:
        return list(self._masses)


_GEO = [['C', 0.0, 0.0, -0.7167593768],
        ['C', 0.0, -0.0138418037, 0.7754533982],
        ['H', 0.8849628235, -0.4944548282, -1.1221531269]]

_GEO_GLOBKEY = (
    'TemperatureList[K]                     500.0  1000.0\n'
    'PressureList[atm]                      0.01  0.1\n'
    'RateOutput                             ' + _OUT + '\n'
)


class _FakeRotor:
    def __init__(self, geo: Any = None) -> None:
        self.fourier = False
        self.scan = [0.0, 0.09]
        self.symmetry = 6
        self.ThermalPowerMax = 50.0
        self.group = [3, 4, 5]
        self.axis = [1, 2]
        self.geo = geo


class _FakeWell:
    def __init__(self, name: str, symbols: list[str],
                 h_rotors: list[Any] | None = None) -> None:
        self.name = name
        self.energy = 0.0
        self.structure = _FakeStruct(symbols)
        self.frequencies = [500.0]
        self.elec_levels = [[0.0, 1]]
        self.h_rotors = h_rotors or []
        self.m_rotors: list[Any] = []
        self.dummy = False
        self.pes_ids = [0]
        self.sym_factor = 1.0


class _FakeBimolecular:
    def __init__(self, name: str, f1: _FakeWell, f2: _FakeWell) -> None:
        self.name = name
        self.energy = -5.0
        self.fragments = [f1, f2]
        self.dummy = False
        self.pes_ids = [0]
        self.structure = _FakeStruct(
            f1.structure.get_chemical_symbols()
            + f2.structure.get_chemical_symbols())


class _FakeBarrier:
    def __init__(self, name: str, connected: list[Any], kind: str,
                 h_rotors: list[Any] | None = None) -> None:
        self.name = name
        self.connected = connected
        self.energy = 20.0
        self.frequencies = [400.0]
        self.elec_levels = [[0.0, 2]]
        self.h_rotors = h_rotors or []
        self.pes_ids = [0]
        self.dummy = False
        self.symFact = 2.353
        self.barrierless = kind != 'saddle'
        if kind == 'saddle':
            self.structure = _FakeStruct(['C', 'H', 'O'])
            self.ifreq = -800.0
            self.r_lenergy = 20.0
            self.r_renergy = 15.0
        elif kind == 'rotd':
            self.file = 'ne_c2h5o2.dat'
        else:
            self.pp = 10.0
            self.ppe = 6.0


class _FakeSOP:
    def __init__(self, wells=(), bimols=(), barriers=(), **attrs: Any
                 ) -> None:
        self._wells = list(wells)
        self._bimols = list(bimols)
        self.barriers = list(barriers)
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = [500.0, 1000.0]
        self.pres = [0.01, 0.1]
        self.pres_unit = 'bar'
        self.masses = [4.0, 61.0]
        for key, val in attrs.items():
            setattr(self, key, val)

    def wells_in(self, pes_id: int) -> list[Any]:
        return [w for w in self._wells if pes_id in w.pes_ids]

    def bimols_in(self, pes_id: int) -> list[Any]:
        return [b for b in self._bimols if pes_id in b.pes_ids]


def _load_sop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sop: _FakeSOP
              ) -> tuple[Any, _Recorder]:
    """Emit the driver for ``sop``, check it compiles, load it."""
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)
    writer.write(loc=str(tmp_path), filename=_FILENAME)
    compile((tmp_path / _FILENAME).read_text(), _FILENAME, 'exec')
    return _load_driver(tmp_path / _FILENAME, monkeypatch, _GEO_GLOBKEY)


def _rotd_sop(rotor_geo: Any = _GEO) -> _FakeSOP:
    well = _FakeWell('RO2', ['C', 'C', 'O', 'O'])
    bim = _FakeBimolecular('R+O2', _FakeWell('R', ['C', 'C', 'H']),
                           _FakeWell('O2', ['O', 'O']))
    bar = _FakeBarrier('TSrotd', [well, bim], 'rotd',
                       h_rotors=[_FakeRotor(geo=rotor_geo)])
    return _FakeSOP([well], [bim], [bar])


def test_hind_rot_str_forwards_geo_in_bohr_only_when_present(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C2.1-C2.3: a rotor geometry reaches ``rotor_hindered(geo=...)`` in
    bohr through ``_geo_bohr`` (same helper as species geometries), other
    kwargs untouched; no ``geo`` kwarg without a geometry or with an empty
    one."""
    mod, rec = _load_sop(_case_dir(tmp_path, 'geo'), monkeypatch, _rotd_sop())
    rotors = mod.PES_PAYLOAD['barriers'][0]['hind_rotors']
    assert rotors[0]['geo'] == _GEO
    assert mod._hind_rot_str(rotors) == '<rotor_hindered>'
    kwargs = rec.last('rotor_hindered')
    geo = kwargs['geo']
    assert [row[0] for row in geo] == ['C', 'C', 'H']
    for row, expected in zip(geo, _GEO):
        assert row[1] == pytest.approx(
            tuple(v / _BOHR2ANG for v in expected[1:]))
    assert kwargs['group'] == [2, 3, 4]
    assert kwargs['axis'] == [0, 1]
    assert kwargs['symmetry'] == 6
    assert kwargs['potential_form'] == 'fourier'
    assert kwargs['therm_pow_max'] == 50.0
    rows = mod._geo_bohr(_GEO)
    assert rows[0] == ('C', (0.0, 0.0, pytest.approx(
        -0.7167593768 / _BOHR2ANG)))
    assert len(rows) == 3

    with monkeypatch.context() as mp:
        mod, rec = _load_sop(_case_dir(tmp_path, 'no_geo'), mp,
                             _rotd_sop(rotor_geo=None))
        rotors = mod.PES_PAYLOAD['barriers'][0]['hind_rotors']
        assert 'geo' not in rotors[0]
        mod._hind_rot_str(rotors)
        assert 'geo' not in rec.last('rotor_hindered')
        rotor = dict(rotors[0])
        rotor['geo'] = []
        mod._hind_rot_str([rotor])
        assert 'geo' not in rec.last('rotor_hindered')


def test_barrier_str_rotd_passes_rotors_phasespace_does_not(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C2.4-C2.4d: the rotd branch passes its rotors to
    ``molecule(hind_rot=...)`` with the flux file and symmetry factor;
    without rotors (or without the key, older payloads) hind_rot is ''; the
    phasespace branch passes its rotors too, and ``tstlvl`` only when the
    payload has a tst_level."""
    mod, rec = _load_sop(_case_dir(tmp_path, 'rotd'), monkeypatch, _rotd_sop())
    bar = mod.PES_PAYLOAD['barriers'][0]
    assert bar['kind'] == 'rotd'
    mod._barrier_str(bar)
    assert rec.last('rotor_hindered')['symmetry'] == 6
    assert 'geo' in rec.last('rotor_hindered')
    assert rec.last('molecule')['hind_rot'] == '<rotor_hindered>'
    core = rec.last('core_rotd')
    assert core['sym_factor'] == 2.353
    assert core['flux_file_name'] == 'ne_c2h5o2.dat'
    assert rec.last('ts_sadpt')['ts_data'] == '<molecule>'
    # Payloads produced before this change carry no 'hind_rotors' for rotd.
    legacy = dict(bar)
    del legacy['hind_rotors']
    mod._barrier_str(legacy)
    assert rec.last('molecule')['hind_rot'] == ''

    with monkeypatch.context() as mp:
        sop = _rotd_sop()
        sop.barriers[0].h_rotors = []
        mod, rec = _load_sop(_case_dir(tmp_path, 'rotd_empty'), mp, sop)
        mod._barrier_str(mod.PES_PAYLOAD['barriers'][0])
        assert rec.last('molecule')['hind_rot'] == ''
        assert 'rotor_hindered' not in rec.calls

    with monkeypatch.context() as mp:
        well = _FakeWell('RO2', ['C', 'C', 'O', 'O'])
        bim = _FakeBimolecular('R+O2', _FakeWell('R', ['C', 'C', 'H']),
                               _FakeWell('O2', ['O', 'O']))
        bar = _FakeBarrier('TSpst', [well, bim], 'phasespace',
                           h_rotors=[_FakeRotor(geo=_GEO)])
        mod, rec = _load_sop(_case_dir(tmp_path, 'phasespace'), mp,
                             _FakeSOP([well], [bim], [bar]))
        mod._barrier_str(mod.PES_PAYLOAD['barriers'][0])
        assert rec.last('molecule')['hind_rot'] == '<rotor_hindered>'
        assert 'geo' in rec.last('rotor_hindered')
        assert 'tstlvl' not in rec.last('core_phasespace')

    with monkeypatch.context() as mp:
        well = _FakeWell('RO2', ['C', 'C', 'O', 'O'])
        bim = _FakeBimolecular('R+O2', _FakeWell('R', ['C', 'C', 'H']),
                               _FakeWell('O2', ['O', 'O']))
        bar = _FakeBarrier('TSpst', [well, bim], 'phasespace')
        bar.tst_level = 'EJ'
        mod, rec = _load_sop(_case_dir(tmp_path, 'phasespace_ej'), mp,
                             _FakeSOP([well], [bim], [bar]))
        mod._barrier_str(mod.PES_PAYLOAD['barriers'][0])
        assert rec.last('core_phasespace')['tstlvl'] == 'ej'
        assert rec.last('molecule')['hind_rot'] == ''
        assert 'rotor_hindered' not in rec.calls


def test_globkey_forwards_header_keys_only_when_set(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C2.5-C2.6d: calculation_method / model_ene_limit / excess_ene_temp /
    chem_eig_max reach ``global_rates_input_v1`` when set (each one
    independently, 0.0 included, stable across passes) and are omitted when
    None, so mess_io keeps its own defaults."""
    keys = ('calculation_method', 'model_ene_limit', 'excess_ene_temp',
            'chem_eig_max')
    sop = _FakeSOP(calculation_method='direct', model_ene_limit=400.0,
                   excess_ene_temp=40.0, chem_eig_max=0.2)
    mod, rec = _load_sop(_case_dir(tmp_path, 'all'), monkeypatch, sop)
    block = mod._globkey_str(_OUT, None)
    kwargs = rec.last('global_rates_input_v1')
    assert kwargs['calculation_method'] == 'direct'
    assert kwargs['model_ene_limit'] == 400.0
    assert kwargs['excess_ene_temp'] == 40.0
    assert kwargs['chem_eig_max'] == 0.2
    # The pre-existing kwargs are still forwarded.
    assert kwargs['temperatures'] == [500.0, 1000.0]
    assert kwargs['pressures'] == [0.01, 0.1]
    assert kwargs['well_extension'] is None
    assert kwargs['ktp_outname'] == _OUT
    assert 'PressureList[bar]' in block
    # Stable across passes.
    mod._globkey_str(_OUT, {'RO2': 12.0})
    first, second = rec.kwargs('global_rates_input_v1')
    assert first['calculation_method'] == second['calculation_method']
    assert first['model_ene_limit'] == second['model_ene_limit']
    assert second['well_extension'] == {'RO2': 12.0}

    with monkeypatch.context() as mp:
        mod, rec = _load_sop(_case_dir(tmp_path, 'none'), mp, _FakeSOP())
        for key in ('calc_method', 'model_ene_limit', 'excess_ene_temp',
                    'chem_eig_max'):
            assert mod.PES_PAYLOAD[key] is None, key
        mod._globkey_str(_OUT, None)
        assert set(rec.last('global_rates_input_v1')) == {
            'temperatures', 'pressures', 'well_extension', 'ktp_outname'}

    failures: list[str] = []
    for arg, value in (('calculation_method', 'low-eigenvalue'),
                       ('model_ene_limit', 800.0),
                       ('excess_ene_temp', 30.0),
                       ('chem_eig_max', 0.1),
                       # 0.0 is a legitimate value, not "absent".
                       ('chem_eig_max', 0.0)):
        with monkeypatch.context() as mp:
            mod, rec = _load_sop(_case_dir(tmp_path, f'{arg}_{value}'), mp,
                                 _FakeSOP(**{arg: value}))
            mod._globkey_str(_OUT, None)
            kwargs = rec.last('global_rates_input_v1')
            if kwargs.get(arg, 'MISSING') != value:
                failures.append(f'{arg}={value!r}: forwarded {kwargs.get(arg)!r}')
            others = (set(keys) - {arg}) & set(kwargs)
            if others:
                failures.append(f'{arg}={value!r}: also forwarded {sorted(others)}')
    assert not failures, '\n'.join(failures)


def test_globkey_forwards_hot_energies_as_tuples(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C2.7: a PES whose input carries HotEnergies gets ``hot_enes_dct``
    (well name -> tuple of floats: a range as (start, step, finish), a
    single energy as a 1-tuple), shifted by each well's dE through
    ``SOP.shifted_hot_energies``; identical in pass 1 and pass 2; the
    payload holds lists (a Python literal); the emitted ``_globkey_str`` is
    brace-free (the template is rendered with ``str.format``)."""
    from kimeco.parameters import SOP, PesFileData

    sop = _FakeSOP([_FakeWell('RO2', ['C', 'O', 'O'])])
    sop.items = {'RO2': types.SimpleNamespace(dE=0.5),
                 'QOOH': types.SimpleNamespace(dE=-1.0)}
    sop.pes_file_data = {0: PesFileData(
        hot_energies={'RO2': (-5.0, 1.0, 20.0), 'QOOH': (3.0,)})}
    sop.shifted_hot_energies = types.MethodType(SOP.shifted_hot_energies,
                                                sop)
    mod, rec = _load_sop(_case_dir(tmp_path, 'hot'), monkeypatch, sop)
    assert mod.PES_PAYLOAD['hot_energies'] == {
        'RO2': [-4.5, 1.0, 20.5], 'QOOH': [2.0]}
    mod._globkey_str(_OUT, None)
    mod._globkey_str(_OUT, {'RO2': 12.0})
    first, second = rec.kwargs('global_rates_input_v1')
    assert first['hot_enes_dct'] == {'RO2': (-4.5, 1.0, 20.5),
                                     'QOOH': (2.0,)}
    for values in first['hot_enes_dct'].values():
        assert isinstance(values, tuple)
        assert all(type(v) is float for v in values)
    assert second['hot_enes_dct'] == first['hot_enes_dct']
    assert second['well_extension'] == {'RO2': 12.0}

    tpl = automech_kin.automech_kin_tpl
    body = tpl[tpl.index('def _globkey_str('):]
    body = body[:body.index('\ndef ', 1)]
    assert 'hot_enes_dct' in body
    assert '{' not in body and '}' not in body
