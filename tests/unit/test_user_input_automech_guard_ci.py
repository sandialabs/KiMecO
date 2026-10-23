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
def test_check_automech_gate(tmp_path: Path, monkeypatch) -> None:
    """mess_io import failure cancels; stub mess_io + phydat pass; mess_io
    present but phydat missing still cancels with one warning naming
    phydat."""
    with monkeypatch.context() as m:
        _force_mess_io_import_error(m)
        obj = _bare_input(tmp_path)
        obj._check_automech()
        assert obj.cancel_run is True, "mess_io import failure must cancel"

    with monkeypatch.context() as m:
        _inject_stub_mess_io(m)
        _inject_stub_phydat(m)
        obj = _bare_input(tmp_path)
        obj._check_automech()
        assert obj.cancel_run is False, "stub automech deps must pass"

    with monkeypatch.context() as m:
        _inject_stub_mess_io(m)
        _force_phydat_import_error(m)
        obj = _bare_input(tmp_path)
        recorder = _WarningRecorder()
        obj.klog = recorder
        obj._check_automech()
        assert obj.cancel_run is True, "missing phydat must cancel"
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


def test_full_run_settings_use_automech_guard(
        tmp_path: Path, monkeypatch) -> None:
    """True triggers the guard; False is a no-op; a missing key is
    normalised to the bool False (no guard)."""
    for value, expected_calls in ((True, ['checked']), (False, []),
                                  ('absent', [])):
        with monkeypatch.context() as m:
            obj = _bare_input(tmp_path)
            if value != 'absent':
                obj.json_file['use_automech'] = value
            called = _stub_heavy_stages(m, obj)
            settings = obj.full_run_settings()
            assert called == expected_calls, value
            assert settings['use_automech'] is (value is True), value
            assert isinstance(settings['use_automech'], bool), value


# ===========================================================================
# basic_checks / _check_pp_experiments / _initial_ratio_from_exp
# ===========================================================================
import pytest  # noqa: E402


class _Klog:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: str, *a: Any, **k: Any) -> None:
        self.messages.append(str(msg))

    warning = debug = error = info

    def has(self, fragment: str) -> bool:
        return any(fragment in m for m in self.messages)


def _checked_input(tmp_path: Path, json_file: dict) -> KMOInput:
    obj = _bare_input(tmp_path)
    obj.klog = _Klog()  # type: ignore[assignment]
    obj.json_file = json_file
    return obj


def _valid_exp(**extra: Any) -> dict[str, Any]:
    exp = {'temp': 300.0, 'pres': 1.0, 'cantera_tpl': 't.tpl',
           'data_file': 'd.csv', 'error_file': 'e.csv', 'initial_ratio': {'a': 0.1}}
    exp.update(extra)
    return exp


def test_basic_checks_flags_errors_and_canonicalises_units(tmp_path) -> None:
    bad_exp = {'temp': 300.0, 'pres': 1.0, 'initial_ratio': {},
               'initial_concentration': {}, 'weight': 'x', 'pres_unit': 3}
    obj = _checked_input(tmp_path, {
        'mess_inputs': ['a.inp'], 'q_name': 5,
        'experiments': ['not a dict', bad_exp, _valid_exp(pres_unit='furlong'),
                        _valid_exp(pres_unit='TORR')],
        'pp_experiments': 'nope'})
    obj.basic_checks()
    log = obj.klog  # type: ignore[assignment]
    assert obj.cancel_run
    for fragment in ('ct_yaml is a mandatory keyword.',
                     'q_name has incorrect type',
                     'Experiment 0 should be a dictionary.',
                     "Experiment 1 missing mandatory key 'cantera_tpl'.",
                     "Experiment 1 missing mandatory key 'data_file'.",
                     "Experiment 1 missing mandatory key 'error_file'.",
                     'Experiment 1 should define exactly one of',
                     'Experiment 1 weight should be numeric.',
                     'Experiment 1 pres_unit should be a string.',
                     'Unknown pressure unit: furlong',
                     'pp_experiments should be a list.'):
        assert log.has(fragment), fragment
    assert not any(m.startswith(('Experiment 2 ', 'Experiment 3 ')) for m in log.messages)
    assert obj.json_file['experiments'][3]['pres_unit'] == 'torr'
    assert obj.json_file['pres_unit'] == 'bar'
    assert log.has('Experiment pressure units detected')

    # Valid input: no cancel, default unit filled in
    obj = _checked_input(tmp_path, {
        'mess_inputs': ['a.inp'], 'ct_yaml': 'm.yaml', 'q_name': 'q',
        'experiments': [_valid_exp()]})
    obj.basic_checks()
    assert not obj.cancel_run, obj.klog.messages  # type: ignore[attr-defined]
    assert obj.json_file['experiments'][0]['pres_unit'] == 'bar'

    # Empty experiment list
    obj = _checked_input(tmp_path, {
        'mess_inputs': ['a.inp'], 'ct_yaml': 'm.yaml', 'q_name': 'q',
        'experiments': []})
    obj.basic_checks()
    assert obj.cancel_run
    assert obj.klog.has('experiments should contain at least one item.')  # type: ignore[attr-defined]
    assert not obj.klog.has('units detected')  # type: ignore[attr-defined]


def test_check_pp_experiments_reports_each_rule(tmp_path) -> None:
    # (a) not a list
    obj = _checked_input(tmp_path, {'pp_experiments': {'a': 1}})
    obj._check_pp_experiments()
    assert obj.cancel_run
    assert obj.klog.messages == ['pp_experiments should be a list.']  # type: ignore[attr-defined]

    # (b) per-item rules
    valid = {'temp': 300.0, 'pres': 1.0, 'cantera_tpl': 't', 'times': [1.0],
             'species': ['A'], 'initial_ratio': {'A': 0.1}}
    obj = _checked_input(tmp_path, {'pp_experiments': [
        'x',
        {'data_file': 'd', 'error_file': 'e', 'pres_unit': 1},
        {'temp': 1, 'pres': 1, 'cantera_tpl': 't', 'times': [], 'species': 'A',
         'initial_concentration': {}},
        valid]})
    obj._check_pp_experiments()
    log = obj.klog  # type: ignore[assignment]
    assert obj.cancel_run
    for fragment in ('pp_experiment 0 should be a dictionary.',
                     "pp_experiment 1 missing mandatory key 'temp'.",
                     "pp_experiment 1 missing mandatory key 'times'.",
                     "pp_experiment 1 should not define 'data_file'",
                     "pp_experiment 1 should not define 'error_file'",
                     'pp_experiment 1 should define exactly one of',
                     'pp_experiment 1 pres_unit should be a string.',
                     "pp_experiment 2 'times' should be a non-empty list.",
                     "pp_experiment 2 'species' should be a non-empty list."):
        assert log.has(fragment), fragment
    assert not log.has('pp_experiment 2 missing')
    assert not log.has('pp_experiment 2 should define exactly')
    assert not log.has('pp_experiment 3')

    # (c) key absent
    obj = _checked_input(tmp_path, {})
    obj._check_pp_experiments()
    assert not obj.cancel_run and obj.klog.messages == []  # type: ignore[attr-defined]


def test_initial_ratio_from_ratio_block(tmp_path) -> None:
    obj = _checked_input(tmp_path, {})
    out = obj._initial_ratio_from_exp({'initial_ratio': {'o2': 0.2, 'ch4': 0.1, 'ar': 'base'}})
    assert out == pytest.approx({'o2': 0.2, 'ch4': 0.1, 'ar': 0.7})
    out = obj._initial_ratio_from_exp({'initial_ratio': {'o2': 0.2, 'ch4': 0.1}})
    assert out == pytest.approx({'o2': 0.2, 'ch4': 0.1, 'n2': 0.7})
    for block, msg in (({'a': 'base', 'b': 'BASE'}, 'Two base species'),
                       ({'a': 'x'}, 'should be numeric'),
                       ({'a': 0.6, 'b': 0.5}, 'exceeds 100%')):
        with pytest.raises(ValueError, match=msg):
            obj._initial_ratio_from_exp({'initial_ratio': block})


def test_initial_ratio_from_concentration_block(tmp_path) -> None:
    from scipy.constants import k as k_b
    obj = _checked_input(tmp_path, {})
    base = {'pres': 760.0, 'pres_unit': 'torr', 'temp': 300.0}
    out = obj._initial_ratio_from_exp(
        dict(base, initial_concentration={'o2': 1e17, 'he': 'BASE'}))
    ntot = 101325.0 * 1e-6 / (k_b * 300.0)
    assert out['o2'] == pytest.approx(1e17 / ntot, rel=1e-6)
    assert out['he'] == pytest.approx(1.0 - 1e17 / ntot, rel=1e-9)
    for block, msg in (({'a': 'base', 'b': 'base'}, 'Two base species'),
                       ({'a': 'x'}, 'should be numeric'),
                       ({'a': 1e20}, 'exceeds total pressure')):
        with pytest.raises(ValueError, match=msg):
            obj._initial_ratio_from_exp(dict(base, initial_concentration=block))
