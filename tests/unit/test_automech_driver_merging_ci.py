"""CI-safe tests for the emitted driver's merged-well gate and pass-1 guard.

The emitted automech driver now:

1. runs MESS (pass 1);
2. if ``<name>P<slot>.out`` is absent, prints a message and returns cleanly -
   no rename, no pass 2, no exception - so ``q_sys._pickup_kin``'s
   ``len(p_outs) != n_pes`` gate leaves the job unpicked for retry;
3. otherwise ``os.replace``s the output to the leading-underscore pass-1 copy;
4. runs pass 2 (``well_lumped_input_file`` + WellExtension caps) *only* when
   ``MessOutputReader.well_merging`` reports missing T/P coefficients;
5. otherwise moves the pass-1 copy straight back to the final output name.

Both the emitted *source structure* (AST) and the *runtime behavior* are
checked. The behavioral tests execute the emitted module with stub
``phydat``/``mess_io`` modules and a patched ``subprocess.run``, so no MESS
binary and no real automech install are required.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

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


# ---------------------------------------------------------------------------
# Emission helpers
# ---------------------------------------------------------------------------
class _MinimalSOP:
    """Smallest SOP surface the serializer reads (no species needed here)."""

    def __init__(self) -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = [500.0, 1000.0]
        self.pres = [1.0, 10.0]

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _emit(tmp_path: Path) -> Path:
    writer = AutomechKinWriter(sop=cast(Any, _MinimalSOP()), pes_id=0)
    writer.write(loc=str(tmp_path), filename=_FILENAME)
    return tmp_path / _FILENAME


# ---------------------------------------------------------------------------
# Stub third-party modules so the emitted driver imports without automech.
# ---------------------------------------------------------------------------
class _Recorder:
    """Records every stubbed mess_io call by name."""

    def __init__(self) -> None:
        self.calls: dict[str, list[tuple[Any, ...]]] = {}

    def fn(self, name: str, ret: str = ''):
        def _stub(*args, **kwargs):
            self.calls.setdefault(name, []).append((args, kwargs))
            return ret
        return _stub

    def count(self, name: str) -> int:
        return len(self.calls.get(name, []))


def _install_stubs(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()

    phycon = types.ModuleType('phydat.phycon')
    setattr(phycon, 'BOHR2ANG', 0.52917721092)
    setattr(phycon, 'EH2WAVEN', 219474.6313702)
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

    mess_io = types.ModuleType('mess_io')
    setattr(mess_io, 'writer', writer_mod)
    setattr(mess_io, 'well_lumped_input_file',
            rec.fn('well_lumped_input_file', ret='EXTENDED_INP\n'))

    for name, mod in (('phydat', phydat), ('phydat.phycon', phycon),
                      ('mess_io', mess_io), ('mess_io.writer', writer_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    return rec


_counter = itertools.count()


def _load_driver(script: Path,
                 monkeypatch: pytest.MonkeyPatch) -> tuple[Any, _Recorder]:
    """Import the emitted script as a module (its ``main`` is not run)."""
    rec = _install_stubs(monkeypatch)
    mod_name = f'emitted_driver_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(mod_name, script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, mod_name, mod)
    spec.loader.exec_module(mod)
    return mod, rec


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
                outputs: list[str | None]) -> tuple[Any, _Recorder, _FakeMess]:
    script = _emit(tmp_path)
    mod, rec = _load_driver(script, monkeypatch)
    fake = _FakeMess(tmp_path, outputs)
    monkeypatch.setattr(mod.subprocess, 'run', fake)
    monkeypatch.chdir(tmp_path)
    assert mod.main() is None
    return mod, rec, fake


# ---------------------------------------------------------------------------
# AST structure of the emitted driver
# ---------------------------------------------------------------------------
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


def test_emitted_main_guards_a_missing_pass1_output(tmp_path) -> None:
    """A ``not os.path.isfile(out_name)`` guard returns before pass 2."""
    main = _main_def(_emit(tmp_path).read_text())
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
    body_index = main.body.index(guard)
    merging_index = main.body.index(_merging_if(main))
    assert body_index < merging_index


def test_emitted_main_branches_on_well_merging(tmp_path) -> None:
    main = _main_def(_emit(tmp_path).read_text())
    branch = _merging_if(main)
    assert isinstance(branch.test, ast.Call)
    func = branch.test.func
    assert isinstance(func, ast.Attribute) and func.attr == 'well_merging'
    assert isinstance(func.value, ast.Name)
    assert func.value.id == 'MessOutputReader'
    # Both arms exist: pass 2 on merging, plain restore otherwise.
    assert branch.body and branch.orelse


def test_pass2_machinery_lives_only_in_the_merging_arm(tmp_path) -> None:
    main = _main_def(_emit(tmp_path).read_text())
    branch = _merging_if(main)
    body_calls = [c for stmt in branch.body for c in _called_names(stmt)]
    else_calls = [c for stmt in branch.orelse for c in _called_names(stmt)]

    assert 'well_lumped_input_file' in body_calls
    assert body_calls.count('_run_mess') == 1
    # The non-merging arm only renames the pass-1 copy back.
    assert 'well_lumped_input_file' not in else_calls
    assert '_run_mess' not in else_calls
    assert 'replace' in else_calls


def test_emitted_main_runs_mess_exactly_twice_in_source(tmp_path) -> None:
    main = _main_def(_emit(tmp_path).read_text())
    assert _called_names(main).count('_run_mess') == 2


def test_emitted_driver_uses_os_replace_not_shutil(tmp_path) -> None:
    script = _emit(tmp_path).read_text()
    assert 'os.replace(out_name, pass1_copy)' in script
    assert 'os.replace(pass1_copy, out_name)' in script
    assert 'shutil' not in script


# ---------------------------------------------------------------------------
# Runtime behavior: merging branch
# ---------------------------------------------------------------------------
def test_merging_output_triggers_second_pass(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert args[4] == mod.LUMP_PRESSURE
    assert args[5] == mod.LUMP_TEMP

    # The input was rewritten with the WellExtension-capped version.
    assert (tmp_path / _INP).read_text() == 'EXTENDED_INP\n'
    # Pass-1 result preserved, pass-2 result at the final name.
    assert (tmp_path / _PASS1).read_text() == _MERGING_OUT
    assert (tmp_path / _OUT).read_text() == 'PASS2-OUTPUT'


def test_merging_branch_does_not_move_aux_or_log(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the .out is renamed; .aux/.log are read in place."""
    (tmp_path / _AUX).write_text('AUX-DATA')
    (tmp_path / _LOG).write_text('LOG-DATA')

    _run_driver(tmp_path, monkeypatch, [_MERGING_OUT, 'PASS2-OUTPUT'])

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


# ---------------------------------------------------------------------------
# Runtime behavior: non-merging branch
# ---------------------------------------------------------------------------
def test_healthy_output_skips_the_second_pass(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / _AUX).write_text('AUX-DATA')
    (tmp_path / _LOG).write_text('LOG-DATA')

    _mod, rec, fake = _run_driver(tmp_path, monkeypatch, [_HEALTHY_OUT])

    assert fake.calls == [['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 0
    # Pass-1 result is the final result, moved back under the real name.
    assert (tmp_path / _OUT).read_text() == _HEALTHY_OUT
    assert not (tmp_path / _PASS1).exists()
    # The input is left as written by pass 1.
    assert (tmp_path / _INP).read_text() == 'BASE_INP\n'
    assert (tmp_path / _AUX).read_text() == 'AUX-DATA'
    assert (tmp_path / _LOG).read_text() == 'LOG-DATA'


def test_pass1_globkey_requests_no_well_extension(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pass 1 passes ``well_extension=None``; caps come from mess_io later."""
    _mod, rec, _fake = _run_driver(tmp_path, monkeypatch, [_HEALTHY_OUT])
    _args, kwargs = rec.calls['global_rates_input_v1'][0]
    assert kwargs['well_extension'] is None
    assert kwargs['ktp_outname'] == _OUT


# ---------------------------------------------------------------------------
# Runtime behavior: missing pass-1 output (clean exit)
# ---------------------------------------------------------------------------
def test_missing_pass1_output_exits_cleanly(
        tmp_path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """No output after pass 1 -> message, return, no rename, no pass 2."""
    _mod, rec, fake = _run_driver(tmp_path, monkeypatch, [None])

    out = capsys.readouterr().out
    assert f'MESS pass 1 produced no output {_OUT}, aborting.' in out
    assert fake.calls == [['mess', _INP]]
    assert rec.count('well_lumped_input_file') == 0
    # Neither the final output nor the pass-1 copy exists: the job stays
    # unpicked (q_sys._pickup_kin counts len(p_outs) != n_pes) and is retried.
    assert not (tmp_path / _OUT).exists()
    assert not (tmp_path / _PASS1).exists()


def test_missing_pass1_output_never_calls_well_merging(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The existence guard lives in the driver, ahead of the gate."""
    script = _emit(tmp_path)
    mod, _rec = _load_driver(script, monkeypatch)

    seen: list[str] = []

    def _spy(filename: str) -> bool:
        seen.append(filename)
        return False

    monkeypatch.setattr(mod.MessOutputReader, 'well_merging',
                        staticmethod(_spy))
    monkeypatch.setattr(mod.subprocess, 'run', _FakeMess(tmp_path, [None]))
    monkeypatch.chdir(tmp_path)

    assert mod.main() is None
    assert seen == []


def test_missing_pass1_output_leaves_aux_and_log_untouched(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / _AUX).write_text('AUX-DATA')
    (tmp_path / _LOG).write_text('LOG-DATA')

    _run_driver(tmp_path, monkeypatch, [None])

    assert (tmp_path / _AUX).read_text() == 'AUX-DATA'
    assert (tmp_path / _LOG).read_text() == 'LOG-DATA'
