"""End-to-end parity between the normal (template) and automech pipelines.

Both pipelines start from the same user MESS input parsed once by the real
``MessInputReader``. The normal pipeline renders it back through
``MessWriter``; the automech pipeline serializes the parsed SOP through
``AutomechKinWriter`` and, at run time, hands the payload to ``mess_io``.

The values the driver hands to ``mess_io`` (stubbed and recorded here) must
be the ones written by the normal pipeline:

* ``Masses[amu]`` -> ``lj_masses``;
* ``CalculationMethod`` / ``ModelEnergyLimit`` / ``ExcessEnergyOverTemperature``
  / ``ChemicalEigenvalueMax`` -> ``global_rates_input_v1`` kwargs;
* every rigid-rotor ``SymmetryFactor`` -> the species / saddle ``sym_factor``;
* rotor-local ``Geometry[angstrom]`` blocks -> ``rotor_hindered(geo=...)``.

Always-on twin: ``tests/parse_pes/dme/mess_roo_L3.inp`` (tracked). The
``dev_tests/example`` ethyl-oxidation input is gitignored, so the tests that
depend on it are skipped when it is absent.

No MESS binary and no real automech install are needed.
"""
from __future__ import annotations

import importlib.util
import itertools
import re
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from kimeco.barrier import Barrier
from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_input import MessInputReader
from kimeco.writers.automech_kin import AutomechKinWriter
from kimeco.writers.mess import MessWriter

_ROOT = Path(__file__).resolve().parent.parent.parent
DME_ROOT = _ROOT / 'tests' / 'parse_pes' / 'dme'
DME_ROO = 'mess_roo_L3.inp'
DME_OOQOOH = 'mess_ooqooh_L2.inp'
EXAMPLE_ROOT = _ROOT / 'dev_tests' / 'example'
EXAMPLE_INP = 'mess_input_ethyl_oxidation.inp'

_BOHR2ANG = 0.52917721092
_GRID_TEMP = [550.0, 600.0]
_GRID_PRES = [0.1, 1.0]


# ---------------------------------------------------------------------------
# Normal pipeline
# ---------------------------------------------------------------------------
def _settings(root: Path, inputs: list[str]) -> dict[str, Any]:
    return {
        'init_loc': str(root),
        'mess_inputs': inputs,
        'n_exp': 1,
        'score_sp': [],
        'freq_mode': FreqMode.BATCH,
        'rc_temp': list(_GRID_TEMP),
        'rc_pres': list(_GRID_PRES),
        'pres_unit': 'bar',
        'force_new_molecules': True,
    }


class _SpyLog(KMOLogger):
    """KMOLogger that also keeps the warnings in memory."""

    def __init__(self, filename: str) -> None:
        super().__init__(filename=filename)
        self.warnings: list[str] = []

    def warning(self, msg: str = '', *a: Any, **k: Any) -> None:  # type: ignore[override]
        self.warnings.append(str(msg))
        super().warning(msg, *a, **k)


def _parse(tmp_path: Path, root: Path, inputs: list[str]
           ) -> tuple[Any, list[str], MessInputReader]:
    reader = MessInputReader(
        settings=_settings(root, inputs),
        mechanism_species=[],
        klog=_SpyLog(filename=str(tmp_path / 'parity.log')),
        postprocess=False,
    )
    sop, templates = reader.read()
    MessWriter(SOP=sop, tpl=templates[0]).write(
        loc=str(tmp_path), filename='normal.inp')
    return sop, (tmp_path / 'normal.inp').read_text().splitlines(), reader


# ---------------------------------------------------------------------------
# automech pipeline with a recording mess_io stub
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
            if name == 'global_rates_input_v1':
                return 'PressureList[atm] 0.1 1.0\n'
            return f'<{name}>'
        return _fn

    def _writer_getattr(name: str):
        if name.startswith('__'):
            raise AttributeError(name)
        return _make(name)

    setattr(writer_mod, '__getattr__', _writer_getattr)
    mess_io = types.ModuleType('mess_io')
    setattr(mess_io, 'writer', writer_mod)
    setattr(mess_io, 'well_lumped_input_file', lambda *a, **k: '')
    for name, mod in (('phydat', phydat), ('phydat.phycon', phycon),
                      ('mess_io', mess_io), ('mess_io.writer', writer_mod)):
        monkeypatch.setitem(sys.modules, name, mod)
    return calls


_counter = itertools.count()


def _driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sop: Any
            ) -> tuple[Any, _Calls]:
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)
    filename = 'G0000E0001P00.py'
    writer.write(loc=str(tmp_path), filename=filename)
    calls = _install_stubs(monkeypatch)
    mod_name = f'parity_e2e_driver_{next(_counter)}'
    spec = importlib.util.spec_from_file_location(
        mod_name, tmp_path / filename)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, mod_name, mod)
    spec.loader.exec_module(mod)
    return mod, calls


# ---------------------------------------------------------------------------
# Rendered-input helpers (normal pipeline side of the parity)
# ---------------------------------------------------------------------------
def _header_value(lines: list[str], key: str) -> list[str]:
    """Tokens after ``key`` on the (first, uncommented) matching line."""
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(('!', '#')):
            continue
        if stripped.casefold().startswith(key.casefold()):
            toks = stripped.split()
            out: list[str] = []
            for tok in toks[1:]:
                if tok.startswith(('!', '#')):
                    break
                out.append(tok)
            return out
    raise AssertionError(f'{key} not found in rendered input')


def _block_start(lines: list[str], kind: str, name: str) -> int:
    for idx, line in enumerate(lines):
        toks = line.split()
        if len(toks) >= 2 and toks[0].casefold() == kind.casefold() \
                and toks[1] == name:
            return idx
    raise AssertionError(f'{kind} {name} not found in rendered input')


def _symmetry_factor_after(lines: list[str], start: int) -> float:
    for line in lines[start + 1:]:
        if line.lstrip().casefold().startswith('symmetryfactor'):
            return float(line.split()[1])
    raise AssertionError(f'no SymmetryFactor after line {start}')


def _rotor_geos_after(lines: list[str], start: int, stop_kind: str
                      ) -> list[list[list[Any]]]:
    """All rotor-local geometries between ``start`` and the next block."""
    geos: list[list[list[Any]]] = []
    idx = start + 1
    while idx < len(lines):
        stripped = lines[idx].lstrip()
        toks = stripped.split()
        if toks and toks[0].casefold() in ('well', 'bimolecular', 'barrier') \
                and idx != start:
            break
        if stripped.casefold().startswith('rotor'):
            for jdx in range(idx + 1, min(idx + 4, len(lines))):
                inner = lines[jdx].lstrip()
                if inner.casefold().startswith('geometry'):
                    natom = int(inner.split()[1])
                    rows = []
                    for row in lines[jdx + 1:jdx + 1 + natom]:
                        t = row.split()
                        rows.append([t[0], float(t[1]), float(t[2]),
                                     float(t[3])])
                    geos.append(rows)
                    break
        idx += 1
    return geos


def _bohr_rows(geo_ang: list[list[Any]]) -> list[tuple[str, tuple[float, ...]]]:
    return [(row[0], tuple(v / _BOHR2ANG for v in row[1:]))
            for row in geo_ang]


# ===========================================================================
# Always-on twin: tests/parse_pes/dme/mess_roo_L3.inp
# ===========================================================================
@pytest.fixture(scope='module')
def dme(tmp_path_factory) -> dict[str, Any]:
    tmp_path = tmp_path_factory.mktemp('dme_roo')
    sop, rendered, reader = _parse(tmp_path, DME_ROOT, [DME_ROO])
    payload = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)._build_payload()
    return {'sop': sop, 'rendered': rendered, 'reader': reader,
            'payload': payload, 'tmp': tmp_path}


def test_dme_reader_captures_header_keys(dme) -> None:
    sop = dme['sop']
    assert sop.masses == [4.0, 77.0]
    assert sop.calculation_method == 'direct'
    assert sop.model_ene_limit == 400.0
    assert sop.excess_ene_temp == 30.0
    assert sop.chem_eig_max == 0.2
    assert dme['reader']._trigger_stop is False


def test_dme_header_parity_masses(dme) -> None:
    rendered, payload = dme['rendered'], dme['payload']
    normal = [float(t) for t in _header_value(rendered, 'Masses[amu]')]
    assert payload['lj_masses'] == normal == [4.0, 77.0]


def test_dme_header_parity_global_keys(dme) -> None:
    rendered, payload = dme['rendered'], dme['payload']
    assert payload['calc_method'] == \
        _header_value(rendered, 'CalculationMethod')[0]
    assert payload['model_ene_limit'] == \
        float(_header_value(rendered, 'ModelEnergyLimit[kcal/mol]')[0])
    assert payload['excess_ene_temp'] == \
        float(_header_value(rendered, 'ExcessEnergyOverTemperature')[0])
    assert payload['chem_eig_max'] == \
        float(_header_value(rendered, 'ChemicalEigenvalueMax')[0])


def test_dme_global_keys_reach_mess_io(dme, tmp_path, monkeypatch) -> None:
    mod, calls = _driver(tmp_path, monkeypatch, dme['sop'])
    mod._globkey_str('x.out', None)
    kwargs = calls.last('global_rates_input_v1')
    assert kwargs['calculation_method'] == 'direct'
    assert kwargs['model_ene_limit'] == 400.0
    assert kwargs['excess_ene_temp'] == 30.0
    assert kwargs['chem_eig_max'] == 0.2


def test_dme_lj_masses_reach_collision_frequency(
        dme, tmp_path, monkeypatch) -> None:
    mod, calls = _driver(tmp_path, monkeypatch, dme['sop'])
    mod._energy_transfer_str()
    collid = calls.last('collision_frequency')
    assert collid['mass1'] == 4.0
    assert collid['mass2'] == 77.0


@pytest.mark.parametrize('kind, name, expected', [
    ('Well', 'CH3OCH2OO', 1.0),
    ('Fragment', 'O2', 2.0),
    ('Fragment', 'C1H2OC(O1)H2', 4.0),
    ('Fragment', 'CH3OCHO', 1.0),
])
def test_dme_species_symmetry_factor_parity(
        dme, kind: str, name: str, expected: float) -> None:
    rendered, payload = dme['rendered'], dme['payload']
    normal = _symmetry_factor_after(rendered, _block_start(rendered, kind,
                                                            name))
    species = {w['label']: w for w in payload['wells']}
    for bim in payload['bimols']:
        species[bim['frag1']['label']] = bim['frag1']
        species[bim['frag2']['label']] = bim['frag2']
    assert species[name]['sym_factor'] == normal == expected


def test_dme_saddle_symmetry_factor_parity(dme) -> None:
    rendered, payload = dme['rendered'], dme['payload']
    name = 'CH3OCH2OO=CH3OCHO+OH'
    normal = _symmetry_factor_after(
        rendered, _block_start(rendered, 'Barrier', name))
    saddle = next(b for b in payload['barriers'] if b['label'] == name)
    assert saddle['kind'] == 'saddle'
    assert saddle['sym_factor'] == normal == 0.5


def test_dme_saddle_symfact_reaches_core_rigidrotor(
        dme, tmp_path, monkeypatch) -> None:
    mod, calls = _driver(tmp_path, monkeypatch, dme['sop'])
    saddle = next(b for b in mod.PES_PAYLOAD['barriers']
                  if b['label'] == 'CH3OCH2OO=CH3OCHO+OH')
    mod._barrier_str(saddle)
    assert calls.last('core_rigidrotor')['sym_factor'] == 0.5


def test_dme_phasespace_rotor_geometries_captured_on_barrier(dme) -> None:
    sop, rendered = dme['sop'], dme['rendered']
    name = 'CH3OCH2OO=CH3OCH2+O2'
    bar = sop.items[name]
    assert isinstance(bar, Barrier) and bar.barrierless
    assert len(bar.h_rotors) == 2
    geos = [hr.geo for hr in bar.h_rotors]
    assert all(len(g) == 8 for g in geos)
    normal = _rotor_geos_after(rendered, _block_start(rendered, 'Barrier',
                                                       name), 'Barrier')
    assert normal == geos
    # No other rotor in this file carries its own geometry.
    for label, item in sop.items.items():
        if label == name:
            continue
        for hr in getattr(item, 'h_rotors', []):
            assert hr.geo is None, label


def test_dme_phasespace_payload_has_no_rotor_key(dme) -> None:
    pst = next(b for b in dme['payload']['barriers']
               if b['label'] == 'CH3OCH2OO=CH3OCH2+O2')
    assert pst['kind'] == 'phasespace'
    assert 'hind_rotors' not in pst


def test_dme_wells_without_rotor_geometry_emit_no_geo(
        dme, tmp_path, monkeypatch) -> None:
    mod, calls = _driver(tmp_path, monkeypatch, dme['sop'])
    for well in mod.PES_PAYLOAD['wells']:
        assert all('geo' not in hr for hr in well['hind_rotors'])
    mod._rxn_chan_str()
    assert calls.calls['rotor_hindered']
    assert all('geo' not in k for k in calls.calls['rotor_hindered'])


def test_dme_pair_species_mass_difference_does_not_stop(tmp_path) -> None:
    """roo (4.0/77.0) + ooqooh (4.0/109.0): bath matches, species differs."""
    sop, _, reader = _parse(tmp_path, DME_ROOT, [DME_ROO, DME_OOQOOH])
    assert sop.masses == [4.0, 77.0]  # first file wins
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    assert not any('bath mass' in w.casefold() for w in warnings)
    assert not any('Different' in w for w in warnings)
    assert reader._trigger_stop is False


# ===========================================================================
# dev_tests/example (gitignored): skipped when absent
# ===========================================================================
_example_missing = not (EXAMPLE_ROOT / EXAMPLE_INP).is_file()
example_only = pytest.mark.skipif(
    _example_missing,
    reason='dev_tests/example is gitignored and not present here')


@pytest.fixture(scope='module')
def example(tmp_path_factory) -> dict[str, Any]:
    tmp_path = tmp_path_factory.mktemp('example_ethyl')
    sop, rendered, reader = _parse(tmp_path, EXAMPLE_ROOT, [EXAMPLE_INP])
    payload = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)._build_payload()
    return {'sop': sop, 'rendered': rendered, 'reader': reader,
            'payload': payload}


@example_only
def test_example_header_keys_and_masses(example) -> None:
    sop, payload, rendered = example['sop'], example['payload'], \
        example['rendered']
    assert sop.masses == [4.0, 61.0]
    assert payload['lj_masses'] == [4.0, 61.0]
    assert payload['lj_masses'] == [
        float(t) for t in _header_value(rendered, 'Masses[amu]')]
    assert payload['calc_method'] == 'direct'
    assert payload['model_ene_limit'] == 400.0
    assert payload['excess_ene_temp'] == 40.0
    assert payload['chem_eig_max'] == 0.2
    assert example['reader']._trigger_stop is False


@example_only
@pytest.mark.parametrize('kind, name, expected', [
    ('Fragment', 'O2', 2.0),
    ('Fragment', 'C2H4', 4.0),
    ('Fragment', 'c-CH2CH2O', 2.0),
    ('Well', 'CH2CH2OOH', 1.0),
])
def test_example_species_symmetry_factor_parity(
        example, kind: str, name: str, expected: float) -> None:
    rendered, payload = example['rendered'], example['payload']
    normal = _symmetry_factor_after(rendered, _block_start(rendered, kind,
                                                            name))
    species = {w['label']: w for w in payload['wells']}
    for bim in payload['bimols']:
        species[bim['frag1']['label']] = bim['frag1']
        species[bim['frag2']['label']] = bim['frag2']
    assert species[name]['sym_factor'] == normal == expected


@example_only
def test_example_saddle_symmetry_factor_parity(example) -> None:
    rendered, payload = example['rendered'], example['payload']
    name = 'CH3CH2OO=CH2CH2OOH'
    normal = _symmetry_factor_after(
        rendered, _block_start(rendered, 'Barrier', name))
    saddle = next(b for b in payload['barriers'] if b['label'] == name)
    assert saddle['kind'] == 'saddle'
    assert saddle['sym_factor'] == normal == 0.5


@example_only
def test_example_rotd_barrier_symfact_and_rotor_geo(example) -> None:
    sop, payload, rendered = example['sop'], example['payload'], \
        example['rendered']
    name = 'CH3CH2OO=C2H5+O2'
    rotd = next(b for b in payload['barriers'] if b['label'] == name)
    assert rotd['kind'] == 'rotd'
    assert rotd['sym_factor'] == 2.353
    assert len(rotd['hind_rotors']) == 1
    geo = rotd['hind_rotors'][0]['geo']
    assert len(geo) == 7
    assert [row[0] for row in geo] == ['C', 'C', 'H', 'H', 'H', 'H', 'H']
    normal = _rotor_geos_after(
        rendered, _block_start(rendered, 'Barrier', name), 'Barrier')
    assert normal == [geo]
    assert sop.items[name].h_rotors[0].geo == geo


@example_only
def test_example_rotd_rotor_geo_reaches_mess_io_in_bohr(
        example, tmp_path, monkeypatch) -> None:
    mod, calls = _driver(tmp_path, monkeypatch, example['sop'])
    rotd = next(b for b in mod.PES_PAYLOAD['barriers']
                if b['label'] == 'CH3CH2OO=C2H5+O2')
    mod._barrier_str(rotd)
    kwargs = calls.last('rotor_hindered')
    expected = _bohr_rows(rotd['hind_rotors'][0]['geo'])
    assert [r[0] for r in kwargs['geo']] == [r[0] for r in expected]
    for got, exp in zip(kwargs['geo'], expected):
        assert got[1] == pytest.approx(exp[1])
    assert calls.last('molecule')['hind_rot'] == '<rotor_hindered>'
    assert calls.last('core_rotd')['sym_factor'] == 2.353


@example_only
def test_example_global_keys_reach_mess_io(
        example, tmp_path, monkeypatch) -> None:
    mod, calls = _driver(tmp_path, monkeypatch, example['sop'])
    mod._globkey_str('x.out', None)
    kwargs = calls.last('global_rates_input_v1')
    assert kwargs['calculation_method'] == 'direct'
    assert kwargs['model_ene_limit'] == 400.0
    assert kwargs['excess_ene_temp'] == 40.0
    assert kwargs['chem_eig_max'] == 0.2
    # A WellReductionThreshold must not be introduced by the driver itself.
    block = mod._globkey_str('x.out', None)
    assert not re.search(r'WellReductionThreshold', block)
