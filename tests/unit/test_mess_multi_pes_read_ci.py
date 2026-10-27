"""CI-safe tests: several MESS input files (one PES each) read into one SOP.

Black-box tests of ``MessInputReader.read`` on small synthetic MESS inputs
written to ``tmp_path`` (one file per PES, file index = PES id):

* items with the same label in several files are one object carrying the PES
  id of every file; their data must be identical, else the read stops;
* energies of files sharing items are aligned (offset of each file =
  shared energy difference, reference = first file of each group of linked
  files), every shared energy is checked after alignment (0.01 kcal/mol);
* header keys: ten keys must be the same in all files (value and presence),
  ModelEnergyLimit / AtomDistanceMin / WellExtension are kept per PES, the
  first Epsilons / Sigmas / Masses value (collider) must be the same in all
  files and the second one is PES-specific (``SOP.epsilons`` =
  ``[collider, file 0, file 1, ...]``);
* AutoMech fake wells (``FW-`` / ``FakeW-``) need no mechanism species;
  ``Atom`` fragments, ``PotentialSpline`` rotors and the fragment
  ``density`` keyword are read.

Stop cases assert ``_trigger_stop`` and exactly one message naming the key
or item and the file; consistent inputs log no warning and no error.

The builders below are reused by ``test_mess_multi_pes_write_ci.py`` and
``test_sop_lj_per_pes_ci.py``. No MESS binary, database or automech install
is needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pytest

from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.enums import FreqMode
from kimeco.readers.mess_input import (MessInputReader, PesEnergyAlignment,
                                       is_fake_well_label)
from kimeco.well import Well
from kimeco.writers.mess import MessTemplate


# ---------------------------------------------------------------------------
# MESS snippet builders
# ---------------------------------------------------------------------------
_GEO_2 = ['        C 0.0 0.0 0.0\n', '        O 0.0 0.0 1.2\n']


def model(eps: str | None = '7.95 206.15',
          sig: str | None = '2.715 4.71',
          masses: str | None = '4.0 77.0',
          factor: str | None = '200',
          power: str | None = '0.85',
          header: Iterable[str] = (),
          relax: Iterable[str] = (),
          eps_token: str = 'Epsilons[1/cm]',
          sig_token: str = 'Sigmas[angstrom]') -> list[str]:
    """Global section of a MESS input: grids, extra header lines, then the
    energy-relaxation and collision blocks (a line is dropped when None)."""
    lines = ['TemperatureList[K]  500 600\n',
             'PressureList[bar]   0.1 1.0\n']
    lines += list(header)
    lines += ['Model\n', '  EnergyRelaxation\n', '    Exponential\n']
    if factor is not None:
        lines.append(f'      Factor[1/cm]    {factor}\n')
    if power is not None:
        lines.append(f'      Power           {power}\n')
    lines += list(relax)
    lines += ['    End\n', '  CollisionFrequency\n', '    LennardJones\n']
    if eps is not None:
        lines.append(f'      {eps_token}  {eps}\n')
    if sig is not None:
        lines.append(f'      {sig_token}  {sig}\n')
    if masses is not None:
        lines.append(f'      Masses[amu]  {masses}\n')
    lines += ['    End\n']
    return lines


def rotor(scan: str = '0.00 0.50 1.00 0.50',
          group: str = '2',
          axis: str = '1 2',
          symmetry: int = 1,
          angles: str | None = None) -> list[str]:
    """A hindered rotor; ``angles`` given -> a PotentialSpline rotor."""
    lines = ['      Rotor  Hindered\n',
             f'        Group     {group}\n',
             f'        Axis      {axis}\n',
             f'        Symmetry  {symmetry}\n']
    npot = len(scan.split())
    if angles is None:
        lines.append(f'        Potential[kcal/mol]  {npot}\n')
    else:
        lines.append(f'        PotentialSpline[kcal/mol]  {npot}  {npot - 1}\n')
        lines.append(f'          {angles}\n')
    lines += [f'          {scan}\n', '      End\n']
    return lines


def well(name: str, energy: float | str = 0.0,
         freqs: str = '1500.0', rotors: Iterable[list[str]] = (),
         geo: list[str] | None = None, comment: str = '') -> list[str]:
    lines = [f'Well {name}{comment}\n', '  Species\n', '    RRHO\n',
             f'      Geometry[angstrom]  {len(geo or _GEO_2)}\n']
    lines += list(geo or _GEO_2)
    lines += ['      Core RigidRotor\n', '        SymmetryFactor 1.0\n',
              '      End\n',
              f'      Frequencies[1/cm]  {len(freqs.split())}\n',
              f'        {freqs}\n']
    for rot in rotors:
        lines += rot
    lines += [f'      ZeroEnergy[kcal/mol]  {energy}\n', '  End\n', 'End\n']
    return lines


def fragment(name: str, freqs: str = '3700.0', density: bool = False,
             rotors: Iterable[list[str]] = ()) -> list[str]:
    lines = [f'  Fragment {name}{" density" if density else ""}\n',
             '    RRHO\n', '      Geometry[angstrom]  2\n',
             '        O 0.0 0.0 0.0\n', '        H 0.0 0.0 0.97\n',
             '      Core RigidRotor\n', '        SymmetryFactor 1.0\n',
             '      End\n',
             f'      Frequencies[1/cm]  {len(freqs.split())}\n',
             f'        {freqs}\n']
    for rot in rotors:
        lines += rot
    lines += ['      ZeroEnergy[kcal/mol]  0.0\n', '    End\n']
    return lines


def atom(name: str, mass: str | None = '1.00782503223',
         density: bool = False) -> list[str]:
    lines = [f'  Fragment {name}{" density" if density else ""}\n',
             '    Atom\n']
    if mass is not None:
        lines.append(f'      Mass[amu]  {mass}\n')
    lines += ['      ElectronicLevels[1/cm]  1\n', '        0.0  2\n',
              '    End\n']
    return lines


def bimol(name: str, frags: Iterable[list[str]],
          energy: float | str = 0.0) -> list[str]:
    lines = [f'Bimolecular {name}\n']
    for frag in frags:
        lines += frag
    lines += [f'  GroundEnergy[kcal/mol]  {energy}\n', 'End\n']
    return lines


def saddle(name: str, lside: str, rside: str, energy: float | str = 10.0,
           freqs: str = '800.0', ifreq: str = '1500.0') -> list[str]:
    return [f'Barrier {name} {lside} {rside}\n', '  RRHO\n',
            '    Geometry[angstrom]  2\n', *_GEO_2,
            '    Core RigidRotor\n', '      SymmetryFactor 1.0\n',
            '    End\n',
            f'    Frequencies[1/cm]  {len(freqs.split())}\n',
            f'      {freqs}\n',
            f'    ZeroEnergy[kcal/mol]  {energy}\n',
            '    Tunneling  Eckart\n',
            f'      ImaginaryFrequency[1/cm]  {ifreq}\n',
            '      WellDepth[kcal/mol]  10.0\n',
            '      WellDepth[kcal/mol]  12.0\n',
            '    End\n',
            'End\n']


def pst(name: str, lside: str, rside: str, energy: float | str = 0.0,
        prefactor: str = '10.0', tst_level: str | None = 'EJ',
        rotors: Iterable[list[str]] = ()) -> list[str]:
    lines = [f'Barrier {name} {lside} {rside}\n', '  RRHO\n',
             '    Stoichiometry  C1O1H1\n',
             '    Core PhaseSpaceTheory\n',
             '      FragmentGeometry[angstrom]  2\n',
             '        O 0.0 0.0 0.0\n', '        H 0.0 0.0 0.97\n',
             '      FragmentGeometry[angstrom]  1\n',
             '        C 0.0 0.0 0.0\n',
             '      SymmetryFactor  1.0\n',
             f'      PotentialPrefactor[au]  {prefactor}\n',
             '      PotentialPowerExponent  6.0\n']
    if tst_level is not None:
        lines.append(f'      TSTLevel {tst_level}\n')
    lines += ['    End\n', '    Frequencies[1/cm]  1\n', '      300.0\n']
    for rot in rotors:
        lines += rot
    lines += [f'    ZeroEnergy[kcal/mol]  {energy}\n', 'End\n']
    return lines


END = ['End\n']


def mess_file(*blocks: Iterable[str], **model_kwargs: Any) -> list[str]:
    """A whole MESS input: ``model(**model_kwargs)``, the blocks, End."""
    lines = model(**model_kwargs)
    for block in blocks:
        lines += list(block)
    return lines + END


# ---------------------------------------------------------------------------
# Reader harness
# ---------------------------------------------------------------------------
class SpyLog:
    """Records warning/error messages; mirrors the KMOLogger surface used."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.infos: list[str] = []

    def warning(self, msg: str = '', *a: Any, **k: Any) -> None:
        self.warnings.append(str(msg))

    def error(self, msg: str = '', *a: Any, **k: Any) -> None:
        self.errors.append(str(msg))

    def info(self, msg: str = '', *a: Any, **k: Any) -> None:
        self.infos.append(str(msg))

    def debug(self, *a: Any, **k: Any) -> None:
        pass


def species_of(files: Iterable[Iterable[str]]) -> list[str]:
    """Every Well / Fragment label of the files that is not a fake well
    (the mechanism species list that makes ``validate_species`` pass)."""
    names: list[str] = []
    for lines in files:
        for line in lines:
            tokens = line.split()
            if (len(tokens) >= 2 and tokens[0] in ('Well', 'Fragment')
                    and not is_fake_well_label(tokens[1])
                    and tokens[1] not in names):
                names.append(tokens[1])
    return names


def make_reader(tmp_path: Path, files: list[list[str]],
                species: list[str] | None = None,
                force_new_molecules: bool = False,
                names: list[str] | None = None) -> MessInputReader:
    """A reader on real files ``f0.inp``, ``f1.inp``... in ``tmp_path``."""
    names = names or [f'f{k}.inp' for k in range(len(files))]
    for name, lines in zip(names, files):
        (tmp_path / name).write_text(''.join(lines))
    settings = {
        'init_loc': str(tmp_path), 'mess_inputs': list(names), 'n_exp': 1,
        'score_sp': [], 'freq_mode': FreqMode.BATCH,
        'rc_temp': [500.0, 600.0], 'rc_pres': [0.1, 1.0],
        'pres_unit': 'bar', 'force_new_molecules': force_new_molecules}
    reader = MessInputReader(
        settings=settings,
        mechanism_species=species if species is not None
        else species_of(files),
        klog=SpyLog(),  # type: ignore[arg-type]
        postprocess=False)
    return reader


def read(tmp_path: Path, *files: list[str], **kwargs: Any
         ) -> tuple[Any, list[MessTemplate], MessInputReader]:
    """Read the files; returns (SOP, templates, reader)."""
    reader = make_reader(tmp_path, list(files), **kwargs)
    sop, tpls = reader.read()
    return sop, tpls, reader


def log_of(reader: MessInputReader) -> SpyLog:
    return reader.klog  # type: ignore[return-value]


def assert_clean(reader: MessInputReader) -> None:
    """No stop, no warning, no error."""
    log = log_of(reader)
    assert reader._trigger_stop is False, (log.warnings, log.errors)
    assert log.warnings == [] and log.errors == [], (log.warnings, log.errors)


def stop_messages(reader: MessInputReader) -> list[str]:
    log = log_of(reader)
    return log.warnings + log.errors


def assert_one_stop(reader: MessInputReader, *needles: str) -> str:
    """The read stopped with exactly one message containing every needle."""
    assert reader._trigger_stop is True
    hits = [m for m in stop_messages(reader)
            if all(needle in m for needle in needles)]
    assert len(hits) == 1, (needles, stop_messages(reader))
    return hits[0]


def two_pes_shared(file2_overrides: dict[str, list[str]] | None = None
                   ) -> tuple[list[str], list[str]]:
    """Two files sharing a fake well (2 rotors), a bimolecular A+B, its PST
    barrier, a plain well W and the saddle W=FakeW-A+B; each file also owns
    a well of its own (U0, U1)."""
    blocks = {
        'fake': well('FakeW-A+B', -1.0,
                     rotors=[rotor(), rotor(scan='0.0 0.3 0.9 0.3',
                                            group='1', axis='2 1')]),
        'w': well('W', -5.0),
        'bimol': bimol('A+B', [fragment('A'), fragment('B', '1600.0')], 0.0),
        'pst': pst('A+B=FakeW-A+B', 'A+B', 'FakeW-A+B', 0.0),
        'saddle': saddle('W=FakeW-A+B', 'W', 'FakeW-A+B', 10.0),
    }
    first = mess_file(*blocks.values(), well('U0', -2.0))
    blocks.update(file2_overrides or {})
    second = mess_file(*blocks.values(), well('U1', -3.0))
    return first, second


# ---------------------------------------------------------------------------
# R1: shared items are single multi-PES objects
# ---------------------------------------------------------------------------
def test_shared_items_are_single_multi_pes_objects(tmp_path) -> None:
    """Shared fake well, plain well, bimolecular, PST barrier and saddle:
    one object each, PES ids [0, 1], rotors not doubled, no stop; each file
    keeps its own template."""
    sop, tpls, reader = read(tmp_path, *two_pes_shared())
    assert_clean(reader)
    for name in ('FakeW-A+B', 'W', 'A+B', 'A+B=FakeW-A+B', 'W=FakeW-A+B'):
        item = sop.items[name]
        assert item.pes_ids == [0, 1], name
        assert item.in_multiple_pes is True, name
        assert sop.item_pes_ids[name] == (0, 1), name
    for name in ('U0', 'U1'):
        assert sop.items[name].in_multiple_pes is False
    assert sop.item_pes_ids['U1'] == (1,)
    assert [w.name for w in sop.wells] == ['FakeW-A+B', 'W', 'U0', 'U1']
    assert [b.name for b in sop.barriers] == ['A+B=FakeW-A+B',
                                               'W=FakeW-A+B']
    assert [b.name for b in sop.bimolecular] == ['A+B']
    bim = sop.items['A+B']
    assert bim.frag_names == ['A', 'B']
    assert bim.fragments[0] is sop.items['A']
    # Rotors declared again in the second file are not appended again.
    assert len(sop.items['FakeW-A+B'].h_rotors) == 2
    names = list(sop.parameters_names)
    assert 'FakeW-A+B__hrs1' in names and 'FakeW-A+B__hrs2' not in names
    assert sop.pes_ids == [0, 1]
    assert [tpl.pes_id for tpl in tpls] == [0, 1]
    assert all(isinstance(tpl, MessTemplate) for tpl in tpls)
    for tpl in tpls:
        assert 'Well {FakeW-A+B.name}\n' in tpl
        assert ' {FakeW-A+B.r_scan(1)}\n' in tpl
    # The shared items are noted at info level only.
    assert any('shared by several MESS inputs' in m
               for m in log_of(reader).infos)


def test_shared_barrier_with_sides_in_both_files(tmp_path) -> None:
    """A barrier repeated in a file that declares both of its sides is one
    shared barrier (positive counterpart of
    ``test_read_duplicate_barrier_name_across_inputs_triggers_stop``)."""
    first = mess_file(well('L', 0.0), well('R', -1.0),
                      saddle('L=R', 'L', 'R', 5.0))
    second = mess_file(well('L', 0.0), well('R', -1.0),
                       saddle('L=R', 'L', 'R', 5.0))
    sop, _, reader = read(tmp_path, first, second)
    assert_clean(reader)
    assert sop.items['L=R'].pes_ids == [0, 1]
    assert len(sop.barriers) == 1


# ---------------------------------------------------------------------------
# R2: shared item whose data differ -> stop
# ---------------------------------------------------------------------------
_MISMATCHES: dict[str, tuple[dict[str, list[str]], tuple[str, ...]]] = {
    'barrier_sides': (
        {'saddle': saddle('W=FakeW-A+B', 'FakeW-A+B', 'W', 10.0)},
        ('Barrier W=FakeW-A+B connects W and FakeW-A+B',)),
    'barrier_frequencies': (
        {'saddle': saddle('W=FakeW-A+B', 'W', 'FakeW-A+B', 10.0,
                          freqs='801.0')},
        ('Barrier W=FakeW-A+B differs between', 'in: frequencies.')),
    'barrier_imaginary_frequency': (
        {'saddle': saddle('W=FakeW-A+B', 'W', 'FakeW-A+B', 10.0,
                          ifreq='1400.0')},
        ('Barrier W=FakeW-A+B differs between', 'imaginary frequency')),
    'fake_well_geometry': (
        {'fake': well('FakeW-A+B', -1.0,
                      rotors=[rotor(), rotor(scan='0.0 0.3 0.9 0.3',
                                             group='1', axis='2 1')],
                      geo=['        C 0.0 0.0 0.0\n',
                           '        O 0.0 0.0 1.3\n'])},
        ('Well FakeW-A+B differs between', 'in: geometry.')),
    'rotor_scan': (
        {'fake': well('FakeW-A+B', -1.0,
                      rotors=[rotor(scan='0.00 0.60 1.00 0.50'),
                              rotor(scan='0.0 0.3 0.9 0.3', group='1',
                                    axis='2 1')])},
        ('Well FakeW-A+B differs between', 'in: hindered rotors.')),
    'rotor_count': (
        {'fake': well('FakeW-A+B', -1.0, rotors=[rotor()])},
        ('Well FakeW-A+B differs between', 'in: hindered rotors.')),
    'bimol_fragment_set': (
        {'bimol': bimol('A+B', [fragment('A'), fragment('C', '1600.0')]),
         'pst': pst('A+B=FakeW-A+B', 'A+B', 'FakeW-A+B', 0.0)},
        ('Bimolecular A+B differs between', 'in: fragments.')),
    'bimol_density': (
        {'bimol': bimol('A+B', [fragment('A', density=True),
                                fragment('B', '1600.0')])},
        ('Bimolecular A+B differs between', 'in: fragment density.')),
    'fragment_frequency': (
        {'bimol': bimol('A+B', [fragment('A', '3701.0'),
                                fragment('B', '1600.0')])},
        ('Well A differs between', 'in: frequencies.')),
    'pst_prefactor': (
        {'pst': pst('A+B=FakeW-A+B', 'A+B', 'FakeW-A+B', 0.0,
                    prefactor='12.0')},
        ('Barrier A+B=FakeW-A+B differs between', 'PotentialPrefactor')),
    'pst_tst_level': (
        {'pst': pst('A+B=FakeW-A+B', 'A+B', 'FakeW-A+B', 0.0,
                    tst_level='E')},
        ('Barrier A+B=FakeW-A+B differs between', 'TSTLevel')),
}


@pytest.mark.parametrize('case', sorted(_MISMATCHES))
def test_shared_item_data_mismatch_stops(tmp_path, case) -> None:
    """Any difference in the input data of a shared item stops the read
    with one error naming the item (and both files for a data mismatch)."""
    overrides, needles = _MISMATCHES[case]
    sop, _, reader = read(tmp_path, *two_pes_shared(overrides))
    msg = assert_one_stop(reader, *needles)
    assert reader.filenames[1] in msg
    if 'differs between' in msg:
        assert reader.filenames[0] in msg
    # The stored item keeps the first file's data.
    assert sop.items['FakeW-A+B'].h_rotors[0].scan[1] == pytest.approx(0.5)


def test_fragment_shared_by_two_bimoleculars(tmp_path) -> None:
    """Fragment X in A+X and B+X: one object; identical data -> no stop,
    the density flag belongs to each bimolecular slot; one frequency
    +1 cm-1 in the second bimolecular -> stop naming X."""
    first = mess_file(bimol('A+X', [fragment('A', '1000.0'),
                                    fragment('X', '2000.0', density=True)]))
    second = mess_file(bimol('B+X', [fragment('B', '1100.0'),
                                     fragment('X', '2000.0')]))
    sop, _, reader = read(tmp_path, first, second)
    assert_clean(reader)
    assert sop.items['A+X'].fragments[1] is sop.items['B+X'].fragments[1]
    assert sop.items['A+X'].fragment_density == [False, True]
    assert sop.items['B+X'].fragment_density == [False, False]
    assert sop.items['X'].pes_ids == []

    second = mess_file(bimol('B+X', [fragment('B', '1100.0'),
                                     fragment('X', '2001.0')]))
    _, _, reader = read(tmp_path, first, second)
    msg = assert_one_stop(reader, 'Well X differs between', 'frequencies')
    assert reader.filenames[0] in msg and reader.filenames[1] in msg

    # Same file: X twice in one bimolecular with identical data is allowed.
    sop, _, reader = read(tmp_path, mess_file(
        bimol('X+X', [fragment('X', '2000.0'), fragment('X', '2000.0')])))
    assert_clean(reader)
    assert sop.items['X+X'].fragments[0] is sop.items['X+X'].fragments[1]


_LABEL_CONFLICTS: dict[str, tuple[list[list[str]], tuple[str, ...]]] = {
    'well_then_bimolecular': (
        [mess_file(well('Q')), mess_file(well('Z'),
                                         bimol('Q', [fragment('A'),
                                                     fragment('B')]))],
        ('Label Q names a Well in', 'and a Bimolecular in')),
    'bimolecular_then_well': (
        [mess_file(bimol('Q', [fragment('A'), fragment('B')])),
         mess_file(well('Q'))],
        ('Label Q names a Bimolecular in', 'and a Well in')),
    'well_then_barrier': (
        [mess_file(well('Q'), well('R')),
         mess_file(well('Q'), well('R'), saddle('R', 'Q', 'R'))],
        ('names a Well in', 'and a Barrier in')),
    'well_twice_in_file': (
        [mess_file(well('Q'), well('Q'))],
        ('Well Q is declared twice in',)),
    'barrier_twice_in_file': (
        [mess_file(well('Q'), well('R'), saddle('Q=R', 'Q', 'R'),
                   saddle('Q=R', 'Q', 'R'))],
        ('Barrier Q=R is declared twice in',)),
    'bimolecular_twice_in_file': (
        [mess_file(bimol('A+B', [fragment('A'), fragment('B')]),
                   bimol('A+B', [fragment('A'), fragment('B')]))],
        ('Multiple Bimolecular A+B exist in',)),
    'barrier_side_missing': (
        [mess_file(well('Q'), saddle('Q=R', 'Q', 'R'))],
        ('Barrier Q=R connects R, which is not a Well or Bimolecular',)),
    'third_fragment': (
        [mess_file(bimol('A+B', [fragment('A'), fragment('B'),
                                 fragment('C')]))],
        ('already has two fragments',)),
    'fragment_is_a_barrier': (
        [mess_file(well('Q'), well('R'), saddle('Q=R', 'Q', 'R'),
                   bimol('A+B', [fragment('A'), fragment('Q=R')]))],
        ('Fragment Q=R points to a barrier object',)),
    'fragment_is_a_bimolecular': (
        [mess_file(bimol('A+B', [fragment('A'), fragment('B')]),
                   bimol('C+D', [fragment('C'), fragment('A+B')]))],
        ('Fragment A+B is not a well object',)),
}


@pytest.mark.parametrize('case', sorted(_LABEL_CONFLICTS))
def test_label_conflicts_stop(tmp_path, case) -> None:
    """A label reused for another kind of item, an item declared twice in
    one file, a barrier side not declared in its file, a third fragment:
    one message and a stop; the read goes on to the end."""
    files, needles = _LABEL_CONFLICTS[case]
    _, tpls, reader = read(tmp_path, *files)
    assert_one_stop(reader, *needles)
    assert len(tpls) == len(files)


def test_file_without_well_or_bimolecular_stops(tmp_path) -> None:
    """Every file must own a well or a bimolecular (template k <-> PES k)."""
    first = mess_file(well('L'), well('R'), saddle('L=R', 'L', 'R'))
    second = mess_file()
    _, _, reader = read(tmp_path, first, second)
    msg = assert_one_stop(reader, 'declares no Well and no Bimolecular')
    assert reader.filenames[1] in msg


# ---------------------------------------------------------------------------
# R3-R6: energy alignment
# ---------------------------------------------------------------------------
def _alignment_pair(shift: float = 1.61, unique: float = 5.0
                    ) -> tuple[list[str], list[str]]:
    """A: bimol P 0.0, FakeW-P -1.0; B: same items +shift, unique U."""
    a = mess_file(bimol('P', [fragment('A'), fragment('B', '1600.0')], 0.0),
                  well('FakeW-P', -1.0))
    b = mess_file(bimol('P', [fragment('A'), fragment('B', '1600.0')],
                        round(0.0 + shift, 6)),
                  well('FakeW-P', round(-1.0 + shift, 6)),
                  well('U', unique))
    return a, b


def test_energy_alignment_offset_sign_and_reference(tmp_path) -> None:
    """Offset of file B = its shared energies minus file A's (sign fixed);
    the first file is the reference; differences between items are the
    same whatever the file order."""
    a, b = _alignment_pair()
    sop, _, reader = read(tmp_path, a, b)
    assert_clean(reader)
    assert sop.pes_file_data[0].energy_offset == 0.0
    assert sop.pes_file_data[1].energy_offset == pytest.approx(1.61)
    # Old sign bug would give 6.61.
    assert sop.items['U'].energy == pytest.approx(3.39)
    assert sop.items['P'].energy == pytest.approx(0.0)
    assert sop.items['FakeW-P'].energy == pytest.approx(-1.0)
    first_order = {n: sop.items[n].energy for n in ('U', 'P', 'FakeW-P')}
    assert any('above the reference file' in m
               for m in log_of(reader).infos)

    sub = tmp_path / 'swapped'
    sub.mkdir()
    sop, _, reader = read(sub, b, a)
    assert_clean(reader)
    assert sop.pes_file_data[0].energy_offset == 0.0
    assert sop.pes_file_data[1].energy_offset == pytest.approx(-1.61)
    assert sop.items['U'].energy == pytest.approx(5.0)
    assert sop.items['P'].energy == pytest.approx(1.61)
    swapped = {n: sop.items[n].energy for n in ('U', 'P', 'FakeW-P')}
    for x in first_order:
        for y in first_order:
            assert (first_order[x] - first_order[y]) == pytest.approx(
                swapped[x] - swapped[y])
    # Energies and offsets are rounded to 1e-10 kcal/mol.
    assert sop.items['P'].energy == round(sop.items['P'].energy, 10)


def test_alignment_through_hub_read_last(tmp_path) -> None:
    """[X, Y, H]: X and Y share nothing, the hub H shares PX with X and PY
    with Y; Y is aligned through H although H is read last."""
    x = mess_file(bimol('PX', [fragment('A'), fragment('B')], 0.0),
                  well('UX', 3.0))
    y = mess_file(bimol('PY', [fragment('C'), fragment('D')], 0.0),
                  well('UY', 4.0))
    h = mess_file(bimol('PX', [fragment('A'), fragment('B')], 0.0),
                  bimol('PY', [fragment('C'), fragment('D')], -1.61))
    sop, _, reader = read(tmp_path, x, y, h)
    assert_clean(reader)
    offsets = {k: v.energy_offset for k, v in sop.pes_file_data.items()}
    assert offsets == pytest.approx({0: 0.0, 1: 1.61, 2: 0.0})
    assert sop.items['UY'].energy == pytest.approx(2.39)
    assert sop.items['PY'].energy == pytest.approx(-1.61)
    hub_last = {n: sop.items[n].energy for n in ('UX', 'UY', 'PX', 'PY')}

    sub = tmp_path / 'hub_first'
    sub.mkdir()
    sop, _, reader = read(sub, h, x, y)
    assert_clean(reader)
    offsets = {k: v.energy_offset for k, v in sop.pes_file_data.items()}
    assert offsets == pytest.approx({0: 0.0, 1: 0.0, 2: 1.61})
    hub_first = {n: sop.items[n].energy for n in hub_last}
    assert hub_first == pytest.approx(hub_last)


def test_components_without_shared_items(tmp_path) -> None:
    """A file sharing nothing keeps offset 0 and its raw energies; the
    first file of each group of linked files is its reference."""
    a, b = _alignment_pair()
    c = mess_file(well('UC', 7.0))
    sop, _, reader = read(tmp_path, a, c, b)
    assert_clean(reader)
    offsets = {k: v.energy_offset for k, v in sop.pes_file_data.items()}
    assert offsets == pytest.approx({0: 0.0, 1: 0.0, 2: 1.61})
    assert sop.items['UC'].energy == 7.0

    c = mess_file(well('UC', 7.0), well('S', 2.0))
    d = mess_file(well('S', 2.5), well('UD', 9.0))
    sub = tmp_path / 'two_groups'
    sub.mkdir()
    sop, _, reader = read(sub, a, c, d, b)
    assert_clean(reader)
    offsets = {k: v.energy_offset for k, v in sop.pes_file_data.items()}
    assert offsets == pytest.approx({0: 0.0, 1: 0.0, 2: 0.5, 3: 1.61})
    assert sop.items['UC'].energy == 7.0
    assert sop.items['UD'].energy == pytest.approx(8.5)


@pytest.mark.parametrize('delta, stops', [(0.02, True), (0.005, False)])
def test_alignment_mismatch_tolerance(tmp_path, delta, stops) -> None:
    """A shared energy off by more than 0.01 kcal/mol after alignment stops
    (one error naming the item and both files); 0.005 does not."""
    a = mess_file(bimol('P', [fragment('A'), fragment('B')], 0.0),
                  well('FakeW-P', -1.0))
    b = mess_file(bimol('P', [fragment('A'), fragment('B')], 1.0),
                  well('FakeW-P', round(-1.0 + 1.0 + delta, 6)))
    _, _, reader = read(tmp_path, a, b)
    if stops:
        msg = assert_one_stop(reader, 'Energy of FakeW-P is not consistent')
        assert reader.filenames[0] in msg and reader.filenames[1] in msg
    else:
        assert_clean(reader)


def test_alignment_inconsistent_cycle_stops(tmp_path) -> None:
    """A-B +1 through P1, B-C +1 through P2, A-C 0 through P3: no offsets
    satisfy all three, the read stops naming the item and both files."""
    a = mess_file(well('P1', 0.0), well('P3', 0.0))
    b = mess_file(well('P1', 1.0), well('P2', 0.0))
    c = mess_file(well('P2', 1.0), well('P3', 0.0))
    _, _, reader = read(tmp_path, a, b, c)
    msg = assert_one_stop(reader, 'is not consistent between')
    assert sum(name in msg for name in reader.filenames) == 2


def test_pes_energy_alignment_unit() -> None:
    """PesEnergyAlignment: only anchors link files; non-anchor shared labels
    are checked; files linked by nothing keep offset 0."""
    energies = {'L': {0: 0.0, 1: 1.0}, 'N': {1: 2.0, 2: 5.0},
                'M': {0: 3.0, 1: 4.0}}
    align = PesEnergyAlignment(n_files=3, energies=energies, anchors={'L'})
    assert align.solve() == {0: 0.0, 1: 1.0, 2: 0.0}
    assert align.links == {1: 'L'}
    assert align.aligned_energy('M') == 3.0
    # N is not an anchor: file 2 stays unlinked and N disagrees by +4.
    assert align.mismatches() == [('N', 1, 2, pytest.approx(4.0))]
    assert PesEnergyAlignment.TOLERANCE == 0.01


# ---------------------------------------------------------------------------
# R7a: the ten keys that must be the same in every file
# ---------------------------------------------------------------------------
# (label, line in A, different line, equal line after normalisation,
#  SOP attribute, stored value)
_SAME_KEYS = [
    ('CalculationMethod', 'CalculationMethod direct',
     'CalculationMethod low-eigenvalue', 'CalculationMethod Direct',
     'calculation_method', 'direct'),
    ('EnergyStepOverTemperature', 'EnergyStepOverTemperature .2',
     'EnergyStepOverTemperature 0.3', 'EnergyStepOverTemperature 0.20',
     'ene_step_over_temp', 0.2),
    ('ExcessEnergyOverTemperature', 'ExcessEnergyOverTemperature 30',
     'ExcessEnergyOverTemperature 40', 'ExcessEnergyOverTemperature 30.0',
     'excess_ene_temp', 30.0),
    ('ChemicalEigenvalueMax', 'ChemicalEigenvalueMax 0.2',
     'ChemicalEigenvalueMax 0.1', 'ChemicalEigenvalueMax .2',
     'chem_eig_max', 0.2),
    ('WellCutoff', 'WellCutoff 10', 'WellCutoff 15', 'WellCutoff 10.0',
     'well_cutoff', 10.0),
    ('ReductionMethod', 'ReductionMethod diagonalization',
     'ReductionMethod projection', 'ReductionMethod Diagonalization',
     'reduction_method', 'diagonalization'),
    ('WellReductionThreshold', 'WellReductionThreshold 10',
     'WellReductionThreshold 12', 'WellReductionThreshold 10.0',
     'well_reduction_threshold', 10.0),
    ('GroundEnergyShiftMax', 'GroundEnergyShiftMax[kcal/mol] 10',
     'GroundEnergyShiftMax[kcal/mol] 5', 'GroundEnergyShiftMax[kJ/mol] 41.84',
     'ground_ene_shift_max', 10.0),
    ('FloatType', 'FloatType double', 'FloatType dd', 'FloatType DOUBLE',
     'float_type', 'double'),
    ('ExponentCutoff', 'ExponentCutoff 15', 'ExponentCutoff 20',
     'ExponentCutoff 15.000', 'exp_cutoff', 15.0),
]


def _key_files(line_a: str | None, line_b: str | None
               ) -> tuple[list[str], list[str]]:
    """Two files; ExponentCutoff goes in the relaxation block, the other
    keys in the global header."""
    def _one(line: str | None, wname: str) -> list[str]:
        lines = [] if line is None else [line + '\n']
        if line is not None and line.startswith('ExponentCutoff'):
            return mess_file(well(wname), relax=['      ' + lines[0]])
        return mess_file(well(wname), header=lines)
    return _one(line_a, 'WA'), _one(line_b, 'WB')


@pytest.mark.parametrize('key', _SAME_KEYS, ids=[k[0] for k in _SAME_KEYS])
def test_same_in_all_files_keys(tmp_path, key) -> None:
    """Different value -> one warning 'Different <Label> in <file B>' and a
    stop; key in one file only (either one) -> one presence error and a
    stop; equal after normalisation, or absent from both -> no stop. The
    first file's value is stored; each template keeps its own line."""
    label, line_a, line_diff, line_equal, attr, stored = key

    sop, tpls, reader = read(tmp_path, *_key_files(line_a, line_diff))
    msg = assert_one_stop(reader, f'Different {label} in')
    assert reader.filenames[1] in msg
    assert 'Saved value:' in msg
    assert getattr(sop, attr) == stored
    assert any(t.strip() == line_a for t in tpls[0])
    assert any(t.strip() == line_diff for t in tpls[1])

    for case, files in (('only_a', _key_files(line_a, None)),
                        ('only_b', _key_files(None, line_a))):
        sub = tmp_path / case
        sub.mkdir()
        sop, _, reader = read(sub, *files)
        msg = assert_one_stop(reader, f'{label} is set in', 'absent from')
        assert log_of(reader).warnings == [], case
        with_key, without = msg.split('absent from')
        present = 0 if case == 'only_a' else 1
        assert reader.filenames[present] in with_key
        assert reader.filenames[1 - present] in without
        assert getattr(sop, attr) == stored

    sub = tmp_path / 'equal'
    sub.mkdir()
    sop, tpls, reader = read(sub, *_key_files(line_a, line_equal))
    assert_clean(reader)
    assert getattr(sop, attr) == stored
    assert any(t.strip() == line_equal for t in tpls[1])

    sub = tmp_path / 'absent'
    sub.mkdir()
    sop, _, reader = read(sub, *_key_files(None, None))
    assert_clean(reader)
    assert getattr(sop, attr) is None


def test_ground_energy_shift_max_is_not_a_ground_energy(tmp_path) -> None:
    """GroundEnergyShiftMax (header) never reaches the GroundEnergy branch
    of bimoleculars: a single file reads cleanly and keeps the line."""
    lines = mess_file(bimol('A+B', [fragment('A'), fragment('B')], -2.0),
                      header=['GroundEnergyShiftMax[1/cm] 3497.55\n'])
    sop, tpls, reader = read(tmp_path, lines)
    assert_clean(reader)
    assert sop.ground_ene_shift_max == pytest.approx(10.0)
    assert sop.items['A+B'].energy == -2.0
    assert 'GroundEnergyShiftMax[1/cm] 3497.55\n' in tpls[0]


def test_header_value_errors(tmp_path) -> None:
    """A same-in-all key without a value or with a non-number stops; an
    unknown energy unit warns and stores the raw value."""
    cases = (('WellCutoff\n', 'WellCutoff has no value'),
             ('WellCutoff ten\n', "WellCutoff value 'ten' is not a number"),
             ('MicroEnerMax[kcal/mol]\n',
              'MicroEnerMax[kcal/mol] has no value'))
    for idx, (line, needle) in enumerate(cases):
        sub = tmp_path / f'case{idx}'
        sub.mkdir()
        _, _, reader = read(sub, mess_file(well('W'), header=[line]))
        assert_one_stop(reader, needle)
    sop, _, reader = read(tmp_path, mess_file(
        well('W'), header=['GroundEnergyShiftMax[eV] 0.5\n']))
    assert reader._trigger_stop is False
    assert sop.ground_ene_shift_max == 0.5
    assert any("Unknown GroundEnergyShiftMax unit 'ev'" in w
               for w in log_of(reader).warnings)


# ---------------------------------------------------------------------------
# R7b: per-PES keys never stop
# ---------------------------------------------------------------------------
def test_per_pes_keys_never_stop(tmp_path) -> None:
    """ModelEnergyLimit, AtomDistanceMin, WellExtension, PEDSpecies and
    MicroEner* differ (or are absent) between files: no stop, no warning;
    each file keeps its own value; templates keep the raw lines."""
    a_lines = ['ModelEnergyLimit[kcal/mol] 400\n',
               'AtomDistanceMin[bohr] 0.68793\n',
               'WellExtension 0.5\n',
               'PEDSpecies A+B=WA C+D=WA ! comment\n',
               'MicroEnerMin[kcal/mol] 0.\n',
               'MicroEnerMax[kcal/mol] 200.\n',
               'MicroEnerStep[1/cm] 349.755\n']
    b_lines = ['ModelEnergyLimit[kJ/mol] 3347.2\n',
               'AtomDistanceMin[angstrom] 1.0\n',
               'MicroEnerMax[kcal/mol] 150\n']
    a = mess_file(well('WA'), header=a_lines)
    b = mess_file(well('WB'), header=b_lines)
    sop, tpls, reader = read(tmp_path, a, b)
    assert_clean(reader)
    first, second = sop.pes_file_data[0], sop.pes_file_data[1]
    assert first.model_ene_limit == 400.0
    assert second.model_ene_limit == pytest.approx(800.0)
    assert sop.model_ene_limit == 400.0
    assert first.atom_distance_min == (0.68793, 'bohr')
    assert second.atom_distance_min == (1.0, 'angstrom')
    assert first.well_extension == 0.5
    assert second.well_extension is None
    assert first.ped_species == ['A+B=WA', 'C+D=WA']
    assert second.ped_species is None
    assert first.micro_ener == pytest.approx((0.0, 200.0, 1.0))
    assert second.micro_ener == (None, 150.0, None)
    for line in a_lines:
        assert line in tpls[0], line
    for line in b_lines:
        assert line in tpls[1], line

    # A bare WellExtension keyword means 0.0.
    sop, _, reader = read(tmp_path, mess_file(
        well('W'), header=['WellExtension ! no value\n']))
    assert_clean(reader)
    assert sop.pes_file_data[0].well_extension == 0.0


def test_side_output_keys_become_placeholders(tmp_path) -> None:
    """RateOutput / PEDOutput / MicroRateOutput lines become
    ``{__output__.<kind>}`` placeholders; commented ones stay raw."""
    header = ['RateOutput rate.out\n', 'PEDOutput ped.out\n',
              'MicroRateOutput  ke.out\n', '!LogOutput me.log\n',
              '!RateOutput me.out\n']
    _, tpls, reader = read(tmp_path, mess_file(well('W'), header=header))
    assert_clean(reader)
    assert 'RateOutput {__output__.rate}\n' in tpls[0]
    assert 'PEDOutput {__output__.ped}\n' in tpls[0]
    assert 'MicroRateOutput {__output__.micro}\n' in tpls[0]
    assert '!LogOutput me.log\n' in tpls[0]
    assert '!RateOutput me.out\n' in tpls[0]


# ---------------------------------------------------------------------------
# R7c-R7d: collider lines (Factor, Power, Epsilons, Sigmas, Masses)
# ---------------------------------------------------------------------------
_COLLIDER_LINES = ('factor', 'power', 'eps', 'sig', 'masses')
_COLLIDER_LABEL = {'factor': 'Factor', 'power': 'Power', 'eps': 'Epsilons',
                   'sig': 'Sigmas', 'masses': 'Masses'}


@pytest.mark.parametrize('line', _COLLIDER_LINES)
def test_collider_line_missing_from_some_files_stops(tmp_path, line) -> None:
    """A collider line present in some files only stops with one presence
    error (both orders); absent from every file is fine."""
    label = _COLLIDER_LABEL[line]
    for case, (kw_a, kw_b) in (('missing_in_b', ({}, {line: None})),
                               ('missing_in_a', ({line: None}, {}))):
        sub = tmp_path / case
        sub.mkdir()
        _, _, reader = read(sub, mess_file(well('WA'), **kw_a),
                            mess_file(well('WB'), **kw_b))
        assert_one_stop(reader, f'{label} is set in', 'absent from')

    if line in ('eps', 'sig', 'masses'):
        sub = tmp_path / 'absent_everywhere'
        sub.mkdir()
        sop, _, reader = read(sub, mess_file(well('WA'), **{line: None}),
                              mess_file(well('WB'), **{line: None}))
        assert_clean(reader)
        if line == 'eps':
            assert sop.epsilons == []
            assert not any(n.startswith('__epsilon')
                           for n in sop.parameters_names)


@pytest.mark.parametrize('line, first, other, needle', [
    ('eps', '7.95 206.15', '8.0 206.15', 'Different epsilon 0 (collider)'),
    ('sig', '2.715 4.71', '2.8 4.71', 'Different sigma 0 (collider)'),
    ('masses', '4.0 77.0', '28.0 77.0', 'Different bath mass (collider'),
    ('factor', '200', '250', 'Different factor in'),
    ('power', '0.85', '0.9', 'Different power in'),
])
def test_collider_value_differs_stops(tmp_path, line, first, other,
                                      needle) -> None:
    """The collider value (index 0) of Epsilons / Sigmas / Masses and the
    Factor / Power values must be the same in every file."""
    sop, _, reader = read(tmp_path, mess_file(well('WA'), **{line: first}),
                          mess_file(well('WB'), **{line: other}))
    msg = assert_one_stop(reader, needle)
    assert reader.filenames[1] in msg
    if line == 'masses':
        assert '4.0' in msg and sop.masses == [4.0, 77.0]


def test_collider_second_values_are_per_pes(tmp_path) -> None:
    """Index 1 of Epsilons / Sigmas / Masses differing between files is
    PES-specific: no stop, no warning; each file keeps its own masses."""
    sop, tpls, reader = read(
        tmp_path,
        mess_file(well('WA'), eps='7.95 206.15', sig='2.715 4.71',
                  masses='4.0 77.0'),
        mess_file(well('WB'), eps='7.95 300.0', sig='2.715 5.0',
                  masses='4.0 109.0'))
    assert_clean(reader)
    assert sop.epsilons == [7.95, 206.15, 300.0]
    assert sop.sigmas == [2.715, 4.71, 5.0]
    assert sop.masses == [4.0, 77.0]
    assert sop.pes_file_data[0].masses == [4.0, 77.0]
    assert sop.pes_file_data[1].masses == [4.0, 109.0]
    assert '      Masses[amu]  4.0 109.0\n' in tpls[1]
    assert any('kept for this PES' in m for m in log_of(reader).infos)


def test_lj_unit_token_and_number_count(tmp_path) -> None:
    """Epsilons[K] vs Epsilons[1/cm] stops (no conversion); the unit token
    is compared case-folded; fewer than two numbers stops; a third number
    is ignored."""
    _, _, reader = read(tmp_path, mess_file(well('WA')),
                        mess_file(well('WB'), eps_token='Epsilons[K]'))
    msg = assert_one_stop(reader, "Epsilons is given as 'Epsilons[K]'")
    assert reader.filenames[1] in msg

    sub = tmp_path / 'case'
    sub.mkdir()
    sop, _, reader = read(sub, mess_file(well('WA')),
                          mess_file(well('WB'),
                                    sig_token='Sigmas[Angstrom]'))
    assert_clean(reader)
    assert sop.sigmas == [2.715, 4.71, 4.71]

    for files in ([mess_file(well('WA'), eps='7.95')],
                  [mess_file(well('WA')), mess_file(well('WB'),
                                                    eps='7.95')]):
        sub = tmp_path / f'one_number_{len(files)}'
        sub.mkdir()
        _, _, reader = read(sub, *files)
        assert_one_stop(reader, 'Epsilons needs two values')

    sub = tmp_path / 'three_numbers'
    sub.mkdir()
    sop, tpls, reader = read(sub, mess_file(well('WA'),
                                            eps='7.95 206.15 999.0'))
    assert_clean(reader)
    assert sop.epsilons == [7.95, 206.15]
    assert 'Epsilons[1/cm] {SOP.r_epsilons_pes[0]}\n' in tpls[0]
    assert sop.r_epsilons_pes == ['  7.9500  206.1500']


# ---------------------------------------------------------------------------
# L1: Lennard-Jones layout [collider, file 0, file 1, ...]
# ---------------------------------------------------------------------------
def test_lj_second_values_per_pes_layout(tmp_path) -> None:
    """[A, B, C] with Epsilons 'c a', 'c b', 'c d' -> [c, a, b, d]; names
    __epsilon0..3 / __sigma0..3 in order; template k reads
    r_epsilons_pes[k]; swapping A and B swaps their slots."""
    def _three(order: str) -> list[list[str]]:
        eps = {'A': '10.0 1.0', 'B': '10.0 2.0', 'C': '10.0 4.0'}
        sig = {'A': '3.0 0.1', 'B': '3.0 0.2', 'C': '3.0 0.4'}
        return [mess_file(well(f'W{x}'), eps=eps[x], sig=sig[x])
                for x in order]

    sop, tpls, reader = read(tmp_path, *_three('ABC'))
    assert_clean(reader)
    assert sop.epsilons == [10.0, 1.0, 2.0, 4.0]
    assert sop.sigmas == [3.0, 0.1, 0.2, 0.4]
    names = [n for n in sop.parameters_names
             if n.startswith(('__epsilon', '__sigma'))]
    assert names == ['__epsilon0', '__epsilon1', '__epsilon2', '__epsilon3',
                     '__sigma0', '__sigma1', '__sigma2', '__sigma3']
    for k, x in enumerate((1.0, 2.0, 4.0)):
        assert sop.r_epsilons_pes[k] == f' {10.0: 7.4f} {x: 7.4f}'
        assert f'Epsilons[1/cm] {{SOP.r_epsilons_pes[{k}]}}\n' in tpls[k]
        assert f'Sigmas[angstrom] {{SOP.r_sigmas_pes[{k}]}}\n' in tpls[k]
        assert sop.pes_file_data[k].masses == [4.0, 77.0]

    sub = tmp_path / 'bac'
    sub.mkdir()
    sop, _, reader = read(sub, *_three('BAC'))
    assert_clean(reader)
    assert sop.epsilons == [10.0, 2.0, 1.0, 4.0]

    sub = tmp_path / 'single'
    sub.mkdir()
    sop, _, reader = read(sub, mess_file(well('W')))
    assert sop.epsilons == [7.95, 206.15]
    assert [n for n in sop.parameters_names if n.startswith('__epsilon')
            ] == ['__epsilon0', '__epsilon1']
    # Single file: the per-PES pair is the historical r_epsilons string.
    assert sop.r_epsilons_pes == [sop.r_epsilons]
    assert sop.r_sigmas_pes == [sop.r_sigmas]


# ---------------------------------------------------------------------------
# R8: AutoMech fake wells need no mechanism species
# ---------------------------------------------------------------------------
def test_fake_well_labels_exempt_from_mechanism(tmp_path) -> None:
    """force_new_molecules False, mechanism = fragment names only:
    FakeW- and FW- wells shared by two files read cleanly; a regular well
    missing from the mechanism still stops."""
    frags = [fragment('A'), fragment('B')]
    first = mess_file(bimol('A+B', frags), well('FakeW-A+B', -1.0),
                      well('FW-A+B', -1.5))
    second = mess_file(bimol('A+B', frags), well('FakeW-A+B', -1.0),
                       well('FW-A+B', -1.5))
    sop, _, reader = read(tmp_path, first, second, species=['A', 'B'])
    assert_clean(reader)
    assert sop.items['FW-A+B'].pes_ids == [0, 1]
    assert is_fake_well_label('FakeW-A+B') and is_fake_well_label('FW-X')
    assert not is_fake_well_label('W-FakeW')

    sub = tmp_path / 'regular'
    sub.mkdir()
    _, _, reader = read(sub, mess_file(bimol('A+B', frags), well('REAL')),
                        species=['A', 'B'])
    assert_one_stop(reader, "Well 'REAL' from MESS input is not present",
                    'force_new_molecules')


# ---------------------------------------------------------------------------
# R9: Atom fragments, PotentialSpline rotors, fragment density
# ---------------------------------------------------------------------------
def test_atom_fragments(tmp_path) -> None:
    """Atom H / O / a non-element label with a hydrogen mass: element and
    mass stored, one-atom structure, no frequency; parameters_names and
    the PST barrier on +H build."""
    lines = mess_file(
        bimol('A+H', [fragment('A'), atom('H', density=True)], 0.0),
        bimol('A+O', [fragment('A'), atom('O', '15.99491461957')], 2.0),
        bimol('A+Hx', [fragment('A'), atom('Hx', '1.008')], 3.0),
        well('FakeW-A+H', -1.0),
        pst('A+H=FakeW-A+H', 'A+H', 'FakeW-A+H', 0.0))
    sop, tpls, reader = read(tmp_path, lines)
    assert_clean(reader)
    for label, element, mass in (('H', 'H', 1.00782503223),
                                 ('O', 'O', 15.99491461957),
                                 ('Hx', 'H', 1.008)):
        item = sop.items[label]
        assert item.is_atom is True, label
        assert item.atom_mass == mass
        assert list(item.structure.get_chemical_symbols()) == [element]
        assert len(item.frequencies) == 0
        assert item.elec_levels == [[0.0, 2]]
    assert sop.items['A'].is_atom is False
    assert sop.items['A+H'].fragment_density == [False, True]
    assert '    Atom\n' in tpls[0]
    assert '      Mass[amu]  1.00782503223\n' in tpls[0]
    assert 'A+H=FakeW-A+H__sfc' in sop.parameters_names
    assert len(sop.items['A+H=FakeW-A+H'].frequencies) == 1


def test_atom_errors_stop(tmp_path) -> None:
    """An Atom whose label and mass match no element, or without a
    Mass[amu] line, stops."""
    _, _, reader = read(tmp_path, mess_file(
        bimol('A+Q', [fragment('A'), atom('Q', '7.5')])))
    assert_one_stop(reader, 'Atom Q in', 'no chemical element matches')
    sub = tmp_path / 'no_mass'
    sub.mkdir()
    _, _, reader = read(sub, mess_file(
        bimol('A+H', [fragment('A'), atom('H', None)])))
    assert_one_stop(reader, 'Atom H has no Mass[amu] line')


def test_potential_spline_rotor(tmp_path) -> None:
    """PotentialSpline: angles stored, energies in the scan, angles kept
    verbatim in the template, energies replaced by r_scan; a
    Potential[kcal/mol] rotor keeps spline_angles None."""
    lines = mess_file(well('W', rotors=[
        rotor(scan='0.0000 1.5580 3.2660 1.6201',
              angles='0.00 30.00 60.00 90.00', symmetry=3),
        rotor(group='1', axis='2 1')]))
    sop, tpls, reader = read(tmp_path, lines)
    assert_clean(reader)
    spline, plain = sop.items['W'].h_rotors
    assert spline.spline_angles == [0.0, 30.0, 60.0, 90.0]
    assert spline.is_spline is True
    assert list(spline.scan) == pytest.approx([0.0, 1.558, 3.266, 1.6201])
    assert plain.spline_angles is None and plain.is_spline is False
    tpl = tpls[0]
    idx = tpl.index('        PotentialSpline[kcal/mol]  4  3\n')
    assert tpl[idx + 1] == '          0.00 30.00 60.00 90.00\n'
    assert tpl[idx + 2] == ' {W.r_scan(0)}\n'
    assert ' {W.r_scan(1)}\n' in tpl
    # Spline energies keep 4 decimals, Potential grids 3.
    assert sop.items['W'].r_scan(0) == \
        '   0.0000   1.5580   3.2660   1.6201\n'
    assert sop.items['W'].r_scan(1) == '  0.000  0.500  1.000  0.500\n'


def test_potential_spline_mixed_line_raises(tmp_path) -> None:
    """A spline line holding angles and energies together is rejected."""
    bad = rotor(scan='0.0 1.0 2.0 1.0', angles='0 30 60 90')
    bad[-3] = '          0 30 60 90 0.0\n'
    with pytest.raises(TypeError, match='mixes angles and energies'):
        read(tmp_path, mess_file(well('W', rotors=[bad])))


def test_fragment_density_per_slot(tmp_path) -> None:
    """density on one slot, both slots, none; the template keeps the
    keyword only where it was."""
    lines = mess_file(
        bimol('A+B', [fragment('A', density=True), fragment('B')]),
        bimol('C+D', [fragment('C', density=True),
                      fragment('D', density=True)], 1.0),
        bimol('E+F', [fragment('E'), fragment('F')], 2.0))
    sop, tpls, reader = read(tmp_path, lines)
    assert_clean(reader)
    assert sop.items['A+B'].fragment_density == [True, False]
    assert sop.items['C+D'].fragment_density == [True, True]
    assert sop.items['E+F'].fragment_density == [False, False]
    assert sop.items['A+B'].density_of(0) is True
    assert sop.items['A+B'].density_of(5) is False
    assert 'Fragment {A.name} density\n' in tpls[0]
    assert 'Fragment {B.name}\n' in tpls[0]


# ---------------------------------------------------------------------------
# R10: a file holding only shared items keeps its slot
# ---------------------------------------------------------------------------
def test_all_shared_file_keeps_its_slot(tmp_path) -> None:
    """File 1 holds only items of file 0 plus a saddle of its own: it keeps
    PES id 1, its template, and LJ index 2."""
    first = mess_file(well('L', 0.0), well('R', -1.0),
                      bimol('A+B', [fragment('A'), fragment('B')], 3.0))
    second = mess_file(well('L', 0.0), well('R', -1.0),
                       bimol('A+B', [fragment('A'), fragment('B')], 3.0),
                       saddle('L=R', 'L', 'R', 5.0))
    sop, tpls, reader = read(tmp_path, first, second)
    assert_clean(reader)
    assert sop.pes_ids == [0, 1]
    assert len(tpls) == len(sop.pes_ids)
    assert [w.name for w in sop.wells_in(1)] == ['L', 'R']
    assert [b.name for b in sop.bimols_in(1)] == ['A+B']
    assert len(sop.epsilons) == len(sop.pes_ids) + 1


# ---------------------------------------------------------------------------
# R11: SOP DB keeps multi-PES ids and symbol-bearing item names
# ---------------------------------------------------------------------------
def test_sop_db_multi_pes_ids_and_symbol_columns(tmp_path) -> None:
    """The item/PES table round-trips the shared items' [0, 1]; columns
    named after labels with '+', '=' and '-' round-trip their values."""
    from kimeco.database.sop_db import SOP_DB
    from kimeco.logger_config import KMOLogger

    sop, _, reader = read(tmp_path, *two_pes_shared())
    assert_clean(reader)
    db_dir = tmp_path / 'db'
    db_dir.mkdir()
    klog = KMOLogger(filename=str(db_dir / 'sop_db.log'))
    db = SOP_DB(sop=sop, name='MULTI_PES', path=str(db_dir), klog=klog)
    assert db.get_item_pes_ids()['FakeW-A+B'] == (0, 1)
    assert db.get_item_pes_ids()['A+B=FakeW-A+B'] == (0, 1)
    assert db.get_item_pes_ids()['U1'] == (1,)
    reopened = SOP_DB(sop=sop, name='MULTI_PES', path=str(db_dir),
                      klog=klog)
    assert reopened.get_item_pes_ids() == sop.item_pes_ids
    for column in ('FakeW-A+B__we', 'W=FakeW-A+B__be',
                   'A+B=FakeW-A+B__sfc'):
        assert column in sop.parameters_names


def test_read_keeps_types(tmp_path) -> None:
    """Sanity: the shared objects are of the expected classes."""
    sop, _, _ = read(tmp_path, *two_pes_shared())
    assert isinstance(sop.items['FakeW-A+B'], Well)
    assert isinstance(sop.items['A+B'], Bimolecular)
    assert isinstance(sop.items['A+B=FakeW-A+B'], Barrier)
    assert sop.items['A+B=FakeW-A+B'].tst_level == 'EJ'
    assert np.array_equal(sop.items['A']._freq, np.array([3700.0]))
