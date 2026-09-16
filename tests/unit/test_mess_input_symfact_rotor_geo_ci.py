"""CI-safe tests for the rigid-rotor ``SymmetryFactor`` and the per-rotor
``Geometry[angstrom]`` block captured by the MESS reader.

Contract exercised here (black-box, synthetic in-memory MESS files):

* ``SymmetryFactor`` under a ``Core RigidRotor`` lands on
  ``Well.sym_factor`` (wells and bimolecular fragments) or on
  ``Barrier._symFact`` (saddle points, exposed via ``Barrier.symFact``);
  both default to ``1.0`` when the keyword is absent;
* the ``SymmetryFactor`` line is copied verbatim to the template;
* a ``Rotor Hindered`` block that carries its own ``Geometry[angstrom] N``
  yields ``HinRotor.geo`` as ``N`` rows of ``[symbol, x, y, z]`` (floats,
  angstrom) - ``None`` when the rotor has no geometry; the rows are copied
  verbatim to the template;
* ``Well.add_hrotor``'s consistency guard (same group/axis must carry the
  same parameters) now includes the geometry.

No MESS binary, database or automech install is needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_input import MessInputReader
from kimeco.rotors.hrotor import HinRotor
from kimeco.well import Well

DME_ROOT = Path(__file__).resolve().parent.parent / 'parse_pes' / 'dme'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _settings() -> dict[str, Any]:
    return {
        'init_loc': str(DME_ROOT),
        'mess_inputs': ['mess_roo_L3.inp'],
        'n_exp': 1,
        'score_sp': [],
        'freq_mode': FreqMode.BATCH,
        'rc_temp': [],
        'rc_pres': [],
        'pres_unit': 'bar',
        'force_new_molecules': True,
    }


def _read(tmp_path: Path, lines: list[str]) -> tuple[Any, list[str]]:
    reader = MessInputReader(
        settings=_settings(),
        mechanism_species=[],
        klog=KMOLogger(filename=str(tmp_path / 'symfact_geo.log')),
        postprocess=False,
    )
    reader.pes_files = [list(lines)]
    sop, tpls = reader.read()
    assert reader._trigger_stop is False
    return sop, tpls[0]


_GEO_ROWS = [
    '        C -0.592967 -1.067126 -0.288023\n',
    '        H -0.046952 -1.903469 -0.740852\n',
    '        O  0.116508 -0.547138  0.818203\n',
]
_GEO_EXPECTED = [
    ['C', -0.592967, -1.067126, -0.288023],
    ['H', -0.046952, -1.903469, -0.740852],
    ['O', 0.116508, -0.547138, 0.818203],
]


def _rotor(with_geo: bool, symmetry: int = 3,
           potential: str = '0.00 0.20 0.68 1.20',
           group: str = '2 3', axis: str = '1 2') -> list[str]:
    body = ['      Rotor     Hindered\n']
    if with_geo:
        body.append('        Geometry[angstrom]        3\n')
        body.extend(_GEO_ROWS)
    body += [
        '        ThermalPowerMax           50.\n',
        f'        Group                     {group}\n',
        f'        Axis                      {axis}\n',
        f'        Symmetry                  {symmetry}\n',
        f'        Potential[kcal/mol]       {len(potential.split())}\n',
        f'        {potential}\n',
        '      End ! Rotor\n',
    ]
    return body


def _well(name: str, symfact: str | None, rotors: list[list[str]] = ()
          ) -> list[str]:
    lines = [
        f'  Well       {name}\n',
        '    Species\n',
        '      RRHO\n',
        '        Geometry[angstrom]            2\n',
        '        O 0.0 0.0 0.0\n',
        '        O 0.0 0.0 1.2\n',
        '        Core   RigidRotor\n',
    ]
    if symfact is not None:
        lines.append(f'          SymmetryFactor              {symfact}\n')
    lines += [
        '        End ! Core\n',
        '        Frequencies[1/cm]             1\n',
        '          1500.0\n',
    ]
    for rot in rotors:
        lines.extend(rot)
    lines += [
        '        ZeroEnergy[kcal/mol]        0.0\n',
        '      End ! RRHO\n',
        '  End ! Well\n',
    ]
    return lines


def _fragment(name: str, symfact: str | None,
              rotors: list[list[str]] = ()) -> list[str]:
    lines = [
        f'    Fragment       {name}\n',
        '      RRHO\n',
        '        Geometry[angstrom]            2\n',
        '        O 0.0 0.0 0.0\n',
        '        H 0.0 0.0 0.97\n',
        '        Core   RigidRotor\n',
    ]
    if symfact is not None:
        lines.append(f'          SymmetryFactor              {symfact}\n')
    lines += [
        '        End ! Core\n',
        '        Frequencies[1/cm]             1\n',
        '          3700.0\n',
    ]
    for rot in rotors:
        lines.extend(rot)
    lines += [
        '        ZeroEnergy[kcal/mol]        0.0\n',
        '      End ! RRHO\n',
    ]
    return lines


def _bimol(name: str, frags: list[list[str]]) -> list[str]:
    lines = [f'  Bimolecular       {name}\n']
    for frag in frags:
        lines.extend(frag)
    lines += [
        '    GroundEnergy[kcal/mol]        10.0\n',
        '  End ! Bimolecular\n',
    ]
    return lines


def _saddle(name: str, lside: str, rside: str, symfact: str | None,
            rotors: list[list[str]] = ()) -> list[str]:
    lines = [
        f'  Barrier       {name} {lside} {rside}\n',
        '    RRHO\n',
        '      Geometry[angstrom]            2\n',
        '        O 0.0 0.0 0.0\n',
        '        O 0.0 0.0 1.3\n',
        '      Core   RigidRotor\n',
    ]
    if symfact is not None:
        lines.append(f'        SymmetryFactor            {symfact}\n')
    lines += [
        '      End ! Core\n',
        '      Frequencies[1/cm]             1\n',
        '        1200.0\n',
    ]
    for rot in rotors:
        lines.extend(rot)
    lines += [
        '      ZeroEnergy[kcal/mol]        20.0\n',
        '    End ! RRHO\n',
        '  End ! Barrier\n',
    ]
    return lines


# ---------------------------------------------------------------------------
# B1-B6: SymmetryFactor on wells, fragments and saddle points
# ---------------------------------------------------------------------------
def test_b1_well_symmetry_factor_captured(tmp_path) -> None:
    sop, _ = _read(tmp_path, _well('W1', '2.0'))
    assert sop.items['W1'].sym_factor == 2.0


def test_b2_well_symmetry_factor_defaults_to_one(tmp_path) -> None:
    sop, _ = _read(tmp_path, _well('W1', None))
    assert sop.items['W1'].sym_factor == 1.0


def test_b3_saddle_symmetry_factor_captured(tmp_path) -> None:
    lines = _well('WA', '1.0') + _well('WB', '1.0')
    lines += _saddle('TS', 'WA', 'WB', '0.5')
    sop, _ = _read(tmp_path, lines)
    bar = sop.items['TS']
    assert isinstance(bar, Barrier)
    assert bar._symFact == 0.5
    assert bar.symFact == 0.5  # sfc is still 1.0
    # The wells are not touched by the saddle keyword.
    assert sop.items['WA'].sym_factor == 1.0
    assert sop.items['WB'].sym_factor == 1.0


def test_b4_saddle_symmetry_factor_defaults_to_one(tmp_path) -> None:
    lines = _well('WA', None) + _well('WB', None)
    lines += _saddle('TS', 'WA', 'WB', None)
    sop, _ = _read(tmp_path, lines)
    assert sop.items['TS'].symFact == 1.0


def test_b5_fragment_symmetry_factor_targets_the_fragment(tmp_path) -> None:
    lines = _bimol('R+P', [_fragment('FA', '4.0'), _fragment('FB', '2.0')])
    sop, _ = _read(tmp_path, lines)
    bim = sop.items['R+P']
    assert isinstance(bim, Bimolecular)
    assert sop.items['FA'].sym_factor == 4.0
    assert sop.items['FB'].sym_factor == 2.0
    assert [f.sym_factor for f in bim.fragments] == [4.0, 2.0]
    # The Bimolecular container has no rigid-rotor core of its own.
    assert not hasattr(bim, 'sym_factor')


def test_b5b_symmetry_factor_after_fragment_goes_to_next_well(
        tmp_path) -> None:
    # A well parsed *after* a bimolecular must reset the fragment target.
    lines = _bimol('R+P', [_fragment('FA', '4.0'), _fragment('FB', '1.0')])
    lines += _well('W1', '3.0')
    sop, _ = _read(tmp_path, lines)
    assert sop.items['W1'].sym_factor == 3.0
    assert sop.items['FB'].sym_factor == 1.0


def test_b6_symmetry_factor_line_copied_verbatim_to_template(
        tmp_path) -> None:
    lines = _well('W1', '2.0')
    _, tpl = _read(tmp_path, lines)
    sym_line = next(ln for ln in lines if 'SymmetryFactor' in ln)
    assert tpl.count(sym_line) == 1
    # No placeholder was introduced for the keyword.
    assert not any('sym_factor' in ln for ln in tpl)


def test_b6b_symmetry_factor_stored_as_float(tmp_path) -> None:
    sop, _ = _read(tmp_path, _well('W1', '4'))
    assert sop.items['W1'].sym_factor == 4.0
    assert isinstance(sop.items['W1'].sym_factor, float)


# ---------------------------------------------------------------------------
# B7-B11: rotor-specific geometry
# ---------------------------------------------------------------------------
def test_b7_rotor_geometry_captured_as_symbol_xyz_rows(tmp_path) -> None:
    sop, _ = _read(tmp_path, _well('W1', '1.0', [_rotor(with_geo=True)]))
    rotors = sop.items['W1'].h_rotors
    assert len(rotors) == 1
    hr = rotors[0]
    assert hr.geo == _GEO_EXPECTED
    assert all(isinstance(v, float) for row in hr.geo for v in row[1:])
    # The rest of the rotor is unaffected by the geometry block.
    assert hr.group == [2, 3]
    assert hr.axis == [1, 2]
    assert hr.symmetry == 3
    assert hr.ThermalPowerMax == 50.0
    assert list(hr.scan) == pytest.approx([0.0, 0.20, 0.68, 1.20])


def test_b8_rotor_without_geometry_has_geo_none(tmp_path) -> None:
    sop, _ = _read(tmp_path, _well('W1', '1.0', [_rotor(with_geo=False)]))
    hr = sop.items['W1'].h_rotors[0]
    assert hr.geo is None


def test_b9_rotor_geometry_rows_copied_verbatim_to_template(
        tmp_path) -> None:
    lines = _well('W1', '1.0', [_rotor(with_geo=True)])
    _, tpl = _read(tmp_path, lines)
    assert '        Geometry[angstrom]        3\n' in tpl
    for row in _GEO_ROWS:
        assert tpl.count(row) == 1
    # The potential grid is still replaced by its placeholder.
    assert any('W1.r_scan(0)' in ln for ln in tpl)


def test_b10_two_rotors_one_with_geometry_one_without(tmp_path) -> None:
    rotors = [_rotor(with_geo=True, symmetry=3),
              _rotor(with_geo=False, symmetry=2, group='1', axis='2 3',
                     potential='0.00 0.16 0.22 0.01 0.17 1.01')]
    sop, tpl = _read(tmp_path, _well('W1', '1.0', rotors))
    hrs = sop.items['W1'].h_rotors
    assert len(hrs) == 2
    assert hrs[0].geo == _GEO_EXPECTED
    assert hrs[1].geo is None  # geometry does not leak across rotors
    assert [hr.symmetry for hr in hrs] == [3, 2]
    assert any('W1.r_scan(1)' in ln for ln in tpl)


def test_b11_fragment_rotor_geometry_lands_on_the_fragment(tmp_path) -> None:
    lines = _bimol('R+P', [_fragment('FA', '1.0', [_rotor(with_geo=True)]),
                           _fragment('FB', '1.0')])
    sop, _ = _read(tmp_path, lines)
    assert len(sop.items['FA'].h_rotors) == 1
    assert sop.items['FA'].h_rotors[0].geo == _GEO_EXPECTED
    assert sop.items['FB'].h_rotors == []


def test_b11b_saddle_rotor_geometry_lands_on_the_barrier(tmp_path) -> None:
    lines = _well('WA', '1.0') + _well('WB', '1.0')
    lines += _saddle('TS', 'WA', 'WB', '0.5', [_rotor(with_geo=True)])
    sop, _ = _read(tmp_path, lines)
    bar = sop.items['TS']
    assert bar.symFact == 0.5
    assert len(bar.h_rotors) == 1
    assert bar.h_rotors[0].geo == _GEO_EXPECTED
    assert sop.items['WA'].h_rotors == []


# ---------------------------------------------------------------------------
# B12-B13: object-level defaults and the duplicate-rotor guard
# ---------------------------------------------------------------------------
def test_b12_object_defaults() -> None:
    hr = HinRotor(ThermalPowerMax=10.0, group=[2], axis=[1, 2], symmetry=1,
                  scan=[0.0, 1.0], fexp=[], fcoef=[])
    assert hr.geo is None
    well = Well(name='W', pes_ids=[0])
    assert well.sym_factor == 1.0
    bar = Barrier(name='TS', lside=well, rside=Well(name='X', pes_ids=[0]),
                  pes_id=0)
    assert bar._symFact == 1.0
    assert bar.symFact == 1.0


def _add(well: Well, geo: Any) -> None:
    well.add_hrotor(10.0, [2], [1, 2], 1, [0.0, 1.0], [], [], geo=geo)


def test_b13_consistency_guard_accepts_identical_rotor_with_same_geo() -> None:
    # Same group/axis + identical parameters (geometry included) is the
    # "consistent re-declaration" path: accepted, no error.
    well = Well(name='W', pes_ids=[0])
    _add(well, _GEO_EXPECTED)
    _add(well, [list(r) for r in _GEO_EXPECTED])
    assert all(hr.geo == _GEO_EXPECTED for hr in well.h_rotors)


def test_b13b_consistency_guard_rejects_different_geo() -> None:
    well = Well(name='W', pes_ids=[0])
    _add(well, _GEO_EXPECTED)
    other = [list(r) for r in _GEO_EXPECTED]
    other[0][1] += 0.5
    with pytest.raises(ValueError, match='already has a rotor'):
        _add(well, other)
    assert len(well.h_rotors) == 1


def test_b13c_consistency_guard_rejects_geo_vs_no_geo() -> None:
    well = Well(name='W', pes_ids=[0])
    _add(well, None)
    with pytest.raises(ValueError, match='already has a rotor'):
        _add(well, _GEO_EXPECTED)
    assert len(well.h_rotors) == 1
    assert well.h_rotors[0].geo is None


def test_b13d_consistency_guard_without_geo_unchanged() -> None:
    # Pre-existing behaviour for geometry-less rotors is preserved.
    well = Well(name='W', pes_ids=[0])
    _add(well, None)
    _add(well, None)
    assert all(hr.geo is None for hr in well.h_rotors)
    with pytest.raises(ValueError, match='already has a rotor'):
        well.add_hrotor(10.0, [2], [1, 2], 2, [0.0, 1.0], [], [])
