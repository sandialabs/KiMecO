"""CI-safe tests for the automech payload built by ``AutomechKinWriter``.

Covers the serializer-side half of the "MESS input parity" change:

* species ``sym_factor`` comes from ``Well.sym_factor`` (default ``1.0``);
* saddle-point ``sym_factor`` comes from ``Barrier.symFact``;
* rotd barriers now carry ``hind_rotors`` (phasespace ones do not);
* a hindered-rotor payload carries ``geo`` only when the rotor had one;
* ``lj_masses`` is ``[bath, species]`` from ``SOP.masses`` when the reader
  captured a ``Masses[amu]`` line, otherwise the N2/heaviest-well heuristic
  plus a ``logging`` warning on ``kimeco.writers.automech_kin``;
* the global header keys (``calc_method``, ``model_ene_limit``,
  ``excess_ene_temp``, ``chem_eig_max``) are forwarded as floats/str or
  ``None`` when absent.

The serializer never imports mess_io, so plain fakes suffice.
"""
from __future__ import annotations

import ast
import logging
from typing import Any, cast

import pytest

from kimeco.writers.automech_kin import AutomechKinWriter


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------
class _FakeStruct:
    def __init__(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)
        self._positions = [[float(i), 0.1 * i, 0.2 * i]
                           for i in range(len(symbols))]
        _mass = {'H': 1.008, 'C': 12.011, 'O': 15.999}
        self._masses = [_mass.get(s, 10.0) for s in symbols]

    def get_chemical_symbols(self) -> list[str]:
        return list(self._symbols)

    def get_positions(self) -> list[list[float]]:
        return [list(p) for p in self._positions]

    def get_masses(self) -> list[float]:
        return list(self._masses)


_GEO = [['C', 0.0, 0.1, 0.2], ['H', 1.0, 1.1, 1.2], ['H', 2.0, 2.1, 2.2]]


class _FakeRotor:
    def __init__(self, geo: Any = None, scan: list[float] | None = None
                 ) -> None:
        self.fourier = False
        self.scan = list(scan) if scan is not None else [0.0, 1.5, 3.0]
        self.symmetry = 3
        self.ThermalPowerMax = 50.0
        self.group = [2, 3, 4]
        self.axis = [1, 5]
        if geo is not None:
            self.geo = geo


class _FakeWell:
    def __init__(self, name: str, symbols: list[str],
                 sym_factor: float | None = 1.0,
                 h_rotors: list[Any] | None = None) -> None:
        self.name = name
        self.energy = 0.0
        self.structure = _FakeStruct(symbols)
        self.frequencies = [500.0, 1500.0]
        self.elec_levels = [[0.0, 1]]
        self.h_rotors = h_rotors or []
        self.m_rotors: list[Any] = []
        self.dummy = False
        self.pes_ids = [0]
        if sym_factor is not None:
            self.sym_factor = sym_factor


class _FakeBimolecular:
    def __init__(self, name: str, f1: _FakeWell, f2: _FakeWell) -> None:
        self.name = name
        self.energy = -5.0
        self.fragments = [f1, f2]
        self.dummy = False
        self.pes_ids = [0]
        # The barrierless serializer locates a *real* Bimolecular side via
        # isinstance; with doubles it falls back to connected[*].structure.
        self.structure = _FakeStruct(
            f1.structure.get_chemical_symbols()
            + f2.structure.get_chemical_symbols())


class _FakeBarrier:
    def __init__(self, name: str, connected: list[Any], kind: str,
                 sym_fact: float = 1.0,
                 h_rotors: list[Any] | None = None) -> None:
        self.name = name
        self.connected = connected
        self.energy = 20.0
        self.frequencies = [400.0]
        self.elec_levels = [[0.0, 2]]
        self.h_rotors = h_rotors or []
        self.pes_ids = [0]
        self.dummy = False
        self.symFact = sym_fact
        self.barrierless = kind != 'saddle'
        if kind == 'saddle':
            self.structure = _FakeStruct(['C', 'H', 'O'])
            self.ifreq = -800.0
            self.r_lenergy = 20.0
            self.r_renergy = 15.0
        elif kind == 'rotd':
            self.file = 'flux.dat'
        else:  # phasespace
            self.pp = 10.0
            self.ppe = 6.0


class _FakeSOP:
    def __init__(self, wells: list[_FakeWell], bimols: list[_FakeBimolecular],
                 barriers: list[_FakeBarrier], **attrs: Any) -> None:
        self._wells = wells
        self._bimols = bimols
        self.barriers = barriers
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = [300.0, 400.0]
        self.pres = [1.0, 10.0]
        self.pres_unit = 'bar'
        for key, val in attrs.items():
            setattr(self, key, val)

    def wells_in(self, pes_id: int) -> list[_FakeWell]:
        return [w for w in self._wells if pes_id in w.pes_ids]

    def bimols_in(self, pes_id: int) -> list[_FakeBimolecular]:
        return [b for b in self._bimols if pes_id in b.pes_ids]


def _payload(sop: _FakeSOP) -> dict[str, Any]:
    return AutomechKinWriter(sop=cast(Any, sop), pes_id=0)._build_payload()


def _writer(sop: _FakeSOP) -> AutomechKinWriter:
    return AutomechKinWriter(sop=cast(Any, sop), pes_id=0)


# ---------------------------------------------------------------------------
# C1.1-C1.3: symmetry factors
# ---------------------------------------------------------------------------
def test_c1_1_well_sym_factor_propagates() -> None:
    sop = _FakeSOP([_FakeWell('W', ['C', 'H'], sym_factor=2.0)], [], [])
    wells = {w['label']: w for w in _payload(sop)['wells']}
    assert wells['W']['sym_factor'] == 2.0
    assert isinstance(wells['W']['sym_factor'], float)


def test_c1_1b_fragment_sym_factor_propagates() -> None:
    f1 = _FakeWell('O2', ['O', 'O'], sym_factor=2.0)
    f2 = _FakeWell('C2H4', ['C', 'C', 'H', 'H', 'H', 'H'], sym_factor=4.0)
    sop = _FakeSOP([], [_FakeBimolecular('B', f1, f2)], [])
    bim = _payload(sop)['bimols'][0]
    assert bim['frag1']['sym_factor'] == 2.0
    assert bim['frag2']['sym_factor'] == 4.0


def test_c1_2_well_without_sym_factor_attr_defaults_to_one() -> None:
    sop = _FakeSOP([_FakeWell('W', ['C', 'H'], sym_factor=None)], [], [])
    assert _payload(sop)['wells'][0]['sym_factor'] == 1.0


def test_c1_3_saddle_sym_factor_from_barrier_symfact() -> None:
    wa = _FakeWell('WA', ['C', 'H'])
    wb = _FakeWell('WB', ['C', 'O'])
    bar = _FakeBarrier('TS', [wa, wb], 'saddle', sym_fact=0.5)
    payload = _payload(_FakeSOP([wa, wb], [], [bar]))
    ts = payload['barriers'][0]
    assert ts['kind'] == 'saddle'
    assert ts['sym_factor'] == 0.5


def test_c1_3b_saddle_sym_factor_is_read_not_hardcoded() -> None:
    # Two saddles with different symFact must serialize differently.
    wa = _FakeWell('WA', ['C', 'H'])
    wb = _FakeWell('WB', ['C', 'O'])
    b1 = _FakeBarrier('TS1', [wa, wb], 'saddle', sym_fact=1.0)
    b2 = _FakeBarrier('TS2', [wa, wb], 'saddle', sym_fact=2.353)
    payload = _payload(_FakeSOP([wa, wb], [], [b1, b2]))
    assert [b['sym_factor'] for b in payload['barriers']] == [1.0, 2.353]


# ---------------------------------------------------------------------------
# C1.4-C1.6: barrier rotors and rotor geometry
# ---------------------------------------------------------------------------
def _bimol_endpoint() -> tuple[_FakeWell, _FakeBimolecular]:
    well = _FakeWell('RO2', ['C', 'C', 'O', 'O'])
    f1 = _FakeWell('R', ['C', 'C', 'H'])
    f2 = _FakeWell('O2', ['O', 'O'])
    return well, _FakeBimolecular('R+O2', f1, f2)


def test_c1_4_rotd_barrier_carries_hind_rotors_with_geo() -> None:
    well, bim = _bimol_endpoint()
    bar = _FakeBarrier('TSrotd', [well, bim], 'rotd', sym_fact=2.353,
                       h_rotors=[_FakeRotor(geo=_GEO)])
    payload = _payload(_FakeSOP([well], [bim], [bar]))
    ts = payload['barriers'][0]
    assert ts['kind'] == 'rotd'
    assert ts['flux_file'] == 'flux.dat'
    assert ts['sym_factor'] == 2.353
    assert len(ts['hind_rotors']) == 1
    rotor = ts['hind_rotors'][0]
    assert rotor['geo'] == _GEO
    assert rotor['group'] == [1, 2, 3]  # 0-based
    assert rotor['axis'] == [0, 4]
    assert rotor['symmetry'] == 3


def test_c1_4b_rotd_barrier_without_rotors_has_empty_list() -> None:
    well, bim = _bimol_endpoint()
    bar = _FakeBarrier('TSrotd', [well, bim], 'rotd')
    ts = _payload(_FakeSOP([well], [bim], [bar]))['barriers'][0]
    assert ts['hind_rotors'] == []


def test_c1_5_phasespace_barrier_has_no_hind_rotors_key() -> None:
    well, bim = _bimol_endpoint()
    bar = _FakeBarrier('TSpst', [well, bim], 'phasespace',
                       h_rotors=[_FakeRotor(geo=_GEO)])
    ts = _payload(_FakeSOP([well], [bim], [bar]))['barriers'][0]
    assert ts['kind'] == 'phasespace'
    # The driver's phasespace branch does not emit rotors; the payload must
    # not pretend otherwise.
    assert 'hind_rotors' not in ts


def test_c1_6_rotor_geo_present_only_when_rotor_had_one() -> None:
    well = _FakeWell('W', ['C', 'C', 'H'],
                     h_rotors=[_FakeRotor(geo=_GEO), _FakeRotor()])
    rotors = _payload(_FakeSOP([well], [], []))['wells'][0]['hind_rotors']
    assert len(rotors) == 2
    assert rotors[0]['geo'] == _GEO
    assert 'geo' not in rotors[1]


def test_c1_6b_rotor_geo_rows_are_float_cast() -> None:
    geo = [['C', '0.0', '0.1', '0.2'], ['H', 1, 2, 3]]
    well = _FakeWell('W', ['C', 'H'], h_rotors=[_FakeRotor(geo=geo)])
    rotor = _payload(_FakeSOP([well], [], []))['wells'][0]['hind_rotors'][0]
    assert rotor['geo'] == [['C', 0.0, 0.1, 0.2], ['H', 1.0, 2.0, 3.0]]
    assert all(isinstance(v, float) for row in rotor['geo'] for v in row[1:])


def test_c1_6c_empty_geo_list_is_treated_as_absent() -> None:
    well = _FakeWell('W', ['C', 'H'], h_rotors=[_FakeRotor(geo=[])])
    rotor = _payload(_FakeSOP([well], [], []))['wells'][0]['hind_rotors'][0]
    assert 'geo' not in rotor


def test_c1_6d_saddle_barrier_rotor_geo_propagates() -> None:
    wa = _FakeWell('WA', ['C', 'H'])
    wb = _FakeWell('WB', ['C', 'O'])
    bar = _FakeBarrier('TS', [wa, wb], 'saddle',
                       h_rotors=[_FakeRotor(geo=_GEO)])
    ts = _payload(_FakeSOP([wa, wb], [], [bar]))['barriers'][0]
    assert ts['hind_rotors'][0]['geo'] == _GEO


# ---------------------------------------------------------------------------
# C1.7-C1.8: Lennard-Jones masses
# ---------------------------------------------------------------------------
def test_c1_7_lj_masses_from_sop_masses(caplog) -> None:
    sop = _FakeSOP([_FakeWell('W', ['C', 'C', 'O', 'O'])], [], [],
                   masses=[4.0, 61.0])
    with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
        payload = _payload(sop)
    assert payload['lj_masses'] == [4.0, 61.0]
    assert caplog.records == []


def test_c1_7b_lj_masses_uses_only_first_two_and_casts_to_float() -> None:
    sop = _FakeSOP([], [], [], masses=[4, 61, 999])
    masses = _payload(sop)['lj_masses']
    assert masses == [4.0, 61.0]
    assert all(isinstance(m, float) for m in masses)


@pytest.mark.parametrize('masses', [[], [4.0]], ids=['empty', 'single'])
def test_c1_8_lj_masses_fallback_warns_and_uses_heuristic(
        caplog, masses: list[float]) -> None:
    wells = [_FakeWell('light', ['C', 'H']),
             _FakeWell('heavy', ['C', 'C', 'O', 'O'])]
    sop = _FakeSOP(wells, [], [], masses=masses)
    with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
        payload = _payload(sop)
    heavy = 2 * 12.011 + 2 * 15.999
    assert payload['lj_masses'] == pytest.approx([28.0134, heavy])
    hits = [r for r in caplog.records
            if r.name == 'kimeco.writers.automech_kin'
            and r.levelno == logging.WARNING]
    assert len(hits) == 1
    assert 'Masses[amu]' in hits[0].getMessage()


def test_c1_8b_lj_masses_fallback_when_sop_lacks_attribute(caplog) -> None:
    sop = _FakeSOP([_FakeWell('W', ['O', 'O'])], [], [])
    assert not hasattr(sop, 'masses')
    with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
        payload = _payload(sop)
    assert payload['lj_masses'] == pytest.approx([28.0134, 2 * 15.999])
    assert any('Masses[amu]' in r.getMessage() for r in caplog.records)


def test_c1_8c_lj_masses_fallback_without_wells_uses_n2_twice(caplog) -> None:
    sop = _FakeSOP([], [], [], masses=[])
    with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
        payload = _payload(sop)
    assert payload['lj_masses'] == [28.0134, 28.0134]


# ---------------------------------------------------------------------------
# C1.9-C1.10: global header keys
# ---------------------------------------------------------------------------
def test_c1_9_global_keys_forwarded() -> None:
    sop = _FakeSOP([], [], [], calculation_method='direct',
                   model_ene_limit=400, excess_ene_temp=40,
                   chem_eig_max=0.2)
    payload = _payload(sop)
    assert payload['calc_method'] == 'direct'
    assert payload['model_ene_limit'] == 400.0
    assert payload['excess_ene_temp'] == 40.0
    assert payload['chem_eig_max'] == 0.2
    for key in ('model_ene_limit', 'excess_ene_temp', 'chem_eig_max'):
        assert isinstance(payload[key], float)


def test_c1_9b_global_keys_none_when_absent_or_missing() -> None:
    explicit = _FakeSOP([], [], [], calculation_method=None,
                        model_ene_limit=None, excess_ene_temp=None,
                        chem_eig_max=None)
    missing = _FakeSOP([], [], [])
    for sop in (explicit, missing):
        payload = _payload(sop)
        for key in ('calc_method', 'model_ene_limit', 'excess_ene_temp',
                    'chem_eig_max'):
            assert key in payload
            assert payload[key] is None


def test_c1_10_payload_survives_repr_roundtrip_with_new_keys(tmp_path
                                                              ) -> None:
    # The payload is embedded via repr() in the driver: everything new must
    # be a literal (ast.literal_eval-able), geo rows included.
    well, bim = _bimol_endpoint()
    bar = _FakeBarrier('TSrotd', [well, bim], 'rotd', sym_fact=2.353,
                       h_rotors=[_FakeRotor(geo=_GEO)])
    sop = _FakeSOP([well], [bim], [bar], masses=[4.0, 61.0],
                   calculation_method='direct', model_ene_limit=400.0,
                   excess_ene_temp=40.0, chem_eig_max=0.2)
    writer = _writer(sop)
    writer.write(loc=str(tmp_path), filename='G0000E0001P00.py')
    script = (tmp_path / 'G0000E0001P00.py').read_text()
    line = next(ln for ln in script.splitlines()
                if ln.startswith('PES_PAYLOAD = '))
    payload = ast.literal_eval(line[len('PES_PAYLOAD = '):])
    assert payload == writer._build_payload()
    assert payload['lj_masses'] == [4.0, 61.0]
    assert payload['barriers'][0]['hind_rotors'][0]['geo'] == _GEO
    compile(script, 'driver.py', 'exec')
