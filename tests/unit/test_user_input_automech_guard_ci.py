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


# ===========================================================================
# _check_prompt: settings of the prompt (non-thermal) reactions
# ===========================================================================
_PED_MODELS = ('equip_simple', 'equip_phi', 'rovib_dos', 'beta_phi1a',
               'beta_phi2a', 'beta_phi3a', 'thermal', 'fne')
_MECHANALYZER = ('mechanalyzer', 'mechanalyzer.builder')


def _inject_stub_mechanalyzer(monkeypatch, with_symbol: bool = True) -> None:
    """Register a stub ``mechanalyzer.builder`` (with or without the prompt
    entry point) so the gate's import probe never needs AutoMech."""
    mechanalyzer = types.ModuleType('mechanalyzer')
    builder = types.ModuleType('mechanalyzer.builder')
    if with_symbol:
        builder.multipes_prompt_dissociation_ktp_dct = (  # type: ignore
            lambda *a, **k: {})
    mechanalyzer.builder = builder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'mechanalyzer', mechanalyzer)
    monkeypatch.setitem(sys.modules, 'mechanalyzer.builder', builder)


def _block_mechanalyzer(monkeypatch) -> None:
    """Make mechanalyzer unimportable, even where it is really installed
    (a ``None`` entry in sys.modules makes the import raise)."""
    for name in _MECHANALYZER:
        monkeypatch.setitem(sys.modules, name, None)


def _prompt_input(tmp_path: Path, **json_file: Any
                  ) -> tuple[KMOInput, _WarningRecorder]:
    obj = _bare_input(tmp_path)
    recorder = _WarningRecorder()
    obj.klog = recorder  # type: ignore[assignment]
    obj.json_file = {'prompt_reactions': True, **json_file}
    return obj, recorder


@pytest.mark.parametrize('model', _PED_MODELS)
def test_check_prompt_accepts_every_model(tmp_path, monkeypatch,
                                          model) -> None:
    """Each energy-partition model of mechanalyzer passes with
    use_automech, an importable mechanalyzer and a threshold in range."""
    _inject_stub_mechanalyzer(monkeypatch)
    obj, log = _prompt_input(tmp_path, use_automech=True,
                             prompt_ped_model=model,
                             prompt_bf_threshold=0.01)
    obj._check_prompt()
    assert obj.cancel_run is False, log.warnings
    assert log.warnings == []


def test_check_prompt_uses_defaults_when_keys_absent(tmp_path,
                                                     monkeypatch) -> None:
    """Model and threshold absent (read with .get and the defaults
    rovib_dos / 0.01): accepted."""
    _inject_stub_mechanalyzer(monkeypatch)
    obj, log = _prompt_input(tmp_path, use_automech=True)
    obj._check_prompt()
    assert obj.cancel_run is False, log.warnings
    assert log.warnings == []


@pytest.mark.parametrize('use_automech', [False, 'absent'])
def test_check_prompt_refuses_without_use_automech(tmp_path, monkeypatch,
                                                   use_automech) -> None:
    """use_automech false or absent: one warning naming use_automech,
    run cancelled."""
    _inject_stub_mechanalyzer(monkeypatch)
    extra = {} if use_automech == 'absent' else {
        'use_automech': use_automech}
    obj, log = _prompt_input(tmp_path, **extra)
    obj._check_prompt()
    assert obj.cancel_run is True
    assert len(log.warnings) == 1, log.warnings
    assert "'use_automech'" in log.warnings[0]


@pytest.mark.parametrize('case', ['blocked', 'no_symbol'])
def test_check_prompt_refuses_when_mechanalyzer_missing(tmp_path,
                                                        monkeypatch,
                                                        case) -> None:
    """mechanalyzer not importable, or its builder lacking the prompt entry
    point (plain ImportError): one warning naming mechanalyzer, run
    cancelled."""
    if case == 'blocked':
        _block_mechanalyzer(monkeypatch)
    else:
        _inject_stub_mechanalyzer(monkeypatch, with_symbol=False)
    obj, log = _prompt_input(tmp_path, use_automech=True)
    obj._check_prompt()
    assert obj.cancel_run is True
    assert len(log.warnings) == 1, log.warnings
    assert 'mechanalyzer could not be imported' in log.warnings[0]


@pytest.mark.parametrize('model', ['unknown', '', 'ROVIB_DOS'])
def test_check_prompt_refuses_unknown_model(tmp_path, monkeypatch,
                                            model) -> None:
    """A model outside the eight (exact, case-sensitive match): one warning
    holding the value, run cancelled."""
    _inject_stub_mechanalyzer(monkeypatch)
    obj, log = _prompt_input(tmp_path, use_automech=True,
                             prompt_ped_model=model)
    obj._check_prompt()
    assert obj.cancel_run is True
    assert len(log.warnings) == 1, log.warnings
    assert f"'prompt_ped_model' '{model}'" in log.warnings[0]


@pytest.mark.parametrize('threshold, accepted', [
    (0, True), (0.0, True), (0.5, True), (0.999999, True), (False, True),
    (1, False), (1.0, False), (-0.01, False), (True, False), (2, False),
    (float('nan'), False), ('0.1', False)])
def test_check_prompt_threshold_range(tmp_path, monkeypatch, threshold,
                                      accepted) -> None:
    """The threshold must be a number in [0, 1): 1 excluded, a bool counts
    as an int (False = 0 passes, True = 1 fails), NaN and a string fail."""
    _inject_stub_mechanalyzer(monkeypatch)
    obj, log = _prompt_input(tmp_path, use_automech=True,
                             prompt_bf_threshold=threshold)
    obj._check_prompt()
    assert obj.cancel_run is (not accepted), log.warnings
    if accepted:
        assert log.warnings == []
    else:
        assert len(log.warnings) == 1, log.warnings
        assert "'prompt_bf_threshold' must be in [0, 1)" in log.warnings[0]


def test_check_prompt_reports_every_failure(tmp_path, monkeypatch) -> None:
    """All four checks fail at once: four warnings (no early return), one
    per cause, run cancelled."""
    _block_mechanalyzer(monkeypatch)
    obj, log = _prompt_input(tmp_path, use_automech=False,
                             prompt_ped_model='nope',
                             prompt_bf_threshold=1.5)
    obj._check_prompt()
    assert obj.cancel_run is True
    assert len(log.warnings) == 4, log.warnings
    for warning, needle in zip(log.warnings, (
            "'use_automech'", 'mechanalyzer could not be imported',
            "'prompt_ped_model' 'nope'", "'prompt_bf_threshold'")):
        assert needle in warning, (needle, warning)


def test_full_run_settings_prompt_gate(tmp_path, monkeypatch) -> None:
    """With mechanalyzer blocked, prompt mode off or absent leaves
    full_run_settings untouched (no prompt check, no exit); prompt mode
    without use_automech exits with -1; prompt mode with use_automech and a
    stub mechanalyzer returns the settings."""
    for prompt in (False, 'absent'):
        with monkeypatch.context() as m:
            _block_mechanalyzer(m)
            obj = _bare_input(tmp_path)
            obj.json_file['use_automech'] = True
            if prompt != 'absent':
                obj.json_file['prompt_reactions'] = prompt
            _stub_heavy_stages(m, obj)
            settings = obj.full_run_settings()
            assert obj.cancel_run is False, prompt
            assert settings['project_name'] == 'PROJ'

    with monkeypatch.context() as m:
        _inject_stub_mechanalyzer(m)
        obj = _bare_input(tmp_path)
        obj.json_file['prompt_reactions'] = True
        _stub_heavy_stages(m, obj)
        with pytest.raises(SystemExit) as exc:
            obj.full_run_settings()
        assert exc.value.code == -1

    with monkeypatch.context() as m:
        _inject_stub_mechanalyzer(m)
        obj = _bare_input(tmp_path)
        obj.json_file.update(prompt_reactions=True, use_automech=True)
        _stub_heavy_stages(m, obj)
        settings = obj.full_run_settings()
        assert obj.cancel_run is False
        assert settings['prompt_reactions'] is True


def test_prompt_keys_defaults_and_type_check(tmp_path) -> None:
    """set_default_values fills False / 'rovib_dos' / 0.01 (a float); a
    wrong type cancels (a string flag, an int model, a string threshold);
    an int threshold passes the float check; check_unknown_kwords does not
    flag the three keys."""
    obj, _ = _prompt_input(tmp_path)
    obj.json_file = {}
    obj.klog = _Klog()  # type: ignore[assignment]
    obj.set_default_values()
    assert obj.cancel_run is False
    assert obj.json_file['prompt_reactions'] is False
    assert obj.json_file['prompt_ped_model'] == 'rovib_dos'
    assert obj.json_file['prompt_bf_threshold'] == 0.01
    assert isinstance(obj.json_file['prompt_bf_threshold'], float)

    for key, value in (('prompt_reactions', 'yes'),
                       ('prompt_reactions', 3),
                       ('prompt_ped_model', 3),
                       ('prompt_bf_threshold', 'x')):
        obj = _checked_input(tmp_path, {key: value})
        obj.set_default_values()
        assert obj.cancel_run is True, (key, value)
        assert obj.klog.has(f'{key} has incorrect type'), (  # type: ignore
            key, value)

    obj = _checked_input(tmp_path, {'prompt_bf_threshold': 0})
    obj.set_default_values()
    assert obj.cancel_run is False, obj.klog.messages  # type: ignore

    obj = _checked_input(tmp_path, {
        'prompt_reactions': True, 'prompt_ped_model': 'fne',
        'prompt_bf_threshold': 0.05})
    obj.check_unknown_kwords()
    assert not obj.klog.has('unknown keyword')  # type: ignore[attr-defined]
