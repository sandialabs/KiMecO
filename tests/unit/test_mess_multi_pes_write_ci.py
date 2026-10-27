"""CI-safe tests: both MESS writers write each PES of a multi-file SOP.

A SOP read from several MESS input files (one PES each) is written back one
file per PES by ``MessWriter`` (``<name>P<NN>.inp``) and by
``AutomechKinWriter`` (payload + emitted mess_io driver). Each slot gets its
own input file's data:

* energies in the energy zero of its own file;
* the Lennard-Jones pair ``collider, second value of this file`` and its
  own ``Masses``, ``ModelEnergyLimit``, ``WellExtension``,
  ``AtomDistanceMin``, ``PEDSpecies``, ``MicroEner*`` lines;
* side outputs named after the written file (``<stem>.out``,
  ``<stem>_ped.out``, ``<stem>_ke.out``), every SOP;
* PotentialSpline rotors, ``Atom`` fragments, the ``density`` keyword and
  ``TSTLevel`` written back.

The emitted automech driver runs in-process with phydat / mess_io stubs
(``test_automech_driver_ci.py``); one test renders the real mess_io strings
and skips without the ``automech`` extra.

Back-compatibility goldens (``tests/unit/data/mess_writer_golden/``): the
``MessWriter`` input files and ``AutomechKinWriter`` payloads written by the
code before multi-PES parsing (git 3779e43) for the ethyl example and the
DME pair of ``tests/parse_pes/dme`` (grid 550/600 K, 0.1/1.0 bar). Ethyl is
byte-identical; the DME differences are listed in
``test_single_file_and_dme_outputs_match_goldens``. The goldens are data, not
code: the tests never regenerate them.
"""
from __future__ import annotations

import ast
import json
import logging
import re
import types
from pathlib import Path
from typing import Any

import pytest

from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_input import MessInputReader
from kimeco.writers import automech_kin
from kimeco.writers.automech_kin import AutomechKinWriter
from kimeco.writers.mess import MessWriter
from tests.unit.test_automech_driver_ci import (_MERGING_OUT, _Recorder,
                                                _load_driver)
from tests.unit.test_installation_extras_ci import import_or_skip
from tests.unit.test_installation_imports_ci import FORBIDDEN_SOURCE_PATTERNS
from tests.unit.test_mess_multi_pes_read_ci import (assert_clean, atom, bimol,
                                                    fragment, mess_file,
                                                    pst, read,
                                                    rotor, well)

REPO = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / 'data' / 'mess_writer_golden'
EH2WAVEN = 219474.6313702


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def _spline_rotor() -> list[str]:
    return rotor(scan='0.0000 1.5580 3.2660 1.6201',
                 angles='0.00 30.00 60.00 90.00', symmetry=3)


def _shared_blocks(shift: float = 0.0) -> list[list[str]]:
    """A+H (Atom H with density), the fake well (spline + plain rotor) and
    the PST barrier (one rotor, TSTLevel EJ), energies + ``shift``."""
    return [
        bimol('A+H', [fragment('A'), atom('H', density=True)],
              round(0.0 + shift, 6)),
        well('FakeW-A+H', round(-1.0 + shift, 6),
             rotors=[_spline_rotor(), rotor(group='1', axis='2 1')]),
        pst('A+H=FakeW-A+H', 'A+H', 'FakeW-A+H', round(0.0 + shift, 6),
            rotors=[rotor()]),
    ]


_SHARED_HEADER = ['EnergyStepOverTemperature .2\n']
# WellReductionThreshold is per PES: each file its own value.
_WRT_A = ['WellReductionThreshold 12\n']
_WRT_B = ['WellReductionThreshold 14\n']
_RELAX = ['      ExponentCutoff 20\n']
_HEADER_A = ['ModelEnergyLimit[kcal/mol] 400\n', 'WellExtension 0.5\n',
             'AtomDistanceMin[angstrom] 0.68793\n',
             'PEDSpecies A+H=FakeW-A+H\n',
             'MicroEnerMin[kcal/mol] 0.\n', 'MicroEnerMax[kcal/mol] 200.\n',
             'MicroEnerStep[kcal/mol] 1.\n',
             'RateOutput rate.out\n', 'PEDOutput ped.out\n',
             'MicroRateOutput ke.out\n', '!RateOutput me.out\n']
_HEADER_B = ['ModelEnergyLimit[kJ/mol] 3347.2\n',
             'AtomDistanceMin[bohr] 1.3\n', 'RateOutput rate.out\n']


def _rich_pair() -> tuple[list[str], list[str]]:
    """File A (reference) and file B (+1.61 kcal/mol, own LJ second values
    and masses, its own header keys)."""
    a = mess_file(*_shared_blocks(), well('UA', -3.0),
                  header=_SHARED_HEADER + _WRT_A + _HEADER_A, relax=_RELAX,
                  eps='7.95 206.15', sig='2.715 4.71', masses='4.0 77.0')
    b = mess_file(*_shared_blocks(1.61), well('UB', 2.0),
                  header=_SHARED_HEADER + _WRT_B + _HEADER_B, relax=_RELAX,
                  eps='7.95 300.0', sig='2.715 5.0', masses='4.0 109.0')
    return a, b


def _write_slots(sop: Any, tpls: list[Any], out: Path,
                 stems: list[str] | None = None) -> list[Path]:
    """MessWriter output of every slot, ``<stem>.inp`` in ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    stems = stems or [f'G0001P{k:02d}' for k in range(len(tpls))]
    paths = []
    for stem, tpl in zip(stems, tpls):
        MessWriter(SOP=sop, tpl=tpl).write(loc=str(out),
                                           filename=f'{stem}.inp')
        paths.append(out / f'{stem}.inp')
    return paths


def _energies(sop: Any) -> dict[str, float]:
    return {name: float(item.energy) for name, item in sop.items.items()
            if hasattr(item, 'pes_ids') and item.pes_ids}


def _mkdir(path: Path) -> Path:
    path.mkdir()
    return path


def _reread(path: Path, tmp: Path) -> Any:
    """Read one written file alone (its own energy zero)."""
    tmp.mkdir()
    sop, _, reader = read(tmp, path.read_text().splitlines(keepends=True))
    assert_clean(reader)
    return sop


def _line(path: Path, key: str) -> str:
    hits = [ln for ln in path.read_text().splitlines()
            if ln.strip().startswith(key)]
    assert len(hits) == 1, (key, hits)
    return hits[0].strip()


def _pair(c: float, x: float) -> str:
    return f' {c: 7.4f} {x: 7.4f}'


def _driver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sop: Any,
            pes_id: int, globkey: str | None = None,
            base: str = 'G0001') -> tuple[Any, _Recorder]:
    """Emit the automech driver of one PES and import it with stubs."""
    sub = tmp_path / f'drv_{pes_id}_{len(list(tmp_path.iterdir()))}'
    sub.mkdir()
    name = f'{base}P{pes_id:02d}.py'
    AutomechKinWriter(sop=sop, pes_id=pes_id).write(loc=str(sub),
                                                    filename=name)
    if globkey is None:
        return _load_driver(sub / name, monkeypatch)
    return _load_driver(sub / name, monkeypatch, globkey)


# ---------------------------------------------------------------------------
# W1: each file written in its own energy frame
# ---------------------------------------------------------------------------
def test_messwriter_each_file_in_own_frame(tmp_path) -> None:
    """Every ZeroEnergy / GroundEnergy of slot k (PST included) is file k's
    raw value: each output re-read alone equals the original file read
    alone; perturbing a shared well moves it in both outputs."""
    a, b = _rich_pair()
    sop, tpls, reader = read(tmp_path, a, b)
    assert_clean(reader)
    assert sop.pes_file_data[1].energy_offset == pytest.approx(1.61)
    paths = _write_slots(sop, tpls, tmp_path / 'out')
    for k, original in enumerate((a, b)):
        alone = read(_mkdir(tmp_path / f'alone{k}'), original)[0]
        again = _reread(paths[k], tmp_path / f'again{k}')
        assert _energies(again) == pytest.approx(_energies(alone))
    assert 'ZeroEnergy[kcal/mol] 0.61\n' in paths[1].read_text()
    assert 'ZeroEnergy[kcal/mol] -1.0\n' in paths[0].read_text()

    sop.update('FakeW-A+H__we', 0.0)
    paths = _write_slots(sop, tpls, tmp_path / 'moved')
    first = _reread(paths[0], tmp_path / 'moved0')
    second = _reread(paths[1], tmp_path / 'moved1')
    assert first.items['FakeW-A+H'].energy == pytest.approx(0.0)
    assert second.items['FakeW-A+H'].energy == pytest.approx(1.61)
    assert second.items['UB'].energy == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# W2: per-PES header lines
# ---------------------------------------------------------------------------
def test_messwriter_per_pes_header_lines(tmp_path) -> None:
    """Slot k writes ``collider x_k`` on Epsilons / Sigmas and its own raw
    Masses, ModelEnergyLimit, WellExtension, AtomDistanceMin, PEDSpecies,
    MicroEner and WellReductionThreshold lines; every header lists
    __epsilon0..2; updating __epsilon2 changes only slot 1's Epsilons
    line."""
    sop, tpls, reader = read(tmp_path, *_rich_pair())
    assert_clean(reader)
    p0, p1 = _write_slots(sop, tpls, tmp_path / 'out')
    assert _line(p0, 'Epsilons') == 'Epsilons[1/cm] ' + _pair(7.95, 206.15)
    assert _line(p1, 'Epsilons') == 'Epsilons[1/cm] ' + _pair(7.95, 300.0)
    assert _line(p0, 'Sigmas') == 'Sigmas[angstrom] ' + _pair(2.715, 4.71)
    assert _line(p1, 'Sigmas') == 'Sigmas[angstrom] ' + _pair(2.715, 5.0)
    assert _line(p0, 'Masses') == 'Masses[amu]  4.0 77.0'
    assert _line(p1, 'Masses') == 'Masses[amu]  4.0 109.0'
    text0, text1 = p0.read_text(), p1.read_text()
    for line in _HEADER_A[:7]:
        assert line in text0 and line not in text1, line
    for line in _HEADER_B[:2]:
        assert line in text1 and line not in text0, line
    assert _line(p0, 'WellReductionThreshold') == 'WellReductionThreshold 12'
    assert _line(p1, 'WellReductionThreshold') == 'WellReductionThreshold 14'
    for text in (text0, text1):
        assert 'ExponentCutoff 20\n' in text
        assert 'EnergyStepOverTemperature .2\n' in text
        for k in range(3):
            assert f'!__epsilon{k}: ' in text and f'!__sigma{k}: ' in text
        assert '!__epsilon3' not in text

    sop.update('__epsilon2', 333.0)
    q0, q1 = _write_slots(sop, tpls, tmp_path / 'updated')
    assert _line(q0, 'Epsilons') == _line(p0, 'Epsilons')
    assert _line(q1, 'Epsilons') == 'Epsilons[1/cm] ' + _pair(7.95, 333.0)
    assert '!__epsilon2: 333.0\n' in q0.read_text()


# ---------------------------------------------------------------------------
# W2b: side-output names follow the written file
# ---------------------------------------------------------------------------
def test_side_output_names_per_file_every_sop(tmp_path,
                                              monkeypatch) -> None:
    """RateOutput / PEDOutput / MicroRateOutput -> <stem>.out /
    <stem>_ped.out / <stem>_ke.out, for one file and for two files written
    in one directory; the commented line stays raw; the automech driver of
    the same slot uses the same names."""
    single = mess_file(well('W'), header=_HEADER_A[7:])
    sop, tpls, reader = read(_mkdir(tmp_path / 'one'), single)
    assert_clean(reader)
    (path,) = _write_slots(sop, tpls, tmp_path / 'one_out', ['G0007P00'])
    assert _line(path, 'RateOutput') == 'RateOutput G0007P00.out'
    assert _line(path, 'PEDOutput') == 'PEDOutput G0007P00_ped.out'
    assert _line(path, 'MicroRateOutput') == \
        'MicroRateOutput G0007P00_ke.out'
    assert '!RateOutput me.out\n' in path.read_text()

    sop, tpls, reader = read(_mkdir(tmp_path / 'two'), *_rich_pair())
    assert_clean(reader)
    paths = _write_slots(sop, tpls, tmp_path / 'two_out')
    assert [p.name for p in paths] == ['G0001P00.inp', 'G0001P01.inp']
    assert _line(paths[0], 'RateOutput') == 'RateOutput G0001P00.out'
    assert _line(paths[1], 'RateOutput') == 'RateOutput G0001P01.out'
    assert _line(paths[0], 'PEDOutput') == 'PEDOutput G0001P00_ped.out'

    mod, rec = _driver(tmp_path, monkeypatch, sop, 0)
    mod._globkey_str('G0001P00.out', None)
    kwargs = rec.last('global_rates_input_v1')
    assert kwargs['ktp_outname'] == 'G0001P00.out'
    assert kwargs['ped_outname'] == 'G0001P00_ped.out'
    assert kwargs['ke_outname'] == 'G0001P00_ke.out'


# ---------------------------------------------------------------------------
# W3: spline rotors, Atom, density, TSTLevel written back
# ---------------------------------------------------------------------------
def test_messwriter_spline_atom_density_tstlevel(tmp_path) -> None:
    """The written slot keeps the spline block, the Atom block, the density
    keyword on the flagged fragment only and TSTLevel EJ; re-read alone it
    gives the same rotors, atom, flags and TST level."""
    sop, tpls, reader = read(tmp_path, *_rich_pair())
    assert_clean(reader)
    path = _write_slots(sop, tpls, tmp_path / 'out')[1]
    text = path.read_text()
    assert ('        PotentialSpline[kcal/mol]  4  3\n'
            '          0.00 30.00 60.00 90.00\n'
            '    0.0000   1.5580   3.2660   1.6201\n') in text
    assert '    Atom\n      Mass[amu]  1.00782503223\n' in text
    assert 'Fragment H density\n' in text
    assert 'Fragment A\n' in text
    assert 'TSTLevel EJ\n' in text
    again = _reread(path, tmp_path / 'again')
    assert again.items['FakeW-A+H'].h_rotors[0].spline_angles == \
        [0.0, 30.0, 60.0, 90.0]
    assert again.items['FakeW-A+H'].h_rotors[1].spline_angles is None
    assert again.items['H'].is_atom is True
    assert again.items['H'].atom_mass == 1.00782503223
    assert again.items['A+H'].fragment_density == [False, True]
    assert again.items['A+H=FakeW-A+H'].tst_level == 'EJ'
    assert len(again.items['A+H=FakeW-A+H'].h_rotors) == 1


# ---------------------------------------------------------------------------
# W4: AutomechKinWriter payload per PES
# ---------------------------------------------------------------------------
def test_akw_payload_per_pes(tmp_path) -> None:
    """Slot k: own energy frame, LJ pair [collider, x_k], own masses,
    ModelEnergyLimit and WellReductionThreshold, SOP-wide ExponentCutoff /
    EnergyStepOverTemperature, per-file keys only where present; density,
    Atom, spline and PST rotors restored; the payload is a literal."""
    sop, _, reader = read(tmp_path, *_rich_pair())
    assert_clean(reader)
    p0 = AutomechKinWriter(sop=sop, pes_id=0)._build_payload()
    p1 = AutomechKinWriter(sop=sop, pes_id=1)._build_payload()

    assert p0['epsilons'] == [7.95, 206.15]
    assert p1['epsilons'] == [7.95, 300.0]
    assert p0['sigmas'] == [2.715, 4.71] and p1['sigmas'] == [2.715, 5.0]
    assert p0['lj_masses'] == [4.0, 77.0]
    assert p1['lj_masses'] == [4.0, 109.0]
    assert p0['model_ene_limit'] == 400.0
    assert p1['model_ene_limit'] == pytest.approx(800.0)
    for pay in (p0, p1):
        assert pay['edown_cutoff'] == 20.0
        assert pay['ene_stepover_temp'] == 0.2
    assert p0['well_red_thresh'] == 12.0 and p1['well_red_thresh'] == 14.0
    assert p0['well_extension'] == 0.5 and 'well_extension' not in p1
    assert p0['ped_species'] == ['A+H=FakeW-A+H'] and 'ped_species' not in p1
    assert p0['micro_ener'] == [0.0, 200.0, 1.0] and 'micro_ener' not in p1

    zero = {w['label']: w['zero_ene'] for w in p1['wells']}
    assert zero == {'FakeW-A+H': pytest.approx(0.61), 'UB': 2.0}
    assert p1['bimols'][0]['ground_ene'] == pytest.approx(1.61)
    assert p1['barriers'][0]['zero_ene'] == pytest.approx(1.61)
    assert {w['label']: w['zero_ene'] for w in p0['wells']} == {
        'FakeW-A+H': -1.0, 'UA': -3.0}

    bim = p0['bimols'][0]
    assert bim['frag2_density'] is True and 'frag1_density' not in bim
    assert bim['frag2']['mass'] == 1.00782503223
    assert len(bim['frag2']['geo']) == 1
    bar = p0['barriers'][0]
    assert bar['kind'] == 'phasespace' and bar['tst_level'] == 'ej'
    assert len(bar['hind_rotors']) == 1
    spline, plain = next(w for w in p0['wells']
                         if w['label'] == 'FakeW-A+H')['hind_rotors']
    assert spline['potential_form'] == 'spline'
    assert [a for a, _ in spline['potential']] == [0.0, 30.0, 60.0, 90.0]
    assert [e for _, e in spline['potential']] == pytest.approx(
        [0.0, 1.558, 3.266, 1.6201])
    assert 'potential_form' not in plain
    assert ast.literal_eval(repr(p1)) == p1

    sop.update('__epsilon2', 333.0)
    assert AutomechKinWriter(sop=sop, pes_id=0)._build_payload() == p0
    assert AutomechKinWriter(sop=sop, pes_id=1)._build_payload()[
        'epsilons'] == [7.95, 333.0]


def test_akw_payload_fallbacks(tmp_path, monkeypatch, caplog) -> None:
    """lj_masses: own pair -> SOP.masses -> N2 + heaviest well; no file
    data: SOP.model_ene_limit and SOP.well_reduction_threshold (first
    file's values); no ExponentCutoff: 15.0; absent optional keys (the
    PES's own WellReductionThreshold included) are omitted; an incomplete
    MicroEner set is dropped with one warning; a too-short LJ list for the
    PES raises."""
    monkeypatch.setattr(automech_kin, '_warn_once', set())
    sop, _, reader = read(tmp_path, *_rich_pair())
    assert_clean(reader)
    sop.pes_file_data[1].masses = []
    assert AutomechKinWriter(sop=sop, pes_id=1)._lj_masses([]) == [4.0, 77.0]
    sop.masses = []
    heavy = AutomechKinWriter(sop=sop, pes_id=1)._lj_masses(sop.wells)
    assert heavy[0] == 28.0134 and heavy[1] > 20.0

    files = sop.pes_file_data
    sop.pes_file_data = {}
    no_file = AutomechKinWriter(sop=sop, pes_id=1)._build_payload()
    assert no_file['model_ene_limit'] == 400.0
    assert no_file['well_red_thresh'] == 12.0
    sop.pes_file_data = files

    sop.exp_cutoff = None
    sop.ene_step_over_temp = None
    sop.pes_file_data[1].well_reduction_threshold = None
    pay = AutomechKinWriter(sop=sop, pes_id=1)._build_payload()
    assert pay['edown_cutoff'] == 15.0
    assert 'ene_stepover_temp' not in pay and 'well_red_thresh' not in pay

    sop.pes_file_data[1].micro_ener = (None, 150.0, None)
    with caplog.at_level(logging.WARNING, logger=automech_kin.__name__):
        pay = AutomechKinWriter(sop=sop, pes_id=1)._build_payload()
        AutomechKinWriter(sop=sop, pes_id=1)._build_payload()
    assert 'micro_ener' not in pay
    micro_warnings = [r.getMessage() for r in caplog.records
                      if 'MicroEnerMin/MicroEnerMax/MicroEnerStep'
                      in r.getMessage()]
    assert len(micro_warnings) == 1, micro_warnings
    assert 'PES 1' in micro_warnings[0]

    sop.epsilons = sop.epsilons[:2]
    with pytest.raises(ValueError, match='no value for PES 1'):
        AutomechKinWriter(sop=sop, pes_id=1)._build_payload()


def test_akw_no_lj_lines_gives_no_energy_transfer(tmp_path,
                                                  monkeypatch) -> None:
    """Inputs without Epsilons / Sigmas: empty pairs, and the driver writes
    no energy-transfer block."""
    sop, _, reader = read(tmp_path, mess_file(well('W'), eps=None,
                                              sig=None))
    assert_clean(reader)
    mod, _ = _driver(tmp_path, monkeypatch, sop, 0)
    assert mod.PES_PAYLOAD['epsilons'] == [] == mod.PES_PAYLOAD['sigmas']
    assert mod._energy_transfer_str() is None


# ---------------------------------------------------------------------------
# W5: emitted driver hands per-PES values to mess_io
# ---------------------------------------------------------------------------
def test_akw_driver_hands_per_pes_values_to_mess_io(tmp_path,
                                                    monkeypatch) -> None:
    """Stubbed mess_io: density flag, Atom mass, phasespace TSTLevel and
    rotor, spline and fourier rotors, exponent cutoff 20, the PES's LJ pair
    and masses, and the optional header kwargs."""
    sop, _, reader = read(tmp_path, *_rich_pair())
    assert_clean(reader)
    mod, rec = _driver(tmp_path, monkeypatch, sop, 1)
    mod._rxn_chan_str()
    (bim_kw,) = rec.kwargs('bimolecular')
    assert bim_kw['calc_spc2_density'] is True
    assert 'calc_spc1_density' not in bim_kw
    assert rec.last('atom')['mass'] == 1.00782503223
    assert rec.last('core_phasespace')['tstlvl'] == 'ej'
    forms = [kw['potential_form'] for kw in rec.kwargs('rotor_hindered')]
    assert sorted(forms) == ['fourier', 'fourier', 'spline']

    mod._energy_transfer_str()
    assert rec.last('energy_down')['exp_cutoff'] == 20.0
    coll = rec.last('collision_frequency')
    assert coll['eps1'] == pytest.approx(7.95 / EH2WAVEN)
    assert coll['eps2'] == pytest.approx(300.0 / EH2WAVEN)
    assert (coll['mass1'], coll['mass2']) == (4.0, 109.0)

    mod, rec = _driver(tmp_path, monkeypatch, sop, 0)
    mod._globkey_str('G0001P00.out', mod.PES_PAYLOAD.get('well_extension'))
    kwargs = rec.last('global_rates_input_v1')
    assert kwargs['well_extension'] == 0.5
    assert kwargs['ene_stepover_temp'] == 0.2
    assert kwargs['well_reduction_thresh'] == 12.0
    assert kwargs['model_ene_limit'] == 400.0
    assert kwargs['ped_spc_lst'] == ['A+H=FakeW-A+H']
    assert kwargs['micro_out_params'] == (0.0, 200.0, 1.0)


def test_akw_driver_all_header_keys_absent(tmp_path, monkeypatch) -> None:
    """A file without header keys: the kwargs are exactly the four pinned
    ones (new keys omitted, never None)."""
    sop, _, reader = read(tmp_path, mess_file(well('W')))
    assert_clean(reader)
    mod, rec = _driver(tmp_path, monkeypatch, sop, 0)
    for key in ('ene_stepover_temp', 'well_red_thresh', 'well_extension',
                'ped_species', 'micro_ener', 'hot_energies'):
        assert key not in mod.PES_PAYLOAD, key
    mod._globkey_str('G0001P00.out', None)
    assert set(rec.last('global_rates_input_v1')) == {
        'temperatures', 'pressures', 'well_extension', 'ktp_outname'}


class _FakeMessRun:
    """``subprocess.run`` double writing ``<base>.out`` per invocation."""

    def __init__(self, out: Path, outputs: list[str]) -> None:
        self.out = out
        self.outputs = list(outputs)

    def __call__(self, cmd, check=False, **kwargs):
        self.out.write_text(self.outputs.pop(0))
        return types.SimpleNamespace(returncode=0)


_LUMPED = ('TemperatureList[K] 500 600\nWellExtension 0.5000\n'
           'WellExtension\nModel\nEnd\n')


@pytest.mark.parametrize('pes_id, kept', [(0, False), (1, True)])
def test_akw_driver_well_extension_survives_pass_two(
        tmp_path, monkeypatch, pes_id, kept) -> None:
    """Pass 1 forwards the PES's WellExtension value; in pass 2 the bare
    WellExtension line mess_io inserts is dropped only when the PES has a
    value (PES 0), so its value stays the last one; PES 1 keeps mess_io's
    input unchanged."""
    sop, _, reader = read(tmp_path, *_rich_pair())
    assert_clean(reader)
    mod, rec = _driver(tmp_path, monkeypatch, sop, pes_id)
    run_dir = _mkdir(tmp_path / 'run')
    base = f'G0001P{pes_id:02d}'
    monkeypatch.setattr(mod.subprocess, 'run', _FakeMessRun(
        run_dir / f'{base}.out', [_MERGING_OUT, 'PASS2']))
    monkeypatch.setattr(mod, 'well_lumped_input_file',
                        lambda *args: _LUMPED)
    monkeypatch.chdir(run_dir)
    mod.main()
    first = rec.kwargs('global_rates_input_v1')[0]
    assert first['well_extension'] == (0.5 if pes_id == 0 else None)
    final = (run_dir / f'{base}.inp').read_text()
    assert ('WellExtension\n' in final) is kept
    ext = [ln for ln in final.splitlines() if ln.startswith('WellExtension')]
    assert ext[-1 if not kept else 0] == 'WellExtension 0.5000'
    assert (run_dir / f'{base}.out').read_text() == 'PASS2'


# ---------------------------------------------------------------------------
# W5b: warnings for keys mess_io hard-codes
# ---------------------------------------------------------------------------
_HARDCODED = ['AtomDistanceMin[angstrom] 1.0\n', 'WellCutoff 15\n',
              'ReductionMethod projection\n',
              'GroundEnergyShiftMax[kcal/mol] 5\n', 'FloatType dd\n']
_MESS_IO_SAME = ['AtomDistanceMin[bohr] 1.3\n', 'WellCutoff 10\n',
                 'ReductionMethod Diagonalization\n',
                 'GroundEnergyShiftMax[kcal/mol] 10\n', 'FloatType double\n']


def _akw_warnings(tmp_path: Path, monkeypatch, caplog,
                  header: list[str]) -> list[str]:
    monkeypatch.setattr(automech_kin, '_warn_once', set())
    sop, _, reader = read(tmp_path, mess_file(well('W'), header=header))
    assert reader._trigger_stop is False
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=automech_kin.__name__):
        AutomechKinWriter(sop=sop, pes_id=0)._build_payload()
        AutomechKinWriter(sop=sop, pes_id=0)._build_payload()
    return [r.getMessage() for r in caplog.records
            if r.name == automech_kin.__name__]


def test_akw_warns_on_mess_io_hard_coded_keys(tmp_path, monkeypatch,
                                              caplog) -> None:
    """One warning per key (key, value, mess_io's value), once per process;
    the per-PES WellCutoff warning names its PES; none when the value
    equals mess_io's (bohr converted, words case-folded) or the key is
    absent; never the word 'Different'. Two files with WellCutoff 10 and
    20: one warning, for PES 1 only."""
    msgs = _akw_warnings(_mkdir(tmp_path / 'set'), monkeypatch, caplog,
                         _HARDCODED)
    assert len(msgs) == 5, msgs
    for key, value, mess_io_value in (
            ('AtomDistanceMin', '1.0', '0.68793'), ('WellCutoff', '15', '10'),
            ('ReductionMethod', 'projection', 'diagonalization'),
            ('GroundEnergyShiftMax', '5', '10'), ('FloatType', 'dd',
                                                  'double')):
        (hit,) = [m for m in msgs if m.startswith(key)]
        assert value in hit and f'mess_io writes {key} {mess_io_value}' in hit
    assert not any('Different' in m for m in msgs)
    (cutoff,) = [m for m in msgs if m.startswith('WellCutoff')]
    assert 'MESS input of PES 0' in cutoff

    assert _akw_warnings(_mkdir(tmp_path / 'same'), monkeypatch, caplog,
                         _MESS_IO_SAME) == []
    assert _akw_warnings(_mkdir(tmp_path / 'absent'), monkeypatch, caplog,
                         []) == []

    monkeypatch.setattr(automech_kin, '_warn_once', set())
    sop, _, reader = read(_mkdir(tmp_path / 'two'),
                          mess_file(well('WA'), header=['WellCutoff 10\n']),
                          mess_file(well('WB'), header=['WellCutoff 20\n']))
    assert_clean(reader)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=automech_kin.__name__):
        for pes_id in (0, 1, 0, 1):
            AutomechKinWriter(sop=sop, pes_id=pes_id)._build_payload()
    msgs = [r.getMessage() for r in caplog.records
            if r.name == automech_kin.__name__]
    assert len(msgs) == 1, msgs
    assert msgs[0].startswith('WellCutoff 20')
    assert 'MESS input of PES 1' in msgs[0]


# ---------------------------------------------------------------------------
# W5c: HotEnergies move with their well, in the file's own frame
# ---------------------------------------------------------------------------
def _hot_pair() -> tuple[list[str], list[str]]:
    """A: S 0.0, UA -3; B (+1.61): S 1.61, HW -10 and the block
    ``HW -10:0.5:40`` / ``S 5.0``."""
    a = mess_file(well('S', 0.0), well('UA', -3.0))
    b = mess_file(well('S', 1.61), well('HW', -10.0), header=[
        'HotEnergies[kcal/mol] 2\n', 'HW -10:0.5:40\n', 'S 5.0\n'])
    return a, b


def test_hot_energies_shift_with_well_both_writers(tmp_path,
                                                   monkeypatch) -> None:
    """Unperturbed: slot 1 writes the block as read (no energy offset),
    slot 0 none. After HW dE +2 and S dE -1: slot 1 re-reads HW
    (-8, 0.5, 42) and S (4,), the AutomechKinWriter payload and the
    driver's ``hot_enes_dct`` (tuples) hold the same values; in both
    writers every hot energy minus its written well ZeroEnergy equals the
    value read minus the well energy of the file."""
    a, b = _hot_pair()
    sop, tpls, reader = read(tmp_path, a, b)
    assert_clean(reader)
    assert sop.pes_file_data[1].energy_offset == pytest.approx(1.61)
    read_gap = {'HW': -10.0 - -10.0, 'S': 5.0 - 1.61}

    p0, p1 = _write_slots(sop, tpls, tmp_path / 'raw')
    assert 'HotEnergies' not in p0.read_text()
    assert _reread(p1, tmp_path / 'raw1').pes_file_data[0].hot_energies == {
        'HW': (-10.0, 0.5, 40.0), 'S': (5.0,)}
    assert 'hot_energies' not in AutomechKinWriter(
        sop=sop, pes_id=0)._build_payload()

    sop.update('HW__we', sop.items['HW'].energy + 2.0)
    sop.update('S__we', sop.items['S'].energy - 1.0)
    expected = {'HW': (-8.0, 0.5, 42.0), 'S': (4.0,)}
    assert sop.shifted_hot_energies(1) == pytest.approx(expected)
    assert sop.shifted_hot_energies(0) is None

    p0, p1 = _write_slots(sop, tpls, tmp_path / 'moved')
    assert 'HotEnergies' not in p0.read_text()
    again = _reread(p1, tmp_path / 'moved1')
    hot = again.pes_file_data[0].hot_energies
    assert set(hot) == set(expected)
    for name, values in expected.items():
        assert hot[name] == pytest.approx(values), name
        assert hot[name][0] - again.items[name].energy == \
            pytest.approx(read_gap[name]), name

    payload = AutomechKinWriter(sop=sop, pes_id=1)._build_payload()
    assert payload['hot_energies'] == {'HW': pytest.approx([-8.0, 0.5, 42.0]),
                                       'S': pytest.approx([4.0])}
    zero = {w['label']: w['zero_ene'] for w in payload['wells']}
    for name, values in payload['hot_energies'].items():
        assert values[0] - zero[name] == pytest.approx(read_gap[name]), name
    assert ast.literal_eval(repr(payload)) == payload

    mod, rec = _driver(tmp_path, monkeypatch, sop, 1)
    mod._globkey_str('G0001P01.out', None)
    hot_kw = rec.last('global_rates_input_v1')['hot_enes_dct']
    assert all(isinstance(v, tuple) for v in hot_kw.values())
    assert hot_kw == {'HW': pytest.approx((-8.0, 0.5, 42.0)),
                      'S': pytest.approx((4.0,))}
    mod, rec = _driver(tmp_path, monkeypatch, sop, 0)
    mod._globkey_str('G0001P00.out', None)
    assert 'hot_enes_dct' not in rec.last('global_rates_input_v1')


def test_global_key_from_one_file_reaches_every_pes(tmp_path) -> None:
    """EnergyStepOverTemperature in file A only: no stop, both payloads
    carry 0.2 and both MessWriter slots write the line."""
    a = mess_file(well('WA'), header=['EnergyStepOverTemperature .2\n'])
    b = mess_file(well('WB'))
    sop, tpls, reader = read(tmp_path, a, b)
    assert_clean(reader)
    for pes_id in (0, 1):
        assert AutomechKinWriter(sop=sop, pes_id=pes_id)._build_payload()[
            'ene_stepover_temp'] == 0.2
    for path in _write_slots(sop, tpls, tmp_path / 'out'):
        assert _line(path, 'EnergyStepOverTemperature') == \
            'EnergyStepOverTemperature .2'


# ---------------------------------------------------------------------------
# W6: real mess_io strings (automech extra)
# ---------------------------------------------------------------------------
def test_akw_real_mess_io_strings(tmp_path, monkeypatch) -> None:
    """With mess_io installed, the emitted driver of slot 0 renders the
    spline rotor, the density flag, TSTLevel EJ, the Atom, its PEDSpecies,
    WellExtension 0.5, EnergyStepOverTemperature and ExponentCutoff 20."""
    import_or_skip('automech', 'mess_io.writer')
    import importlib.util
    sop, _, reader = read(tmp_path, *_rich_pair())
    assert_clean(reader)
    AutomechKinWriter(sop=sop, pes_id=0).write(loc=str(tmp_path),
                                               filename='G0001P00.py')
    spec = importlib.util.spec_from_file_location(
        'real_mess_io_driver', tmp_path / 'G0001P00.py')
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    chan = mod._rxn_chan_str()
    glob = mod._globkey_str('G0001P00.out', 0.5)
    etrans = mod._energy_transfer_str()
    assert 'PotentialSpline[kcal/mol]' in chan
    assert re.search(r'Fragment\s+H\s+density', chan), chan
    assert 'TSTLevel EJ' in chan
    assert re.search(r'^\s*Atom\s*$', chan, re.M)
    assert re.search(r'PEDSpecies\s+A\+H=FakeW-A\+H', glob)
    assert re.search(r'PEDOutput\s+G0001P00_ped\.out', glob)
    assert re.search(r'MicroRateOutput\s+G0001P00_ke\.out', glob)
    assert re.search(r'WellExtension\s+0\.5', glob)
    assert re.search(r'EnergyStepOverTemperature\s+0\.20', glob)
    assert re.search(r'ExponentCutoff\s+20\.0', etrans)
    assert 'PressureList[bar]' in glob


# ---------------------------------------------------------------------------
# W7: back-compatibility goldens
# ---------------------------------------------------------------------------
def _read_inputs(root: Path, inputs: list[str], log: Path) -> tuple[Any, Any]:
    settings = {
        'init_loc': str(root), 'mess_inputs': inputs, 'n_exp': 1,
        'score_sp': [], 'freq_mode': FreqMode.BATCH,
        'rc_temp': [550.0, 600.0], 'rc_pres': [0.1, 1.0],
        'pres_unit': 'bar', 'force_new_molecules': True}
    reader = MessInputReader(settings=settings, mechanism_species=[],
                             klog=KMOLogger(filename=str(log)),
                             postprocess=False)
    sop, tpls = reader.read()
    assert reader._trigger_stop is False
    return sop, tpls


def _payload_json(sop: Any, pes_id: int) -> dict[str, Any]:
    payload = AutomechKinWriter(sop=sop, pes_id=pes_id)._build_payload()
    return json.loads(json.dumps(payload, sort_keys=True))


def _golden_with_dme_delta(stem: str) -> str:
    """HEAD's DME file with the documented changes applied: per-file
    MicroRateOutput name, per-PES __epsilon2 / __sigma2 header lines, the
    duplicated CH2OCH2OOH rotor names gone."""
    lines = (GOLDEN / f'{stem}.inp').read_text().splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        if re.match(r'!CH2OCH2OOH__hrs[4-7]: ', line):
            continue
        if line == 'MicroRateOutput micro.out\n':
            line = f'MicroRateOutput {stem}_ke.out\n'
        out.append(line)
        if line.startswith('!__epsilon1: '):
            out.append('!__epsilon2: 206.15\n')
        if line.startswith('!__sigma1: '):
            out.append('!__sigma2: 4.71\n')
    return ''.join(out)


def test_single_file_and_dme_outputs_match_goldens(tmp_path) -> None:
    """Ethyl: MessWriter output byte-identical, payload = HEAD + only
    ene_stepover_temp 0.2. DME pair: MessWriter = HEAD + the listed header
    and MicroRateOutput changes; payload = HEAD except new keys
    (ene_stepover_temp 0.2, micro_ener [0, 200, 1]), the PST barriers'
    rotors, the duplicated CH2OCH2OOH rotors removed and slot 1's own
    Masses pair [4.0, 109.0]."""
    sop, tpls = _read_inputs(REPO / 'example',
                             ['mess_input_ethyl_oxidation.inp'],
                             tmp_path / 'ethyl.log')
    (path,) = _write_slots(sop, tpls, tmp_path / 'ethyl', ['ethyl_P00'])
    assert path.read_bytes() == (GOLDEN / 'ethyl_P00.inp').read_bytes()
    new = _payload_json(sop, 0)
    assert new.pop('ene_stepover_temp') == 0.2
    assert new == json.loads(
        (GOLDEN / 'akw_payload_ethyl_P00.json').read_text())

    dme = REPO / 'tests' / 'parse_pes' / 'dme'
    sop, tpls = _read_inputs(dme, ['mess_roo_L3.inp', 'mess_ooqooh_L2.inp'],
                             tmp_path / 'dme.log')
    stems = ['dme_roo_L3_P00', 'dme_ooqooh_L2_P01']
    paths = _write_slots(sop, tpls, tmp_path / 'dme', stems)
    for stem, path in zip(stems, paths):
        assert path.read_text() == _golden_with_dme_delta(stem), stem

    pst_rotors = {0: [2], 1: [4, 3, 3, 4]}
    for slot in (0, 1):
        new = _payload_json(sop, slot)
        old = json.loads(
            (GOLDEN / f'akw_payload_dme_P{slot:02d}.json').read_text())
        assert new.pop('ene_stepover_temp') == 0.2
        assert new.pop('micro_ener') == [0.0, 200.0, 1.0]
        counts = []
        for bar_new, bar_old in zip(new['barriers'], old['barriers']):
            if 'hind_rotors' not in bar_old:
                assert bar_new['kind'] == 'phasespace'
                counts.append(len(bar_new.pop('hind_rotors')))
        assert counts == pst_rotors[slot]
        if slot == 0:
            old_rot = old['wells'][1]['hind_rotors']
            new_rot = new['wells'][1]['hind_rotors']
        else:
            old_rot = old['bimols'][3]['frag1']['hind_rotors']
            new_rot = new['bimols'][3]['frag1']['hind_rotors']
        assert len(old_rot) == 8 and old_rot[4:] == old_rot[:4] == new_rot
        old_rot[4:] = []
        if slot == 1:
            assert old['lj_masses'] == [4.0, 77.0]
            assert new['lj_masses'] == [4.0, 109.0]
            old['lj_masses'] = new['lj_masses']
        assert new == old, slot


# ---------------------------------------------------------------------------
# W8: the golden folder holds data only
# ---------------------------------------------------------------------------
def test_golden_folder_hygiene() -> None:
    """No Python file (nothing pytest could collect or the source scans
    could read) and no forbidden pattern in the goldens."""
    files = sorted(p for p in GOLDEN.rglob('*') if p.is_file())
    assert {p.name for p in files} == {
        'ethyl_P00.inp', 'dme_roo_L3_P00.inp', 'dme_ooqooh_L2_P01.inp',
        'akw_payload_ethyl_P00.json', 'akw_payload_dme_P00.json',
        'akw_payload_dme_P01.json'}
    for path in files:
        assert path.suffix != '.py', path
        assert not path.name.startswith('test_'), path
        assert not path.stem.endswith('_test'), path
        text = path.read_text()
        for pattern in FORBIDDEN_SOURCE_PATTERNS:
            assert not pattern.search(text), (path, pattern.pattern)
