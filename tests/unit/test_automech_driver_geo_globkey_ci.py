"""CI-safe tests for the runtime half of the emitted automech driver.

The driver script produced by ``AutomechKinWriter`` is loaded as a module
with ``mess_io``/``phydat`` replaced by recording stubs, then its helpers
are called directly (``main`` never runs, no MESS binary is needed):

* ``_hind_rot_str`` forwards ``geo=`` (converted angstrom -> bohr through
  ``_geo_bohr``) to ``rotor_hindered`` only for rotors carrying a geometry;
* the rotd branch of ``_barrier_str`` passes the barrier's rotors to
  ``molecule(hind_rot=...)`` (the phasespace branch does not);
* ``_globkey_str`` forwards ``calculation_method`` / ``model_ene_limit`` /
  ``excess_ene_temp`` / ``chem_eig_max`` to ``global_rates_input_v1`` only
  when the payload value is not ``None``, so mess_io keeps its own defaults
  otherwise;
* the six top-level template placeholders are unchanged and the emitted
  script still compiles for every PES shape.

Even when a real ``mess_io`` is importable locally, the stubs are installed
in ``sys.modules`` first so the behaviour is identical to vanilla CI.
"""
from __future__ import annotations

import importlib.util
import itertools
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from kimeco.writers import automech_kin
from kimeco.writers.automech_kin import AutomechKinWriter

_BOHR2ANG = 0.52917721092
_FILENAME = 'G0000E0001P03.py'
_OUT = 'G0000E0001P03.out'

_GLOBKEY = (
    'TemperatureList[K]                     500.0  1000.0\n'
    'PressureList[atm]                      0.01  0.1\n'
    'RateOutput                             ' + _OUT + '\n'
)


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Stubbed mess_io that records every call
# ---------------------------------------------------------------------------
class _Calls:
    def __init__(self) -> None:
        self.calls: dict[str, list[dict[str, Any]]] = {}

    def record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.setdefault(name, []).append(dict(kwargs))

    def last(self, name: str) -> dict[str, Any]:
        return self.calls[name][-1]


def _install_stubs(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    calls = _Calls()

    phycon = types.ModuleType('phydat.phycon')
    setattr(phycon, 'BOHR2ANG', _BOHR2ANG)
    setattr(phycon, 'EH2WAVEN', 219474.6313702)
    phydat = types.ModuleType('phydat')
    setattr(phydat, 'phycon', phycon)

    writer_mod = types.ModuleType('mess_io.writer')

    def _make(name: str):
        def _fn(*a: Any, **k: Any) -> str:
            calls.record(name, k)
            return f'<{name}>'
        return _fn

    def _writer_getattr(name: str):
        if name.startswith('__'):
            raise AttributeError(name)
        return _make(name)

    setattr(writer_mod, '__getattr__', _writer_getattr)
    setattr(writer_mod, 'global_rates_input_v1',
            lambda *a, **k: (calls.record('global_rates_input_v1', k),
                             _GLOBKEY)[1])

    mess_io = types.ModuleType('mess_io')
    setattr(mess_io, 'writer', writer_mod)
    setattr(mess_io, 'well_lumped_input_file', lambda *a, **k: '')

    for name, mod in (('phydat', phydat), ('phydat.phycon', phycon),
                      ('mess_io', mess_io), ('mess_io.writer', writer_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    return calls


_counter = itertools.count()


def _load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sop: _FakeSOP
          ) -> tuple[Any, _Calls]:
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)
    writer.write(loc=str(tmp_path), filename=_FILENAME)
    calls = _install_stubs(monkeypatch)
    mod_name = f'geo_globkey_driver_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(
        mod_name, tmp_path / _FILENAME)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, mod_name, mod)
    spec.loader.exec_module(mod)
    return mod, calls


def _rotd_sop(rotor_geo: Any = _GEO) -> _FakeSOP:
    well = _FakeWell('RO2', ['C', 'C', 'O', 'O'])
    bim = _FakeBimolecular('R+O2', _FakeWell('R', ['C', 'C', 'H']),
                           _FakeWell('O2', ['O', 'O']))
    bar = _FakeBarrier('TSrotd', [well, bim], 'rotd',
                       h_rotors=[_FakeRotor(geo=rotor_geo)])
    return _FakeSOP([well], [bim], [bar])


# ---------------------------------------------------------------------------
# C2.1-C2.3: rotor geometry reaches rotor_hindered in bohr
# ---------------------------------------------------------------------------
def test_c2_1_hind_rot_str_forwards_geo_in_bohr(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod, calls = _load(tmp_path, monkeypatch, _rotd_sop())
    rotors = mod.PES_PAYLOAD['barriers'][0]['hind_rotors']
    assert rotors[0]['geo'] == _GEO
    out = mod._hind_rot_str(rotors)
    assert out == '<rotor_hindered>'
    kwargs = calls.last('rotor_hindered')
    assert 'geo' in kwargs
    geo = kwargs['geo']
    assert [row[0] for row in geo] == ['C', 'C', 'H']
    for row, expected in zip(geo, _GEO):
        assert row[1] == pytest.approx(
            tuple(v / _BOHR2ANG for v in expected[1:]))
    # The other kwargs are untouched by the geometry addition.
    assert kwargs['group'] == [2, 3, 4]
    assert kwargs['axis'] == [0, 1]
    assert kwargs['symmetry'] == 6
    assert kwargs['potential_form'] == 'fourier'
    assert kwargs['therm_pow_max'] == 50.0


def test_c2_2_hind_rot_str_omits_geo_kwarg_without_geometry(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod, calls = _load(tmp_path, monkeypatch, _rotd_sop(rotor_geo=None))
    rotors = mod.PES_PAYLOAD['barriers'][0]['hind_rotors']
    assert 'geo' not in rotors[0]
    mod._hind_rot_str(rotors)
    assert 'geo' not in calls.last('rotor_hindered')


def test_c2_2b_hind_rot_str_ignores_empty_geo(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod, calls = _load(tmp_path, monkeypatch, _rotd_sop(rotor_geo=None))
    rotor = dict(mod.PES_PAYLOAD['barriers'][0]['hind_rotors'][0])
    rotor['geo'] = []
    mod._hind_rot_str([rotor])
    assert 'geo' not in calls.last('rotor_hindered')


def test_c2_3_geo_bohr_matches_species_conversion(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Rotor geometries go through the same helper as species geometries.
    mod, _ = _load(tmp_path, monkeypatch, _rotd_sop())
    rows = mod._geo_bohr(_GEO)
    assert rows[0] == ('C', (0.0, 0.0, pytest.approx(
        -0.7167593768 / _BOHR2ANG)))
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# C2.4: rotd barrier passes its rotors to molecule(hind_rot=...)
# ---------------------------------------------------------------------------
def test_c2_4_rotd_barrier_str_passes_hind_rot_to_molecule(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod, calls = _load(tmp_path, monkeypatch, _rotd_sop())
    bar = mod.PES_PAYLOAD['barriers'][0]
    assert bar['kind'] == 'rotd'
    mod._barrier_str(bar)
    assert calls.last('rotor_hindered')['symmetry'] == 6
    assert 'geo' in calls.last('rotor_hindered')
    mol = calls.last('molecule')
    assert mol['hind_rot'] == '<rotor_hindered>'
    core = calls.last('core_rotd')
    assert core['sym_factor'] == 2.353
    assert core['flux_file_name'] == 'ne_c2h5o2.dat'
    assert calls.last('ts_sadpt')['ts_data'] == '<molecule>'


def test_c2_4b_rotd_barrier_without_rotors_passes_empty_hind_rot(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    sop = _rotd_sop()
    sop.barriers[0].h_rotors = []
    mod, calls = _load(tmp_path, monkeypatch, sop)
    mod._barrier_str(mod.PES_PAYLOAD['barriers'][0])
    assert calls.last('molecule')['hind_rot'] == ''
    assert 'rotor_hindered' not in calls.calls


def test_c2_4c_rotd_barrier_str_tolerates_missing_hind_rotors_key(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Payloads produced before this change carry no 'hind_rotors' for rotd.
    mod, calls = _load(tmp_path, monkeypatch, _rotd_sop())
    bar = dict(mod.PES_PAYLOAD['barriers'][0])
    del bar['hind_rotors']
    mod._barrier_str(bar)
    assert calls.last('molecule')['hind_rot'] == ''


def test_c2_4d_phasespace_barrier_str_emits_no_rotors(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    well = _FakeWell('RO2', ['C', 'C', 'O', 'O'])
    bim = _FakeBimolecular('R+O2', _FakeWell('R', ['C', 'C', 'H']),
                           _FakeWell('O2', ['O', 'O']))
    bar = _FakeBarrier('TSpst', [well, bim], 'phasespace',
                       h_rotors=[_FakeRotor(geo=_GEO)])
    mod, calls = _load(tmp_path, monkeypatch, _FakeSOP([well], [bim], [bar]))
    mod._barrier_str(mod.PES_PAYLOAD['barriers'][0])
    assert 'hind_rot' not in calls.last('molecule')
    assert 'rotor_hindered' not in calls.calls


# ---------------------------------------------------------------------------
# C2.5-C2.6: global keyword forwarding
# ---------------------------------------------------------------------------
def test_c2_5_globkey_forwards_all_header_keys_when_present(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    sop = _FakeSOP(calculation_method='direct', model_ene_limit=400.0,
                   excess_ene_temp=40.0, chem_eig_max=0.2)
    mod, calls = _load(tmp_path, monkeypatch, sop)
    block = mod._globkey_str(_OUT, None)
    kwargs = calls.last('global_rates_input_v1')
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


def test_c2_6_globkey_omits_header_kwargs_when_none(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod, calls = _load(tmp_path, monkeypatch, _FakeSOP())
    for key in ('calc_method', 'model_ene_limit', 'excess_ene_temp',
                'chem_eig_max'):
        assert mod.PES_PAYLOAD[key] is None
    mod._globkey_str(_OUT, None)
    kwargs = calls.last('global_rates_input_v1')
    assert set(kwargs) == {'temperatures', 'pressures', 'well_extension',
                           'ktp_outname'}


@pytest.mark.parametrize('present, arg, value', [
    ('calculation_method', 'calculation_method', 'low-eigenvalue'),
    ('model_ene_limit', 'model_ene_limit', 800.0),
    ('excess_ene_temp', 'excess_ene_temp', 30.0),
    ('chem_eig_max', 'chem_eig_max', 0.1),
])
def test_c2_6b_globkey_forwards_each_key_independently(
        tmp_path, monkeypatch: pytest.MonkeyPatch,
        present: str, arg: str, value: Any) -> None:
    mod, calls = _load(tmp_path, monkeypatch, _FakeSOP(**{present: value}))
    mod._globkey_str(_OUT, None)
    kwargs = calls.last('global_rates_input_v1')
    assert kwargs[arg] == value
    others = {'calculation_method', 'model_ene_limit', 'excess_ene_temp',
              'chem_eig_max'} - {arg}
    assert not (others & set(kwargs))


def test_c2_6c_globkey_forwards_zero_values(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 0.0 is a legitimate value and must not be confused with "absent".
    mod, calls = _load(tmp_path, monkeypatch, _FakeSOP(chem_eig_max=0.0))
    mod._globkey_str(_OUT, None)
    assert calls.last('global_rates_input_v1')['chem_eig_max'] == 0.0


def test_c2_6d_globkey_forwarding_is_stable_across_passes(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    sop = _FakeSOP(calculation_method='direct', model_ene_limit=400.0)
    mod, calls = _load(tmp_path, monkeypatch, sop)
    mod._globkey_str(_OUT, None)
    mod._globkey_str(_OUT, {'RO2': 12.0})
    first, second = calls.calls['global_rates_input_v1']
    assert first['calculation_method'] == second['calculation_method']
    assert first['model_ene_limit'] == second['model_ene_limit']
    assert second['well_extension'] == {'RO2': 12.0}


# ---------------------------------------------------------------------------
# C2.7-C2.8: template integrity
# ---------------------------------------------------------------------------
def test_c2_7_template_still_has_exactly_six_placeholders() -> None:
    import string
    fields = {
        name for _, name, _, _ in string.Formatter().parse(
            automech_kin.automech_kin_tpl) if name is not None}
    assert fields == {'payload', 'name', 'slot', 'pres_unit',
                      'lump_pressure', 'lump_temp'}


def test_c2_7b_template_body_uses_dict_calls_not_literals() -> None:
    # str.format-safety: no '{'/'}' outside the placeholders.
    body = automech_kin.automech_kin_tpl
    for token in ('{payload}', '{name}', '{slot}', '{pres_unit}',
                  '{lump_pressure}', '{lump_temp}'):
        body = body.replace(token, '')
    assert '{' not in body and '}' not in body


@pytest.mark.parametrize('builder', [
    lambda: _rotd_sop(),
    lambda: _rotd_sop(rotor_geo=None),
    lambda: _FakeSOP(calculation_method='direct', model_ene_limit=400.0,
                     excess_ene_temp=40.0, chem_eig_max=0.2),
    lambda: _FakeSOP(),
], ids=['rotd_geo', 'rotd_no_geo', 'globkeys', 'empty'])
def test_c2_8_emitted_script_compiles_and_loads(
        tmp_path, monkeypatch: pytest.MonkeyPatch, builder) -> None:
    mod, _ = _load(tmp_path, monkeypatch, builder())
    source = (tmp_path / _FILENAME).read_text()
    compile(source, _FILENAME, 'exec')
    assert callable(mod._hind_rot_str)
    assert callable(mod._globkey_str)
    assert callable(mod._barrier_str)
