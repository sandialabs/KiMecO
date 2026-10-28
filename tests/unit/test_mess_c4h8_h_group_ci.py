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

``C4H7_hot.inp``: the hot C4H7 PES (wells ``CH2CHCHCH3`` -45.63 and
``CH2CH2CHCH2`` -28.82, bimoleculars ``CH2CHCHCH2+H`` 0.0 and
``CH2CH2+CH2CH`` 4.65, four Eckart barriers) with its ``HotEnergies`` block
(``CH2CHCHCH3 -45:1:250``, ``CH2CH2CHCH2 -28:1:230``). Derived once (scratch
script, not kept) from the structure-named copy of the C4H7 input of the
non-thermal C4H8 study (``C4H7_JC_renamed/wellcap_eigmax02/mess.inp``):

* header: same trim rule (``!ChemicalEigenvalueMin`` comment line dropped,
  grids cut to 500 550 K and 0.03 0.1 atm), every other line as written
  (``WellCutoff 20``, ``WellReductionThreshold 10.``, ``WellExtension``,
  ``ExtensionCorrection 0.4``, no ``ReductionMethod``);
* collision model harmonised with the H group (Factor 609.972, Power 0.521,
  ``Epsilons`` / ``Sigmas`` / ``Masses`` 173.667 / 4.364 twice, 56.063
  39.962; the original has an N2 bath);
* the two wells take the data of the H group's fragments of the same name
  (``RRHO`` up to the last rotor of ``Fragment CH2CHCHCH3`` in
  ``H_C4H71-3``, of ``Fragment CH2CH2CHCH2`` in ``H_C4H71-4``, verbatim),
  keeping their own ``WellExtensionCap`` (53., 40.) and ``ZeroEnergy``;
* bimoleculars and barriers verbatim, except the H atom mass
  (1.00782503223 instead of 1). No E-notation number is left.

The well of the hot PES and the fragment of the H group are then one item.
No MESS binary is needed (one test renders the real mess_io block and skips
without the ``automech`` extra).
"""
from __future__ import annotations

import importlib.util
import logging
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from kimeco.enums import FreqMode
from kimeco.parameters import SOP
from kimeco.readers.mess_input import MessInputReader
from kimeco.writers import automech_kin
from kimeco.writers.automech_kin import AutomechKinWriter
from kimeco.writers.mess import MessWriter
from tests.unit.test_installation_extras_ci import import_or_skip
from tests.unit.test_mess_multi_pes_read_ci import SpyLog
from tests.unit.test_mess_multi_pes_write_ci import _driver
from tests.unit.test_perturbator_boundary_coverage_ci import _scripted_pert

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
C4H7 = 'C4H7_hot.inp'
HOT_SPECIES = SPECIES + ['CH2CHCHCH2', 'CH2CH2', 'CH2CH']
HOT_WELLS = ('CH2CHCHCH3', 'CH2CH2CHCH2')
HOT = {'CH2CHCHCH3': (-45.0, 1.0, 250.0),
       'CH2CH2CHCH2': (-28.0, 1.0, 230.0)}
ORDERS4 = [(C4H7, H3, H4, H2B), (H3, H4, H2B, C4H7)]


def _read(files: list[str] | tuple[str, ...], root: Path = DATA,
          species: list[str] = SPECIES, prompt: bool = False
          ) -> tuple[Any, list[Any], MessInputReader]:
    settings: dict[str, Any] = {
        'init_loc': str(root), 'mess_inputs': list(files), 'n_exp': 1,
        'score_sp': [], 'freq_mode': FreqMode.BATCH,
        'rc_temp': [500.0, 550.0], 'rc_pres': [0.03, 0.1],
        'pres_unit': 'atm', 'force_new_molecules': False}
    if prompt:
        # Only in prompt mode: the other reads carry no key at all, which
        # pins the reader's .get default.
        settings['prompt_reactions'] = True
    reader = MessInputReader(settings=settings, mechanism_species=species,
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


# ---------------------------------------------------------------------------
# C1-C6: the hot C4H7 PES loaded with the H group
# ---------------------------------------------------------------------------
def _read4(order: tuple[str, ...], root: Path = DATA
           ) -> tuple[Any, list[Any], MessInputReader]:
    return _read(order, root=root, species=HOT_SPECIES)


def _hot_line(text: str, name: str) -> str:
    hits = [ln.strip() for ln in text.splitlines()
            if ln.split()[:1] == [name] and len(ln.split()) == 2]
    assert len(hits) == 1, (name, hits)
    return hits[0]


def test_c4h7_hot_fixture_reads_alone() -> None:
    """2 wells, 2 bimoleculars, 4 barriers; 1 and 2 rotors on the wells;
    the harmonised H mass and collision model; the hot energies as read;
    WellCutoff 20 and WellReductionThreshold 10 on its PES; no
    E-notation left in the fixture."""
    sop, tpls, reader = _read4((C4H7,))
    _assert_clean(reader)
    assert [w.name for w in sop.wells] == list(HOT_WELLS)
    assert [b.name for b in sop.bimolecular] == ['CH2CHCHCH2+H',
                                                 'CH2CH2+CH2CH']
    assert len(sop.barriers) == 4
    assert [len(sop.items[n].h_rotors) for n in HOT_WELLS] == [1, 2]
    assert sop.items['H'].atom_mass == 1.00782503223
    assert (sop.factor, sop.power) == (609.972, 0.521)
    assert sop.epsilons == [173.667] * 2 and sop.sigmas == [4.364] * 2
    data = sop.pes_file_data[0]
    assert data.masses == [56.063, 39.962]
    assert data.hot_energies == HOT
    assert data.well_cutoff == 20 and data.well_reduction_threshold == 10
    assert sop.reduction_method is None
    assert '{SOP.r_hot_energies_pes[0]}\n' in tpls[0]
    assert not re.search(r'\dE[-+]', (DATA / C4H7).read_text())


@pytest.mark.parametrize('order', ORDERS4, ids=['hot_first', 'hot_last'])
def test_four_files_load_with_shared_items(order) -> None:
    """No stop; offsets 0 for the hot PES (not linked by energies) and as
    for the H group; each hot well is one object, also the fragment of an
    abstraction product, listed once in SOP.wells with the hot PES id
    only; per-PES WellCutoff / WellReductionThreshold / HotEnergies;
    ReductionMethod from the H group for every PES; the abstraction
    energies equal the H group read alone."""
    sop, tpls, reader = _read4(order)
    _assert_clean(reader)
    hot = order.index(C4H7)
    h2b = order.index(H2B)
    assert len(tpls) == 4 and sop.pes_ids == [0, 1, 2, 3]
    offsets = [sop.pes_file_data[k].energy_offset for k in range(4)]
    assert offsets == pytest.approx(
        [1.61 if k == h2b else 0.0 for k in range(4)])

    products = {'CH2CHCHCH3': 'CH2CHCHCH3+H2',
                'CH2CH2CHCH2': 'CH2CH2CHCH2+H2'}
    for name, product in products.items():
        item = sop.items[name]
        assert item is sop.items[product].fragments[0], name
        assert sum(w is item for w in sop.wells) == 1, name
        assert item.pes_ids == [hot], name
    assert sop.items['H'].pes_ids == []
    assert [w.name for w in sop.wells_in(hot)] == list(HOT_WELLS)
    assert sop.species_names_in_pes(hot) == sorted(
        list(HOT_WELLS) + ['CH2CHCHCH2+H', 'CH2CH2+CH2CH'])
    for fid in range(4):
        if fid != hot:
            assert not set(HOT_WELLS) & set(sop.species_names_in_pes(fid))

    for fid in range(4):
        data = sop.pes_file_data[fid]
        if fid == hot:
            assert data.hot_energies == HOT
            assert (data.well_cutoff, data.well_reduction_threshold) == \
                (20.0, 10.0)
        else:
            assert data.hot_energies is None
            assert (data.well_cutoff, data.well_reduction_threshold) == \
                (10.0, None)
    assert sop.reduction_method == 'diagonalization'
    assert sop.epsilons == [173.667] * 5
    assert sop.parameters_names['CH2CHCHCH3__we'] == -45.63
    assert sop.parameters_names['CH2CH2CHCH2__we'] == -28.82

    group, _, _ = _read(ORDERS[0])
    for name, energy in _energies(group).items():
        assert sop.items[name].energy == pytest.approx(energy), name


def _write_all(sop: Any, tpls: list[Any], out: Path) -> list[Path]:
    out.mkdir()
    paths = []
    for k, tpl in enumerate(tpls):
        MessWriter(SOP=sop, tpl=tpl).write(loc=str(out),
                                           filename=f'G0001P{k:02d}.inp')
        paths.append(out / f'G0001P{k:02d}.inp')
    return paths


def _reread_as(path: Path, name: str, root: Path) -> Any:
    root.mkdir()
    shutil.copy(path, root / name)
    sop, _, reader = _read4((name,), root=root)
    _assert_clean(reader)
    return sop


@pytest.mark.parametrize('order', ORDERS4, ids=['hot_first', 'hot_last'])
def test_four_files_writers_follow_one_item(tmp_path, monkeypatch, caplog,
                                            order) -> None:
    """MessWriter: every slot re-read alone equals its file read alone; the
    hot slot gets one ReductionMethod line (before Model) and keeps its
    WellCutoff 20 and WellReductionThreshold lines, the H slots keep
    WellCutoff 10 and get no WellReductionThreshold. Restart with
    CH2CHCHCH3__we -44.13 (from_db_row): the hot energies of that well move
    by +1.5, the abstraction product CH2CHCHCH3+H2 by +1.5 with its
    fragment ZeroEnergy kept verbatim. AutomechKinWriter: only the hot PES
    gets the shifted hot_enes_dct and WellReductionThreshold 10, and only
    it warns about WellCutoff."""
    sop, tpls, reader = _read4(order)
    _assert_clean(reader)
    hot = order.index(C4H7)
    paths = _write_all(sop, tpls, tmp_path / 'out')
    for k, (name, path) in enumerate(zip(order, paths)):
        again = _reread_as(path, name, tmp_path / f'again{k}')
        alone, _, _ = _read4((name,))
        assert _energies(again) == pytest.approx(_energies(alone)), name
        assert again.pes_file_data[0].hot_energies == \
            alone.pes_file_data[0].hot_energies, name
        text = path.read_text()
        # Whitespace-normalised lines (the added ReductionMethod line keeps
        # the H group's column alignment)
        lines = [' '.join(ln.split()) for ln in text.splitlines()]
        if k == hot:
            assert lines.count('ReductionMethod diagonalization') == 1
            assert lines.index('ReductionMethod diagonalization') < \
                lines.index('Model')
            assert 'WellCutoff 20' in lines
            assert 'WellReductionThreshold 10.' in lines
            assert _hot_line(text, 'CH2CHCHCH3') == \
                'CH2CHCHCH3 -45.0:1.0:250.0'
        else:
            assert 'WellCutoff 10' in lines
            assert not any(ln.startswith('WellReductionThreshold')
                           for ln in lines)
            assert 'HotEnergies' not in text

    names = list(sop.parameters_names)
    row = list(sop.parameters_names.values())
    row[names.index('CH2CHCHCH3__we')] = -44.13
    restarted = SOP.from_db_row(sop, row)
    paths = _write_all(restarted, tpls, tmp_path / 'restart')
    again = _reread_as(paths[hot], C4H7, tmp_path / 'restart_hot')
    assert again.items['CH2CHCHCH3'].energy == pytest.approx(-44.13)
    hot_again = again.pes_file_data[0].hot_energies
    assert hot_again['CH2CHCHCH3'] == pytest.approx((-43.5, 1.0, 251.5))
    assert hot_again['CH2CH2CHCH2'] == HOT['CH2CH2CHCH2']
    fid_h3 = order.index(H3)
    h3_again = _reread_as(paths[fid_h3], H3, tmp_path / 'restart_h3')
    alone, _, _ = _read((H3,))
    assert h3_again.items['CH2CHCHCH3+H2'].energy == pytest.approx(
        alone.items['CH2CHCHCH3+H2'].energy + 1.5)
    assert h3_again.items['CH2CHCH2CH3+H'].energy == pytest.approx(
        alone.items['CH2CHCH2CH3+H'].energy)
    zero = '      ZeroEnergy[kcal/mol]    0.0\n'
    assert paths[fid_h3].read_text().count(zero) == \
        (DATA / H3).read_text().count(zero)

    monkeypatch.setattr(automech_kin, '_warn_once', set())
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=automech_kin.__name__):
        for fid in (0, 1, 2, 3, 0, 1, 2, 3):
            AutomechKinWriter(sop=restarted, pes_id=fid)._build_payload()
    msgs = [r.getMessage() for r in caplog.records
            if r.name == automech_kin.__name__]
    assert len(msgs) == 1, msgs
    assert msgs[0].startswith('WellCutoff 20')
    assert f'MESS input of PES {hot}' in msgs[0]

    for fid in range(4):
        mod, rec = _driver(tmp_path, monkeypatch, restarted, fid)
        mod._globkey_str(f'G0001P{fid:02d}.out', None)
        kwargs = rec.last('global_rates_input_v1')
        if fid == hot:
            assert kwargs['hot_enes_dct'] == {
                'CH2CHCHCH3': pytest.approx((-43.5, 1.0, 251.5)),
                'CH2CH2CHCH2': HOT['CH2CH2CHCH2']}
            assert all(isinstance(v, tuple)
                       for v in kwargs['hot_enes_dct'].values())
            assert kwargs['well_reduction_thresh'] == 10.0
        else:
            assert 'hot_enes_dct' not in kwargs, fid
            assert 'well_reduction_thresh' not in kwargs, fid


def test_four_files_real_mess_io_hot_block(tmp_path) -> None:
    """With mess_io installed, the emitted driver of the hot PES renders a
    HotEnergies block with both wells' ranges."""
    import_or_skip('automech', 'mess_io.writer')
    sop, _, reader = _read4(ORDERS4[1])
    _assert_clean(reader)
    hot = ORDERS4[1].index(C4H7)
    name = f'G0001P{hot:02d}.py'
    AutomechKinWriter(sop=sop, pes_id=hot).write(loc=str(tmp_path),
                                                 filename=name)
    spec = importlib.util.spec_from_file_location('real_hot_driver',
                                                  tmp_path / name)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    glob = mod._globkey_str(f'G0001P{hot:02d}.out', None)
    assert 'HotEnergies[kcal/mol]' in glob
    assert re.search(r'CH2CHCHCH3\s+-45\.0:1\.0:250\.0', glob), glob
    assert re.search(r'CH2CH2CHCH2\s+-28\.0:1\.0:230\.0', glob), glob


_UNHARMONISED = {
    'h_mass': (('Mass[amu]     1.00782503223', 'Mass[amu]     1'),
               ('Well H differs between', 'in: atom.')),
    'frequency': (('        214     287     505',
                   '        215     287     505'),
                  ('Well CH2CHCHCH3 differs between', 'in: frequencies.')),
    'factor': (('Factor[1/cm]                     609.972',
                'Factor[1/cm]                     100'),
               ('Different factor in',)),
}


@pytest.mark.parametrize('case', sorted(_UNHARMONISED))
def test_unharmonised_c4h7_copy_still_stops(tmp_path, case) -> None:
    """One harmonised value put back to the original's (H mass 1), one well
    frequency +1 cm-1, the original Factor: the existing stops, naming the
    hot file."""
    (old, new), needles = _UNHARMONISED[case]
    for name in (H3, H4, H2B):
        shutil.copy(DATA / name, tmp_path / name)
    text = (DATA / C4H7).read_text()
    assert text.count(old) == 1, old
    (tmp_path / C4H7).write_text(text.replace(old, new))
    _, _, reader = _read4(ORDERS4[1], root=tmp_path)
    assert reader._trigger_stop is True
    log: Any = reader.klog
    hits = [m for m in log.warnings + log.errors
            if all(n in m for n in needles)]
    assert len(hits) == 1, (needles, log.warnings, log.errors)
    assert str(tmp_path / C4H7) in hits[0]


def test_four_files_perturbation_draws_each_species_once() -> None:
    """A real Perturbator cycle on the four-file SOP (sub-steps spied):
    every well and fragment object goes through the energy step exactly
    once, CH2CHCHCH3 (hot well and abstraction fragment) and H (fragment
    of several bimoleculars) included."""
    sop, _, reader = _read4(ORDERS4[0])
    _assert_clean(reader)
    work = deepcopy(sop)
    pert, _ = _scripted_pert([], sop)
    seen: list[str] = []
    pert.perturb_energy = lambda item: seen.append(item.name)
    pert.perturb_vibrations = lambda well: None
    pert.perturb_hindered_rotors = lambda well: None
    pert.perturb_multi_rotors = lambda well: None
    pert.perturb_barrier = lambda bar: None
    pert.perturb(work)
    objects = {id(w): w.name for w in work.wells}
    for bim in work.bimolecular:
        objects.update((id(f), f.name) for f in bim.fragments)
    assert sorted(seen) == sorted(objects.values())
    assert seen.count('CH2CHCHCH3') == 1 and seen.count('H') == 1


# ---------------------------------------------------------------------------
# P1-P7: prompt mode, PEDSpecies products linked to HotEnergies wells
# ---------------------------------------------------------------------------
_H3_PED = 'CH2CHCH2CH3+H=CH2CHCHCH3+H2'
_H2B_PED = 'CH3CHCHCH3+H=CH2CHCHCH3+H2'
_MICRO = ('MicroEnerMin[kcal/mol]                 0.1\n',
          'MicroEnerMax[kcal/mol]                 320.0\n',
          'MicroEnerStep[kcal/mol]                0.1\n')


def _prompt_copy(tmp_path: Path, edits: dict[str, list[tuple[str, str]]],
                 files: tuple[str, ...] = (C4H7, H3, H4, H2B)) -> Path:
    """Copy ``files`` to ``tmp_path`` and apply text edits ({file: [(old,
    new)]}, each ``old`` found exactly once); the fixtures stay frozen."""
    for name in files:
        text = (DATA / name).read_text()
        for old, new in edits.get(name, []):
            assert text.count(old) == 1, (name, old)
            text = text.replace(old, new)
        (tmp_path / name).write_text(text)
    return tmp_path


def _messages(reader: MessInputReader) -> tuple[list[str], list[str]]:
    log: Any = reader.klog
    return log.warnings, log.errors


@pytest.mark.parametrize('order', ORDERS4, ids=['hot_first', 'hot_last'])
def test_prompt_four_files_link_cleanly(order) -> None:
    """Prompt mode, the H group with the hot C4H7 PES: every PEDSpecies
    product CH2CHCHCH3 / CH2CH2CHCH2 is a HotEnergies well of C4H7, every
    PED file sets MicroEner*: no stop, no warning, in either order."""
    _, _, reader = _read(order, species=HOT_SPECIES, prompt=True)
    _assert_clean(reader)


@pytest.mark.parametrize('files, counts', [
    ((H3, H4, H2B), 'PEDSpecies in 3 input(s), HotEnergies in 0 input(s)'),
    ((C4H7,), 'PEDSpecies in 0 input(s), HotEnergies in 1 input(s)'),
], ids=['no_hot', 'no_ped'])
def test_prompt_without_ped_or_hot_stops(files, counts) -> None:
    """No HotEnergies anywhere (H group alone) or no PEDSpecies anywhere
    (C4H7 alone): one stop telling which side is missing, no warning."""
    _, _, reader = _read(files, species=HOT_SPECIES, prompt=True)
    warnings, errors = _messages(reader)
    assert reader._trigger_stop is True
    assert warnings == []
    assert len(errors) == 1, errors
    assert "'prompt_reactions' is true but no PEDSpecies product" in \
        errors[0]
    assert counts in errors[0]


def test_prompt_self_link_does_not_count(tmp_path) -> None:
    """C4H7 alone with a PEDSpecies whose product is its own hot well: a
    product hot in its own file is no link, so the read stops."""
    root = _prompt_copy(tmp_path, {C4H7: [(
        'RateOutput                             rate.out\n',
        'RateOutput                             rate.out\n'
        'PEDSpecies CH2CHCHCH2+H=CH2CHCHCH3\n')]}, files=(C4H7,))
    sop, _, reader = _read((C4H7,), root=root, species=HOT_SPECIES,
                           prompt=True)
    assert sop.pes_file_data[0].ped_species == ['CH2CHCHCH2+H=CH2CHCHCH3']
    warnings, errors = _messages(reader)
    assert reader._trigger_stop is True
    assert len(errors) == 1, errors
    assert 'PEDSpecies in 1 input(s), HotEnergies in 1 input(s)' in errors[0]


@pytest.mark.parametrize('pair', ['CH2CHCH2CH3+H', 'A+B=C+D=E', 'A+=B'],
                         ids=['no_eq', 'two_eq', 'empty_name'])
def test_prompt_malformed_ped_pair_stops(tmp_path, pair) -> None:
    """A PEDSpecies entry that is not ``<reactants>=<products>`` stops a
    prompt read, naming the file and the entry (and nothing else); the
    same copy read without prompt mode does not stop."""
    root = _prompt_copy(tmp_path, {H3: [(_H3_PED, pair)]})
    _, _, reader = _read(ORDERS4[0], root=root, species=HOT_SPECIES,
                         prompt=True)
    warnings, errors = _messages(reader)
    assert reader._trigger_stop is True
    assert warnings == []
    assert len(errors) == 1, errors
    assert f"PEDSpecies entry '{pair}' of {root / H3}" in errors[0]
    assert '<reactants>=<products>' in errors[0]

    _, _, reader = _read(ORDERS4[0], root=root, species=HOT_SPECIES)
    _assert_clean(reader)


def test_prompt_unlinked_ped_pes_only_warns(tmp_path) -> None:
    """A PED file whose products are hot nowhere (2-H_C4H71-3 rewritten to
    form CH2CHCH2CH3+H) while the others link: no stop, one warning naming
    that file only."""
    root = _prompt_copy(tmp_path, {H2B: [(
        _H2B_PED, 'CH3CHCHCH3+H=CH2CHCH2CH3+H')]})
    _, _, reader = _read(ORDERS4[1], root=root, species=HOT_SPECIES,
                         prompt=True)
    warnings, errors = _messages(reader)
    assert reader._trigger_stop is False, errors
    assert errors == []
    assert len(warnings) == 1, warnings
    assert warnings[0].startswith(
        f'Prompt reactions: no PEDSpecies product of {root / H2B} is a '
        'HotEnergies species of another MESS input')


@pytest.mark.parametrize('removed', [_MICRO[2:], _MICRO],
                         ids=['one_missing', 'all_missing'])
def test_prompt_linked_ped_incomplete_micro_ener_stops(tmp_path,
                                                       removed) -> None:
    """A linked PED file (H_C4H71-3) without MicroEnerStep, or without all
    three MicroEner keys: one stop naming the file and its linked product;
    the other PED files pass."""
    root = _prompt_copy(tmp_path, {H3: [(line, '') for line in removed]})
    _, _, reader = _read(ORDERS4[0], root=root, species=HOT_SPECIES,
                         prompt=True)
    warnings, errors = _messages(reader)
    assert reader._trigger_stop is True
    assert warnings == []
    assert len(errors) == 1, errors
    assert errors[0].startswith(
        'Prompt reactions: the PEDSpecies products CH2CHCHCH3 of '
        f'{root / H3} are HotEnergies species of another MESS input')
    assert 'MicroEnerStep' in errors[0] and '_ke.out' in errors[0]


def test_prompt_unlinked_ped_incomplete_micro_ener_only_warns(
        tmp_path) -> None:
    """An unlinked PED file needs no MicroEner keys: 2-H_C4H71-3 unlinked
    and without MicroEner* gets the unlinked warning only, no stop."""
    root = _prompt_copy(tmp_path, {H2B: [
        (_H2B_PED, 'CH3CHCHCH3+H=CH2CHCH2CH3+H'),
        *((line, '') for line in _MICRO)]})
    sop, _, reader = _read(ORDERS4[0], root=root, species=HOT_SPECIES,
                           prompt=True)
    assert sop.pes_file_data[ORDERS4[0].index(H2B)].micro_ener is None
    warnings, errors = _messages(reader)
    assert reader._trigger_stop is False, errors
    assert errors == []
    assert len(warnings) == 1, warnings
    assert f'no PEDSpecies product of {root / H2B}' in warnings[0]
