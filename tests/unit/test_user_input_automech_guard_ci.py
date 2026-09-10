"""CI-safe tests for ``KMOInput._check_automech`` and its gating.

The guard imports the ``mess_io`` writer symbols *and* ``phydat.phycon`` used
by the automech driver scripts before any job is submitted. These tests
simulate either dependency being absent (import failure) or present (stub
modules injected into sys.modules) without requiring automech to be installed.
"""
from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path
from typing import Any

from kimeco.logger_config import KMOLogger
from kimeco.user_input import KMOInput


_WRITER_SYMBOLS = (
    'molecule', 'atom', 'core_rigidrotor', 'core_multirotor',
    'core_phasespace', 'core_rotd', 'rotor_hindered', 'rotor_internal',
    'well', 'bimolecular', 'ts_sadpt', 'ts_variational',
    'global_energy_transfer_input', 'global_rates_input_v1',
    'messrates_inp_str', 'energy_down', 'collision_frequency',
)


def _bare_input(tmp_path: Path) -> KMOInput:
    """Construct a KMOInput without running its file-loading __init__."""
    obj = KMOInput.__new__(KMOInput)
    obj.klog = KMOLogger(filename=str(tmp_path / 'guard.log'))
    obj.cancel_run = False
    obj.init_loc = str(tmp_path) + '/'
    obj.input_file = 'in.json'
    obj.n_exp = 1
    obj.json_file = {}
    return obj


def _inject_stub_mess_io(monkeypatch) -> None:
    mess_io = types.ModuleType('mess_io')
    writer = types.ModuleType('mess_io.writer')
    for sym in _WRITER_SYMBOLS:
        setattr(writer, sym, lambda *a, **k: '')
    mess_io.writer = writer  # type: ignore[attr-defined]
    mess_io.well_lumped_input_file = lambda *a, **k: ''  # type: ignore
    monkeypatch.setitem(sys.modules, 'mess_io', mess_io)
    monkeypatch.setitem(sys.modules, 'mess_io.writer', writer)


def _inject_stub_phydat(monkeypatch) -> None:
    """Register a stub ``phydat`` exposing a ``phycon`` submodule.

    ``phycon`` only ever supplies plain float physical constants, so real
    values are good enough for the import-only probe in the guard.
    """
    phydat = types.ModuleType('phydat')
    phycon = types.ModuleType('phydat.phycon')
    phycon.BOHR2ANG = 0.529177249  # type: ignore[attr-defined]
    phycon.EH2WAVEN = 219474.6313705  # type: ignore[attr-defined]
    phydat.phycon = phycon  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'phydat', phydat)
    monkeypatch.setitem(sys.modules, 'phydat.phycon', phycon)


def _force_mess_io_import_error(monkeypatch) -> None:
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == 'mess_io' or name.startswith('mess_io.'):
            raise ImportError(f'No module named {name!r}')
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, 'mess_io', raising=False)
    monkeypatch.delitem(sys.modules, 'mess_io.writer', raising=False)
    monkeypatch.setattr(builtins, '__import__', _fake_import)


def _force_phydat_import_error(monkeypatch) -> None:
    """Make ``phydat`` unimportable even where automech is really installed."""
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == 'phydat' or name.startswith('phydat.'):
            raise ImportError(f'No module named {name!r}')
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, 'phydat', raising=False)
    monkeypatch.delitem(sys.modules, 'phydat.phycon', raising=False)
    monkeypatch.setattr(builtins, '__import__', _fake_import)


class _WarningRecorder:
    """Minimal klog stand-in capturing warning messages in memory."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: Any) -> None:
        self.warnings.append(str(message))


# ---------------------------------------------------------------------------
# _check_automech direct behavior
# ---------------------------------------------------------------------------
def test_check_automech_cancels_when_import_fails(
        tmp_path: Path, monkeypatch) -> None:
    _force_mess_io_import_error(monkeypatch)
    obj = _bare_input(tmp_path)

    obj._check_automech()

    assert obj.cancel_run is True


def test_check_automech_passes_with_stub_automech_deps(
        tmp_path: Path, monkeypatch) -> None:
    _inject_stub_mess_io(monkeypatch)
    _inject_stub_phydat(monkeypatch)
    obj = _bare_input(tmp_path)

    obj._check_automech()

    assert obj.cancel_run is False


def test_check_automech_cancels_when_phydat_missing(
        tmp_path: Path, monkeypatch) -> None:
    """mess_io present but phydat missing must still cancel the run."""
    _inject_stub_mess_io(monkeypatch)
    _force_phydat_import_error(monkeypatch)
    obj = _bare_input(tmp_path)
    recorder = _WarningRecorder()
    obj.klog = recorder

    obj._check_automech()

    assert obj.cancel_run is True
    assert len(recorder.warnings) == 1
    assert 'phydat' in recorder.warnings[0]


# ---------------------------------------------------------------------------
# full_run_settings gating: guard only runs when use_automech is True
# ---------------------------------------------------------------------------
def _stub_heavy_stages(monkeypatch, obj: KMOInput) -> list[str]:
    """Replace the heavy full_run_settings stages with no-ops and record
    whether _check_automech is invoked."""
    called: list[str] = []
    for stage in ('basic_checks', 'check_unknown_kwords', 'set_default_values',
                  'create_experiments', 'other_checks_to_modif'):
        monkeypatch.setattr(obj, stage, lambda *a, **k: None)
    monkeypatch.setattr(
        obj, '_check_automech',
        lambda: called.append('checked'))
    obj.json_file['project_name'] = 'PROJ'
    return called


def test_full_run_settings_triggers_guard_when_true(
        tmp_path: Path, monkeypatch) -> None:
    obj = _bare_input(tmp_path)
    obj.json_file['use_automech'] = True
    called = _stub_heavy_stages(monkeypatch, obj)

    settings = obj.full_run_settings()

    assert called == ['checked']
    assert settings['use_automech'] is True


def test_full_run_settings_guard_noop_when_false(
        tmp_path: Path, monkeypatch) -> None:
    obj = _bare_input(tmp_path)
    obj.json_file['use_automech'] = False
    called = _stub_heavy_stages(monkeypatch, obj)

    settings = obj.full_run_settings()

    assert called == []
    assert settings['use_automech'] is False


def test_full_run_settings_normalizes_missing_use_automech_to_false(
        tmp_path: Path, monkeypatch) -> None:
    obj = _bare_input(tmp_path)
    # use_automech absent entirely.
    called = _stub_heavy_stages(monkeypatch, obj)

    settings = obj.full_run_settings()

    assert called == []
    assert settings['use_automech'] is False
    assert isinstance(settings['use_automech'], bool)
