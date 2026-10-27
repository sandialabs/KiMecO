"""CI-safe tests: three linked AutoMech MESS inputs read into one SOP.

Fixture ``tests/unit/data/c4h8_h_group/``: the "H group" of the C4H8 prompt
system, three AutoMech MESS inputs with structure-based labels (one PES
each). ``H_C4H71-3`` is the hub: it shares ``CH2CHCH2CH3+H``, its fake well
and its PST barrier with ``H_C4H71-4`` (same energy zero), and
``CH2CHCHCH3+H2``, its fake well and its PST barrier with ``2-H_C4H71-3``
(whose energies are 1.61 kcal/mol higher). Each file holds AutoMech fake
wells (``FakeW-<bimol>``), ``Atom`` H, ``density`` fragments,
``PotentialSpline`` rotors, ``TSTLevel EJ``, ``PEDSpecies``,
``MicroEner*`` and the target-first ``Epsilons`` / ``Sigmas`` / ``Masses``
lines (173.667 / 4.364 twice, 56.063 39.962).

Trim applied to the AutoMech files (same rule for every file, so the blocks
shared between files stay byte-identical): full-line ``!`` comments removed,
``TemperatureList`` / ``PressureList`` cut to their first two values.
Everything else, rotor geometries included, is as AutoMech wrote it.
No MESS binary is needed.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from kimeco.enums import FreqMode
from kimeco.readers.mess_input import MessInputReader
from kimeco.writers.automech_kin import AutomechKinWriter
from kimeco.writers.mess import MessWriter
from tests.unit.test_mess_multi_pes_read_ci import SpyLog

DATA = Path(__file__).resolve().parent / 'data' / 'c4h8_h_group'
H3, H4, H2B = 'H_C4H71-3.inp', 'H_C4H71-4.inp', '2-H_C4H71-3.inp'
SPECIES = ['CH2CHCH2CH3', 'CH3CHCHCH3', 'CH2CHCHCH3', 'CH2CH2CHCH2', 'H',
           'H2']
SHARED = {  # item -> files (names) holding it
    'FakeW-CH2CHCH2CH3+H': (H3, H4),
    'CH2CHCH2CH3+H': (H3, H4),
    'CH2CHCH2CH3+H=FakeW-CH2CHCH2CH3+H': (H3, H4),
    'FakeW-CH2CHCHCH3+H2': (H3, H2B),
    'CH2CHCHCH3+H2': (H3, H2B),
    'CH2CHCHCH3+H2=FakeW-CH2CHCHCH3+H2': (H3, H2B),
}
SADDLES = {
    'FakeW-CH2CHCH2CH3+H=FakeW-CH2CHCHCH3+H2': H3,
    'FakeW-CH2CHCH2CH3+H=FakeW-CH2CH2CHCH2+H2': H4,
    'FakeW-CH3CHCHCH3+H=FakeW-CH2CHCHCH3+H2': H2B,
}
PED = {H3: ['CH2CHCH2CH3+H=CH2CHCHCH3+H2'],
       H4: ['CH2CHCH2CH3+H=CH2CH2CHCH2+H2'],
       H2B: ['CH3CHCHCH3+H=CH2CHCHCH3+H2']}
ORDERS = [(H3, H4, H2B), (H4, H2B, H3), (H2B, H3, H4)]


def _read(files: list[str] | tuple[str, ...], root: Path = DATA
          ) -> tuple[Any, list[Any], MessInputReader]:
    settings = {
        'init_loc': str(root), 'mess_inputs': list(files), 'n_exp': 1,
        'score_sp': [], 'freq_mode': FreqMode.BATCH,
        'rc_temp': [500.0, 550.0], 'rc_pres': [0.03, 0.1],
        'pres_unit': 'atm', 'force_new_molecules': False}
    reader = MessInputReader(settings=settings, mechanism_species=SPECIES,
                             klog=SpyLog(),  # type: ignore[arg-type]
                             postprocess=False)
    sop, tpls = reader.read()
    return sop, tpls, reader


def _assert_clean(reader: MessInputReader) -> None:
    log = reader.klog
    assert reader._trigger_stop is False, (log.warnings, log.errors)
    assert log.warnings == [] and log.errors == []  # type: ignore[attr-defined]


def _energies(sop: Any) -> dict[str, float]:
    """Energies of the top-level items (not the bimolecular fragments)."""
    return {item.name: float(item.energy)
            for item in sop.iter_top_level_items()}


# ---------------------------------------------------------------------------
# F1: the three files load into one SOP
# ---------------------------------------------------------------------------
def test_h_group_loads_into_one_sop() -> None:
    """No stop; 3 templates and PES ids; shared items carry the ids of
    their files; saddles one id; rotors as in each file alone; density
    flags; one LJ second value per file; per-PES masses and keys."""
    files = (H3, H4, H2B)
    sop, tpls, reader = _read(files)
    _assert_clean(reader)
    assert len(tpls) == 3 and sop.pes_ids == [0, 1, 2]
    assert [t.pes_id for t in tpls] == [0, 1, 2]
    for name, holders in SHARED.items():
        assert sop.items[name].pes_ids == sorted(
            files.index(f) for f in holders), name
    for name, holder in SADDLES.items():
        assert sop.items[name].pes_ids == [files.index(holder)], name
    fake = [w.name for w in sop.wells if w.name.startswith('FakeW-')]
    assert len(fake) == 4

    for name in files:
        alone, _, alone_reader = _read([name])
        _assert_clean(alone_reader)
        for item in alone.iter_top_level_items():
            assert len(getattr(sop.items[item.name], 'h_rotors', [])) == \
                len(getattr(item, 'h_rotors', [])), (name, item.name)

    assert sop.items['CH2CHCHCH3+H2'].fragment_density == [True, True]
    assert sop.items['CH2CH2CHCH2+H2'].fragment_density == [True, True]
    assert sop.items['CH2CHCH2CH3+H'].fragment_density == [False, False]
    assert sop.items['CH3CHCHCH3+H'].fragment_density == [False, False]
    assert sop.items['H'].is_atom is True

    assert sop.epsilons == [173.667] * 4
    assert sop.sigmas == [4.364] * 4
    lj = [n for n in sop.parameters_names
          if n.startswith(('__epsilon', '__sigma'))]
    assert lj == [f'__epsilon{k}' for k in range(4)] + \
        [f'__sigma{k}' for k in range(4)]
    for fid, name in enumerate(files):
        data = sop.pes_file_data[fid]
        assert data.masses == [56.063, 39.962]
        assert data.model_ene_limit == 800.0
        assert data.atom_distance_min == (0.68793, 'angstrom')
        assert data.ped_species == PED[name]
        assert data.micro_ener == (0.1, 320.0, 0.1)
    assert sop.calculation_method == 'direct'
    assert sop.ene_step_over_temp == 0.2
    assert sop.exp_cutoff == 15.0


# ---------------------------------------------------------------------------
# F2: energy alignment does not depend on the file order
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('order, offsets', [
    (ORDERS[0], [0.0, 0.0, 1.61]),
    (ORDERS[1], [0.0, 1.61, 0.0]),
    (ORDERS[2], [0.0, -1.61, -1.61]),
])
def test_h_group_alignment_order_independent(order, offsets) -> None:
    """Offsets per order (reference = first file); differences between item
    energies are the same in every order."""
    sop, _, reader = _read(order)
    _assert_clean(reader)
    got = [sop.pes_file_data[k].energy_offset for k in range(3)]
    assert got == pytest.approx(offsets)
    ref, _, _ = _read(ORDERS[0])
    if order == ORDERS[0]:
        assert sop.items['FakeW-CH3CHCHCH3+H'].energy == pytest.approx(-2.61)
    a, b = _energies(ref), _energies(sop)
    names = sorted(a)
    assert names == sorted(b)
    for x in names:
        assert (b[x] - b[names[0]]) == pytest.approx(a[x] - a[names[0]]), x


# ---------------------------------------------------------------------------
# F3: both writers give each file back
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('order', [ORDERS[0], ORDERS[2]])
def test_h_group_writers_reproduce_each_file(tmp_path, order) -> None:
    """MessWriter: slot k re-read alone has file k's raw energies, its own
    PEDSpecies and the LJ pair 173.6670 173.6670; AutomechKinWriter: the
    2-H slot in its own frame, its PED species and LJ pair, script
    compiles."""
    sop, tpls, reader = _read(order)
    _assert_clean(reader)
    out = tmp_path / 'out'
    out.mkdir()
    for k, (name, tpl) in enumerate(zip(order, tpls)):
        MessWriter(SOP=sop, tpl=tpl).write(loc=str(out),
                                           filename=f'G0001P{k:02d}.inp')
        written = out / f'G0001P{k:02d}.inp'
        text = written.read_text()
        # 7.4f pairs (the collider and this file's value), as before.
        assert 'Epsilons[1/cm]   173.6670  173.6670\n' in text
        assert 'Sigmas[angstrom]   4.3640  4.3640\n' in text
        assert f'PEDSpecies                             {PED[name][0]}' \
            in text
        assert f'PEDOutput G0001P{k:02d}_ped.out\n' in text

        check = tmp_path / f'check{k}'
        check.mkdir()
        shutil.copy(written, check / name)
        again, _, again_reader = _read([name], root=check)
        _assert_clean(again_reader)
        alone, _, _ = _read([name])
        assert _energies(again) == pytest.approx(_energies(alone)), name

    fid = order.index(H2B)
    payload = AutomechKinWriter(sop=sop, pes_id=fid)._build_payload()
    zero = {w['label']: w['zero_ene'] for w in payload['wells']}
    assert zero['FakeW-CH2CHCHCH3+H2'] == pytest.approx(-19.34)
    assert zero['FakeW-CH3CHCHCH3+H'] == pytest.approx(-1.0)
    bars = {b['label']: b['zero_ene'] for b in payload['barriers']}
    assert bars['FakeW-CH3CHCHCH3+H=FakeW-CH2CHCHCH3+H2'] == \
        pytest.approx(7.25)
    assert payload['ped_species'] == PED[H2B]
    assert payload['epsilons'] == [173.667, 173.667]
    assert payload['sigmas'] == [4.364, 4.364]
    assert payload['lj_masses'] == [56.063, 39.962]
    AutomechKinWriter(sop=sop, pes_id=fid).write(loc=str(tmp_path),
                                                 filename='G0001P02.py')
    compile((tmp_path / 'G0001P02.py').read_text(), 'G0001P02.py', 'exec')
