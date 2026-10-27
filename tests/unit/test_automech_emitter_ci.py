"""CI-safe tests for the automech per-slot MESS driver emitter
(``AutomechKinWriter``).

These tests run without automech/``mess_io`` installed: the emitter only
*serializes* SOP data into a self-contained python driver script (it never
imports ``mess_io`` in the main process), so we assert on the emitted source
text, on the ``_build_payload`` dict and that the script ``compile()``s.

* Emitted script contract per PES shape and the hindered-rotor
  ``potential_form="fourier"`` form (fakes mirror the real accessor surface:
  SOP.wells_in / bimols_in / barriers / factor / power / epsilons / sigmas /
  temp / pres; Well, Bimolecular and Barrier attributes the serializer reads).
* Pressure-unit pass-through: the SOP stores pressures in bar and
  ``MessOutputReader`` indexes results against that very grid, so the grid
  reaches the driver **unconverted**, labelled with the SOP unit, as plain
  literals (an earlier bar -> atm conversion shifted 0.01 bar to 0.00987 and
  broke the output reader).
* Payload parity with the normal MESS input: symmetry factors, barrier
  rotors, rotor geometry, Lennard-Jones masses (``SOP.masses`` or the
  N2/heaviest-well heuristic plus a warning) and the global header keys.
"""
from __future__ import annotations

import ast
import inspect
import logging
import re
from typing import Any, cast

import pytest

from kimeco.writers import automech_kin
from kimeco.writers.automech_kin import AutomechKinWriter


# ===========================================================================
# Emitted script contract and hindered-rotor potential form
# ===========================================================================
# ---------------------------------------------------------------------------
# Doubles mirroring the real read-only accessor surface.
# ---------------------------------------------------------------------------
class _FakeStruct:
    """Minimal ASE-Atoms-like structure double."""

    def __init__(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)
        # Deterministic, non-degenerate coordinates.
        self._positions = [
            [float(i), float(i) + 0.1, float(i) + 0.2]
            for i in range(len(symbols))
        ]
        _mass = {'H': 1.008, 'C': 12.011, 'O': 15.999, 'N': 14.007}
        self._masses = [_mass.get(s, 10.0) for s in symbols]

    def get_chemical_symbols(self) -> list[str]:
        return list(self._symbols)

    def get_positions(self) -> list[list[float]]:
        return [list(p) for p in self._positions]

    def get_masses(self) -> list[float]:
        return list(self._masses)


class _FakeRotor:
    """Scan-based hindered rotor double (mess_io.rotor_hindered)."""

    def __init__(self, fourier: bool = False,
                 scan: list[float] | None = None) -> None:
        self.fourier = fourier
        self.scan = list(scan) if scan is not None else [0.0, 1.5, 3.0, 1.5]
        self.symmetry = 2
        self.ThermalPowerMax = 10.0
        self.group = [3, 4]
        self.axis = [1, 2]


class _FakeInternalRot:
    def __init__(self) -> None:
        self.group = [3, 4]
        self.axis = [1, 2]
        self.symmetry = 1
        self.gridsize = 100
        self.mes = 5
        self.pes = 5
        self.hamiltonsizemin = 11
        self.hamiltonsizemax = 13


class _FakeMultiRotor:
    def __init__(self) -> None:
        self.internal_rot = [_FakeInternalRot()]
        self.symFact = 1.0
        self.file = 'pot_surf.dat'
        self.iem = 100.0
        self.qlem = 200.0


class _FakeWell:
    def __init__(self,
                 name: str,
                 symbols: list[str],
                 energy: float = 0.0,
                 h_rotors: list[Any] | None = None,
                 m_rotors: list[Any] | None = None) -> None:
        self.name = name
        self.energy = energy
        self.structure = _FakeStruct(symbols)
        self.frequencies = [500.0, 1500.0, 3000.0]
        self.elec_levels = [[0.0, 1]]
        self.h_rotors = h_rotors or []
        self.m_rotors = m_rotors or []
        self.dummy = False
        self.pes_ids = [0]


class _FakeBimolecular:
    def __init__(self, name: str, frag1: _FakeWell, frag2: _FakeWell,
                 energy: float = -5.0) -> None:
        self.name = name
        self.energy = energy
        self.fragments = [frag1, frag2]
        self.dummy = False
        self.pes_ids = [0]


class _FakeBarrier:
    def __init__(self,
                 name: str,
                 connected: list[Any],
                 barrierless: bool = False,
                 symbols: list[str] | None = None,
                 pes_ids: list[int] | None = None) -> None:
        self.name = name
        self.connected = connected
        self.barrierless = barrierless
        self.energy = 20.0
        self.frequencies = [400.0, 1200.0]
        self.elec_levels = [[0.0, 2]]
        self.h_rotors: list[Any] = []
        self.pes_ids = pes_ids if pes_ids is not None else [0]
        self.dummy = False
        if not barrierless:
            self.structure = _FakeStruct(symbols or ['C', 'H', 'O'])
            self.symFact = 1.0
            self.ifreq = -800.0
            self.r_lenergy = 20.0
            self.r_renergy = 15.0
        else:
            # phasespace path: symFact + pp/ppe, and NO 'file' attribute.
            self.symFact = 1.0
            self.pp = 10.0
            self.ppe = 6.0


class _FakeSOP:
    def __init__(self,
                 wells: list[_FakeWell],
                 bimols: list[_FakeBimolecular],
                 barriers: list[_FakeBarrier]) -> None:
        self._wells = wells
        self._bimols = bimols
        self.barriers = barriers
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = [300.0, 400.0]
        self.pres = [1.0, 10.0]

    def wells_in(self, pes_id: int) -> list[_FakeWell]:
        return [w for w in self._wells if pes_id in w.pes_ids]

    def bimols_in(self, pes_id: int) -> list[_FakeBimolecular]:
        return [b for b in self._bimols if pes_id in b.pes_ids]


# ---------------------------------------------------------------------------
# PES shape builders.
# ---------------------------------------------------------------------------
def _single_well() -> tuple[_FakeSOP, list[str]]:
    w = _FakeWell('W1', ['C', 'H', 'H', 'H'])
    prod = _FakeWell('P1', ['C', 'O'])
    bim = _FakeBimolecular('BIM1', prod, _FakeWell('P2', ['H']))
    bar = _FakeBarrier('TS1', connected=[w, bim])
    return _FakeSOP([w], [bim], [bar]), ['W1', 'BIM1']


def _multi_well() -> tuple[_FakeSOP, list[str]]:
    w1 = _FakeWell('WA', ['C', 'H', 'H'])
    w2 = _FakeWell('WB', ['C', 'O', 'H'])
    bar = _FakeBarrier('TSAB', connected=[w1, w2])
    return _FakeSOP([w1, w2], [], [bar]), ['WA', 'WB']


def _bimolecular_only() -> tuple[_FakeSOP, list[str]]:
    f1 = _FakeWell('F1', ['O', 'H'])
    f2 = _FakeWell('F2', ['C', 'H', 'H', 'H'])
    f3 = _FakeWell('F3', ['O'])
    f4 = _FakeWell('F4', ['C', 'H', 'H', 'H', 'H'])
    r = _FakeBimolecular('R', f1, f2)
    p = _FakeBimolecular('P', f3, f4)
    # The barrierless serializer prefers a real Bimolecular side (isinstance);
    # with fake doubles it falls back to connected[*].structure, so expose
    # geometry-bearing endpoints named after the two bimoleculars.
    end_r = _FakeWell('R', ['O', 'H', 'C', 'H', 'H', 'H'])
    end_p = _FakeWell('P', ['O', 'C', 'H', 'H', 'H', 'H', 'H'])
    bar = _FakeBarrier('TSbl', connected=[end_r, end_p], barrierless=True)
    return _FakeSOP([], [r, p], [bar]), ['R', 'P']


def _abstraction() -> tuple[_FakeSOP, list[str]]:
    f1 = _FakeWell('OH', ['O', 'H'])
    f2 = _FakeWell('CH4', ['C', 'H', 'H', 'H', 'H'])
    f3 = _FakeWell('H2O', ['O', 'H', 'H'])
    f4 = _FakeWell('CH3', ['C', 'H', 'H', 'H'])
    r = _FakeBimolecular('REAC', f1, f2)
    p = _FakeBimolecular('PROD', f3, f4)
    bar = _FakeBarrier('TSabs', connected=[r, p],
                       symbols=['C', 'H', 'H', 'H', 'H', 'O', 'H'])
    return _FakeSOP([], [r, p], [bar]), ['REAC', 'PROD']


def _rotor_pes() -> tuple[_FakeSOP, list[str]]:
    w = _FakeWell(
        'WR',
        ['C', 'C', 'H', 'H', 'H', 'H'],
        h_rotors=[_FakeRotor(fourier=False), _FakeRotor(fourier=True)],
        m_rotors=[_FakeMultiRotor()],
    )
    prod = _FakeWell('PR', ['C', 'O'])
    bim = _FakeBimolecular('BR', prod, _FakeWell('HR', ['H']))
    bar = _FakeBarrier('TSR', connected=[w, bim],
                       symbols=['C', 'C', 'H', 'H'])
    return _FakeSOP([w], [bim], [bar]), ['WR', 'BR']


def _two_point_rotor_pes() -> tuple[_FakeSOP, list[str]]:
    # C2H5-like well with a single scan-based rotor holding only two grid
    # points (no Fourier rotor, no multirotor): the smallest non-empty
    # potential grid the serializer has to carry through the template.
    w = _FakeWell(
        'W2P',
        ['C', 'C', 'H', 'H', 'H', 'H', 'H'],
        h_rotors=[_FakeRotor(scan=[0.0, 2.7])],
    )
    prod = _FakeWell('P2P', ['C', 'O'])
    bim = _FakeBimolecular('B2P', prod, _FakeWell('H2P', ['H']))
    bar = _FakeBarrier('TS2P', connected=[w, bim],
                       symbols=['C', 'C', 'H', 'H'])
    return _FakeSOP([w], [bim], [bar]), ['W2P', 'B2P']


_SHAPES = {
    'single_well': _single_well,
    'multi_well': _multi_well,
    'bimolecular_only': _bimolecular_only,
    'abstraction': _abstraction,
    'hindered_multi_rotor': _rotor_pes,
    'two_point_scan_rotor': _two_point_rotor_pes,
}


def _emit(tmp_path, builder) -> tuple[str, list[str]]:
    sop, species = builder()
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0)
    filename = 'G0000E0001P03.py'
    writer.write(loc=str(tmp_path), filename=filename)
    script = (tmp_path / filename).read_text()
    return script, species


def test_emitted_script_contract_for_every_shape(tmp_path) -> None:
    """For every PES shape the emitted driver compiles (mess_io is never
    imported or executed), uses only the public mess_io API, references no
    database and names every SOP species. A bimolecular-only PES serializes
    the barrierless phasespace kind (no 'file' attr on the barrier)."""
    failures: list[str] = []
    scripts: dict[str, str] = {}
    for shape in sorted(_SHAPES):
        loc = tmp_path / shape
        loc.mkdir()
        script, species = _emit(loc, _SHAPES[shape])
        scripts[shape] = script
        try:
            compile(script, f'{shape}.py', 'exec')
        except SyntaxError as exc:
            failures.append(f'{shape}: does not compile: {exc}')
        if 'from mess_io.writer import' not in script:
            failures.append(f'{shape}: no public mess_io.writer import')
        if 'from mess_io import well_lumped_input_file' not in script:
            failures.append(f'{shape}: no well_lumped_input_file import')
        if 'mess_io._' in script:
            failures.append(f'{shape}: private mess_io internals leaked')
        lowered = script.lower()
        for token in ('kin_db', 'get_rates_for_kin_id', 'sqlite',
                      'kimeco.database'):
            if token in lowered:
                failures.append(f'{shape}: database token {token!r}')
        if 'KIN_DB' in script:
            failures.append(f'{shape}: KIN_DB referenced')
        missing = [name for name in species if repr(name) not in script]
        if missing:
            failures.append(f'{shape}: species {missing} not in the script')
    assert not failures, '\n'.join(failures)
    assert "'phasespace'" in scripts['bimolecular_only']


# ---------------------------------------------------------------------------
# Hindered-rotor potential form: rotor_hindered(..., potential_form="fourier")
# ---------------------------------------------------------------------------
_FOURIER_KWARG = 'potential_form="fourier"'


def _hind_rot_str_source(script: str) -> str:
    """Return the emitted source of ``_hind_rot_str`` only."""
    start = script.index('def _hind_rot_str')
    end = script.index('def _int_rot_str')
    assert start < end
    return script[start:end]


def _payload_wells(script: str) -> dict[str, dict[str, Any]]:
    """Parse the embedded ``PES_PAYLOAD`` literal and index wells by label."""
    line = next(ln for ln in script.splitlines()
                if ln.startswith('PES_PAYLOAD = '))
    payload = ast.literal_eval(line[len('PES_PAYLOAD = '):])
    return {w['label']: w for w in payload['wells']}


def test_hindered_rotor_payload_and_fourier_form(tmp_path) -> None:
    """Rotor PES (scan rotor kept, Fourier-flag rotor skipped, multirotor
    file as a bare literal) and the two-point scan rotor both request
    ``potential_form="fourier"`` and never PotentialSpline; the kwarg sits
    exactly once in ``_hind_rot_str`` next to ``potential=pot``; the
    two-point grid is serialized; a well whose only rotor is Fourier-flagged
    is dropped from the payload."""
    for label, builder in (('hindered_multi_rotor', _rotor_pes),
                           ('two_point_scan_rotor', _two_point_rotor_pes)):
        loc = tmp_path / label
        loc.mkdir()
        script, _ = _emit(loc, builder)
        assert _FOURIER_KWARG in script, label
        # The spline form (mess_io default) must not be requested anywhere.
        assert 'PotentialSpline' not in script, label
        compile(script, f'{label}.py', 'exec')

    script, _ = _emit(tmp_path / 'hindered_multi_rotor', _rotor_pes)
    # Multirotor potential-surface file is referenced as a bare literal.
    assert "'pot_surf.dat'" in script
    body = _hind_rot_str_source(script)
    assert body.count(_FOURIER_KWARG) == 1
    # The potential grid is still forwarded alongside the new form kwarg.
    assert 'potential=pot' in body

    # symmetry 2, two scan points -> step = (360 / 2) / 2 = 90 degrees.
    script, species = _emit(tmp_path / 'two_point_scan_rotor',
                            _two_point_rotor_pes)
    assert species == ['W2P', 'B2P']
    expected = '[[0.0, 0.0], [90.0, 2.7]]'
    if expected not in script:
        # Whitespace-tolerant fallback in case repr formatting changes.
        pattern = re.compile(
            r'\[\s*\[\s*0\.0\s*,\s*0\.0\s*\]\s*,'
            r'\s*\[\s*90\.0\s*,\s*2\.7\s*\]\s*\]')
        assert pattern.search(script), 'two-point potential grid not emitted'
    rotors = _payload_wells(script)['W2P']['hind_rotors']
    assert len(rotors) == 1
    assert rotors[0]['potential'] == [[0.0, 0.0], [90.0, 2.7]]
    assert rotors[0]['symmetry'] == 2

    # A well whose only hindered rotor is flagged ``fourier`` carries no scan
    # grid: it is dropped from the payload, independently of the
    # potential_form requested in the template.
    def _fourier_only() -> tuple[_FakeSOP, list[str]]:
        w = _FakeWell('WF', ['C', 'C', 'H', 'H', 'H', 'H'],
                      h_rotors=[_FakeRotor(fourier=True)])
        prod = _FakeWell('PF', ['C', 'O'])
        bim = _FakeBimolecular('BF', prod, _FakeWell('HF', ['H']))
        bar = _FakeBarrier('TSF', connected=[w, bim],
                           symbols=['C', 'C', 'H', 'H'])
        return _FakeSOP([w], [bim], [bar]), ['WF', 'BF']

    loc = tmp_path / 'fourier_only'
    loc.mkdir()
    script, _ = _emit(loc, _fourier_only)
    assert _payload_wells(script)['WF']['hind_rotors'] == []
    assert _FOURIER_KWARG in script
    compile(script, 'fourier_only.py', 'exec')


def test_no_rotor_shape_still_emits_fourier_form(tmp_path) -> None:
    # The kwarg lives in the static template, so it is present even when no
    # species carries a hindered rotor.
    script, _ = _emit(tmp_path, _single_well)
    assert _FOURIER_KWARG in script
    assert 'PotentialSpline' not in script
    wells = _payload_wells(script)
    assert all(w['hind_rotors'] == [] for w in wells.values())


# ===========================================================================
# Pressure-unit pass-through (grid unconverted, plain literals)
# ===========================================================================
class _MinimalSOP:
    """Smallest SOP surface ``_build_payload`` reads (no species needed)."""

    def __init__(self, pres: list[float], temp: list[float],
                 pres_unit: str | None = 'bar') -> None:
        self.barriers: list[Any] = []
        self.factor = 200.0
        self.power = 0.85
        self.epsilons = [100.0, 200.0]
        self.sigmas = [3.0, 4.0]
        self.temp = list(temp)
        self.pres = list(pres)
        if pres_unit is not None:
            self.pres_unit = pres_unit

    def wells_in(self, pes_id: int) -> list[Any]:
        return []

    def bimols_in(self, pes_id: int) -> list[Any]:
        return []


def _grid_writer(pres: list[float],
            temp: list[float] | None = None,
            pres_unit: str | None = 'bar') -> AutomechKinWriter:
    sop = _MinimalSOP(pres=pres, temp=temp or [500.0, 1000.0],
                      pres_unit=pres_unit)
    return AutomechKinWriter(sop=cast(Any, sop), pes_id=0)


def _emit_grid(tmp_path, pres: list[float],
          temp: list[float] | None = None,
          pres_unit: str | None = 'bar') -> str:
    writer = _grid_writer(pres, temp, pres_unit)
    filename = 'G0000E0001P03.py'
    writer.write(loc=str(tmp_path), filename=filename)
    return (tmp_path / filename).read_text()


def _literal(script: str, name: str) -> Any:
    """Extract a module-level literal assignment from the emitted script."""
    for node in ast.parse(script).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name
                for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f'{name} not assigned at module level')


def _assign_node(script: str, name: str) -> ast.expr:
    for node in ast.parse(script).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name
                for t in node.targets):
            return node.value
    raise AssertionError(f'{name} not assigned at module level')


# ---------------------------------------------------------------------------
# Standard contract: the grid is passed through, never converted
# ---------------------------------------------------------------------------
def test_payload_grid_is_the_sop_grid_unconverted(tmp_path) -> None:
    """The payload grid is SOP.pres verbatim (no factor, no rounding, plain
    floats, ints coerced, zero kept, order kept); 0.01 bar stays bit-identical
    (regression for "0.00987 is not in list"); temperatures are not converted;
    the postprocessing sub-grid takes the same path; an empty sub-grid gives []
    and the default lump pressure 1.0."""
    # -- test_grid_pres_is_the_sop_grid_unchanged
    _failures = []
    for pres in [
        [1.0],
        [0.01, 0.1, 1.0, 10.0],
        [1.01325, 100.0],
    ]:
        try:
            payload = _grid_writer(pres)._build_payload()
            # Exact equality, not approx: no conversion factor may be applied.
            assert payload['grid_pres'] == pres
        except AssertionError as _exc:
            _failures.append(
                f"test_grid_pres_is_the_sop_grid_unchanged"
                f"[pres={pres!r}]: {_exc}")
    assert not _failures, '\n'.join(_failures)

    # -- test_grid_pres_entries_are_plain_floats: Not numpy scalars, not pint
    #    Quantities - plain python floats.
    payload = _grid_writer([0.01, 1.0, 10.0])._build_payload()
    for value in payload['grid_pres']:
        assert type(value) is float

    # -- test_grid_temp_is_not_converted
    payload = _grid_writer([1.0], temp=[500.0, 1000.0])._build_payload()
    assert payload['grid_temp'] == [500.0, 1000.0]

    # -- test_sub_pressure_grid_override_is_also_passed_through: The
    #    postprocessing sub-grid takes the same (non-)conversion path.
    sop = _MinimalSOP(pres=[1.0], temp=[500.0])
    writer = AutomechKinWriter(
        sop=cast(Any, sop), pes_id=0, sub_p=[0.5, 5.0], sub_t=[700.0])
    assert writer._build_payload()['grid_pres'] == [0.5, 5.0]

    # -- test_empty_pressure_grid_yields_empty_list_and_default_lump
    sop = _MinimalSOP(pres=[1.0], temp=[500.0])
    writer = AutomechKinWriter(sop=cast(Any, sop), pes_id=0, sub_p=[])
    assert writer._build_payload()['grid_pres'] == []

    writer.write(loc=str(tmp_path), filename='G0000E0001P03.py')
    script = (tmp_path / 'G0000E0001P03.py').read_text()
    assert _literal(script, 'PES_PAYLOAD')['grid_pres'] == []
    # max() of an empty grid falls back to the documented 1.0 default.
    assert _literal(script, 'LUMP_PRESSURE') == 1.0

    # -- test_zero_pressure_stays_zero
    payload = _grid_writer([0.0, 1.0])._build_payload()
    assert payload['grid_pres'] == [0.0, 1.0]

    # -- test_integer_pressures_are_coerced_to_float_without_rescaling
    payload = _grid_writer(cast(Any, [1, 10]))._build_payload()
    assert [type(p) for p in payload['grid_pres']] == [float, float]
    assert payload['grid_pres'] == [1.0, 10.0]

    # -- test_low_pressure_point_is_bit_identical_to_the_sop_value: Regression
    #    for ``ValueError: 0.00987 is not in list``.
    grid = _grid_writer([0.01, 0.1, 1.0, 10.0])._build_payload()['grid_pres']
    assert grid[0] == 0.01
    assert repr(grid[0]) == repr(0.01)
    assert 0.00987 not in grid

    # -- test_no_scaling_is_applied_to_any_point: Every emitted point equals
    #    its input exactly, order preserved.
    pres = [0.01, 0.1, 1.0, 10.0]
    script_grid = _grid_writer(pres)._build_payload()['grid_pres']
    assert script_grid == pres
    assert all(a == b for a, b in zip(script_grid, pres))


def test_writer_pres_unit_follows_sop_and_defaults_to_bar() -> None:
    """The writer takes its unit from the SOP; SOPs built outside
    MessInputReader get the documented bar."""
    # -- test_writer_takes_its_unit_from_the_sop
    assert _grid_writer([1.0], pres_unit='bar').pres_unit == 'bar'
    assert _grid_writer([1.0], pres_unit='torr').pres_unit == 'torr'

    # -- test_writer_unit_defaults_to_bar_when_the_sop_has_none: SOPs built
    #    outside ``MessInputReader`` still get the documented bar.
    assert _grid_writer([1.0], pres_unit=None).pres_unit == 'bar'


# ---------------------------------------------------------------------------
# Emitted-script guarantees
# ---------------------------------------------------------------------------
def test_emitted_driver_is_a_plain_literal_script(tmp_path) -> None:
    """PES_PAYLOAD round-trips through literal_eval; PRES_UNIT is a plain string
    following the SOP unit (bar, torr); LUMP_PRESSURE is a plain float, the grid
    max in the grid unit; neither the script nor the writer module needs
    pint/cantera; the script compiles."""
    _tmp_root = tmp_path
    # -- test_emitted_payload_round_trips_through_literal_eval
    tmp_path = _tmp_root / 'test_emitted_payload_round_trips_through_literal_eval'
    tmp_path.mkdir(parents=True)
    script = _emit_grid(tmp_path, [0.01, 1.0, 10.0])
    payload = _literal(script, 'PES_PAYLOAD')
    assert isinstance(payload, dict)
    assert payload['grid_pres'] == [0.01, 1.0, 10.0]

    # -- test_emitted_pres_unit_is_a_plain_string_literal
    tmp_path = _tmp_root / 'test_emitted_pres_unit_is_a_plain_string_literal'
    tmp_path.mkdir(parents=True)
    script = _emit_grid(tmp_path, [0.01, 1.0, 10.0])
    node = _assign_node(script, 'PRES_UNIT')
    assert isinstance(node, ast.Constant)
    assert _literal(script, 'PRES_UNIT') == 'bar'

    # -- test_emitted_pres_unit_follows_the_sop_unit
    tmp_path = _tmp_root / 'test_emitted_pres_unit_follows_the_sop_unit'
    tmp_path.mkdir(parents=True)
    script = _emit_grid(tmp_path, [1.0], pres_unit='torr')
    assert _literal(script, 'PRES_UNIT') == 'torr'

    # -- test_emitted_lump_pressure_is_a_plain_float_literal
    tmp_path = _tmp_root / 'test_emitted_lump_pressure_is_a_plain_float_literal'
    tmp_path.mkdir(parents=True)
    script = _emit_grid(tmp_path, [0.01, 1.0, 10.0])
    node = _assign_node(script, 'LUMP_PRESSURE')
    # A bare numeric constant, not a Call such as Q_(...).to('atm').magnitude.
    assert isinstance(node, ast.Constant)
    value = _literal(script, 'LUMP_PRESSURE')
    assert type(value) is float
    # The max of the grid, in the same (bar) unit as the grid itself.
    assert value == 10.0

    # -- test_emitted_script_has_no_quantity_or_registry_tokens: The driver
    #    must not need pint/cantera to import.
    tmp_path = _tmp_root / 'test_emitted_script_has_no_quantity_or_registry_tokens'
    tmp_path.mkdir(parents=True)
    script = _emit_grid(tmp_path, [0.01, 1.0, 10.0])
    for token in ('Quantity', 'pint', 'cantera', 'ureg', 'Q_', 'magnitude'):
        assert token not in script

    # -- test_writer_module_imports_no_unit_registry: The conversion machinery
    #    is gone from the writer itself, too.
    source = inspect.getsource(automech_kin)
    import_lines = [line for line in source.splitlines()
                    if re.match(r'\s*(import|from)\s', line)]
    for token in ('cantera', 'pint'):
        assert not any(token in line for line in import_lines), token
    for token in ('ureg', 'Q_'):
        assert re.search(rf'\b{re.escape(token)}\b', source) is None, token

    # -- test_emitted_script_compiles
    tmp_path = _tmp_root / 'test_emitted_script_compiles'
    tmp_path.mkdir(parents=True)
    compile(_emit_grid(tmp_path, [0.01, 1.0, 10.0]), 'units.py', 'exec')


# ===========================================================================
# Payload parity: symmetry factors, rotors, LJ masses, global keys
# ===========================================================================
# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------
class _PayloadStruct:
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


class _PayloadRotor:
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


class _PayloadWell:
    def __init__(self, name: str, symbols: list[str],
                 sym_factor: float | None = 1.0,
                 h_rotors: list[Any] | None = None) -> None:
        self.name = name
        self.energy = 0.0
        self.structure = _PayloadStruct(symbols)
        self.frequencies = [500.0, 1500.0]
        self.elec_levels = [[0.0, 1]]
        self.h_rotors = h_rotors or []
        self.m_rotors: list[Any] = []
        self.dummy = False
        self.pes_ids = [0]
        if sym_factor is not None:
            self.sym_factor = sym_factor


class _PayloadBimol:
    def __init__(self, name: str, f1: _PayloadWell, f2: _PayloadWell) -> None:
        self.name = name
        self.energy = -5.0
        self.fragments = [f1, f2]
        self.dummy = False
        self.pes_ids = [0]
        # The barrierless serializer locates a *real* Bimolecular side via
        # isinstance; with doubles it falls back to connected[*].structure.
        self.structure = _PayloadStruct(
            f1.structure.get_chemical_symbols()
            + f2.structure.get_chemical_symbols())


class _PayloadBarrier:
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
            self.structure = _PayloadStruct(['C', 'H', 'O'])
            self.ifreq = -800.0
            self.r_lenergy = 20.0
            self.r_renergy = 15.0
        elif kind == 'rotd':
            self.file = 'flux.dat'
        else:  # phasespace
            self.pp = 10.0
            self.ppe = 6.0


class _PayloadSOP:
    def __init__(self, wells: list[_PayloadWell], bimols: list[_PayloadBimol],
                 barriers: list[_PayloadBarrier], **attrs: Any) -> None:
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

    def wells_in(self, pes_id: int) -> list[_PayloadWell]:
        return [w for w in self._wells if pes_id in w.pes_ids]

    def bimols_in(self, pes_id: int) -> list[_PayloadBimol]:
        return [b for b in self._bimols if pes_id in b.pes_ids]


def _payload(sop: _PayloadSOP) -> dict[str, Any]:
    return AutomechKinWriter(sop=cast(Any, sop), pes_id=0)._build_payload()


def _payload_writer(sop: _PayloadSOP) -> AutomechKinWriter:
    return AutomechKinWriter(sop=cast(Any, sop), pes_id=0)


# ---------------------------------------------------------------------------
# C1.1-C1.3: symmetry factors
# ---------------------------------------------------------------------------
def test_payload_symmetry_factors() -> None:
    """C1.1-C1.3b: species sym_factor from Well.sym_factor (fragments too,
    default 1.0); saddle sym_factor read from Barrier.symFact, never hardcoded."""
    # -- test_c1_1_well_sym_factor_propagates
    sop = _PayloadSOP([_PayloadWell('W', ['C', 'H'], sym_factor=2.0)], [], [])
    wells = {w['label']: w for w in _payload(sop)['wells']}
    assert wells['W']['sym_factor'] == 2.0
    assert isinstance(wells['W']['sym_factor'], float)

    # -- test_c1_1b_fragment_sym_factor_propagates
    f1 = _PayloadWell('O2', ['O', 'O'], sym_factor=2.0)
    f2 = _PayloadWell('C2H4', ['C', 'C', 'H', 'H', 'H', 'H'], sym_factor=4.0)
    sop = _PayloadSOP([], [_PayloadBimol('B', f1, f2)], [])
    bim = _payload(sop)['bimols'][0]
    assert bim['frag1']['sym_factor'] == 2.0
    assert bim['frag2']['sym_factor'] == 4.0

    # -- test_c1_2_well_without_sym_factor_attr_defaults_to_one
    sop = _PayloadSOP([_PayloadWell('W', ['C', 'H'], sym_factor=None)], [], [])
    assert _payload(sop)['wells'][0]['sym_factor'] == 1.0

    # -- test_c1_3_saddle_sym_factor_from_barrier_symfact
    wa = _PayloadWell('WA', ['C', 'H'])
    wb = _PayloadWell('WB', ['C', 'O'])
    bar = _PayloadBarrier('TS', [wa, wb], 'saddle', sym_fact=0.5)
    payload = _payload(_PayloadSOP([wa, wb], [], [bar]))
    ts = payload['barriers'][0]
    assert ts['kind'] == 'saddle'
    assert ts['sym_factor'] == 0.5

    # -- test_c1_3b_saddle_sym_factor_is_read_not_hardcoded
    # Two saddles with different symFact must serialize differently.
    wa = _PayloadWell('WA', ['C', 'H'])
    wb = _PayloadWell('WB', ['C', 'O'])
    b1 = _PayloadBarrier('TS1', [wa, wb], 'saddle', sym_fact=1.0)
    b2 = _PayloadBarrier('TS2', [wa, wb], 'saddle', sym_fact=2.353)
    payload = _payload(_PayloadSOP([wa, wb], [], [b1, b2]))
    assert [b['sym_factor'] for b in payload['barriers']] == [1.0, 2.353]


# ---------------------------------------------------------------------------
# C1.4-C1.6: barrier rotors and rotor geometry
# ---------------------------------------------------------------------------
def _bimol_endpoint() -> tuple[_PayloadWell, _PayloadBimol]:
    well = _PayloadWell('RO2', ['C', 'C', 'O', 'O'])
    f1 = _PayloadWell('R', ['C', 'C', 'H'])
    f2 = _PayloadWell('O2', ['O', 'O'])
    return well, _PayloadBimol('R+O2', f1, f2)


def test_payload_barrier_rotors() -> None:
    """C1.4-C1.5: rotd barriers carry hind_rotors (0-based group/axis, geo;
    empty list without rotors); phasespace barriers carry hind_rotors too,
    plus tst_level (lower case) only when the core had a TSTLevel line."""
    # -- test_c1_4_rotd_barrier_carries_hind_rotors_with_geo
    well, bim = _bimol_endpoint()
    bar = _PayloadBarrier('TSrotd', [well, bim], 'rotd', sym_fact=2.353,
                       h_rotors=[_PayloadRotor(geo=_GEO)])
    payload = _payload(_PayloadSOP([well], [bim], [bar]))
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

    # -- test_c1_4b_rotd_barrier_without_rotors_has_empty_list
    well, bim = _bimol_endpoint()
    bar = _PayloadBarrier('TSrotd', [well, bim], 'rotd')
    ts = _payload(_PayloadSOP([well], [bim], [bar]))['barriers'][0]
    assert ts['hind_rotors'] == []

    # -- test_c1_5_phasespace_barrier_carries_hind_rotors_and_tst_level
    well, bim = _bimol_endpoint()
    bar = _PayloadBarrier('TSpst', [well, bim], 'phasespace',
                       h_rotors=[_PayloadRotor(geo=_GEO)])
    ts = _payload(_PayloadSOP([well], [bim], [bar]))['barriers'][0]
    assert ts['kind'] == 'phasespace'
    # PST-barrier rotors are restored: same serialization as rotd rotors.
    assert len(ts['hind_rotors']) == 1
    assert ts['hind_rotors'][0]['geo'] == _GEO
    assert ts['hind_rotors'][0]['group'] == [1, 2, 3]
    # No TSTLevel line read: no tst_level key (mess_io keeps its default).
    assert 'tst_level' not in ts
    bar.tst_level = 'EJ'
    ts = _payload(_PayloadSOP([well], [bim], [bar]))['barriers'][0]
    assert ts['tst_level'] == 'ej'
    # A phasespace barrier without rotors still has the key (empty list).
    bar = _PayloadBarrier('TSpst', [well, bim], 'phasespace')
    ts = _payload(_PayloadSOP([well], [bim], [bar]))['barriers'][0]
    assert ts['hind_rotors'] == []


def test_payload_rotor_geometry() -> None:
    """C1.6-C1.6d: a rotor payload carries geo only when the rotor had one
    (float cast, empty list = absent), saddle rotors included."""
    # -- test_c1_6_rotor_geo_present_only_when_rotor_had_one
    well = _PayloadWell('W', ['C', 'C', 'H'],
                     h_rotors=[_PayloadRotor(geo=_GEO), _PayloadRotor()])
    rotors = _payload(_PayloadSOP([well], [], []))['wells'][0]['hind_rotors']
    assert len(rotors) == 2
    assert rotors[0]['geo'] == _GEO
    assert 'geo' not in rotors[1]

    # -- test_c1_6b_rotor_geo_rows_are_float_cast
    geo = [['C', '0.0', '0.1', '0.2'], ['H', 1, 2, 3]]
    well = _PayloadWell('W', ['C', 'H'], h_rotors=[_PayloadRotor(geo=geo)])
    rotor = _payload(_PayloadSOP([well], [], []))['wells'][0]['hind_rotors'][0]
    assert rotor['geo'] == [['C', 0.0, 0.1, 0.2], ['H', 1.0, 2.0, 3.0]]
    assert all(isinstance(v, float) for row in rotor['geo'] for v in row[1:])

    # -- test_c1_6c_empty_geo_list_is_treated_as_absent
    well = _PayloadWell('W', ['C', 'H'], h_rotors=[_PayloadRotor(geo=[])])
    rotor = _payload(_PayloadSOP([well], [], []))['wells'][0]['hind_rotors'][0]
    assert 'geo' not in rotor

    # -- test_c1_6d_saddle_barrier_rotor_geo_propagates
    wa = _PayloadWell('WA', ['C', 'H'])
    wb = _PayloadWell('WB', ['C', 'O'])
    bar = _PayloadBarrier('TS', [wa, wb], 'saddle',
                       h_rotors=[_PayloadRotor(geo=_GEO)])
    ts = _payload(_PayloadSOP([wa, wb], [], [bar]))['barriers'][0]
    assert ts['hind_rotors'][0]['geo'] == _GEO


# ---------------------------------------------------------------------------
# C1.7-C1.8: Lennard-Jones masses
# ---------------------------------------------------------------------------
def test_payload_lj_masses(caplog) -> None:
    """C1.7-C1.8c: lj_masses is [bath, species] from SOP.masses (first two,
    floats, no warning); otherwise the N2/heaviest-well heuristic with one
    Masses[amu] warning (empty, single, missing attribute, no wells -> N2
    twice)."""
    # -- test_c1_7_lj_masses_from_sop_masses
    caplog.clear()
    sop = _PayloadSOP([_PayloadWell('W', ['C', 'C', 'O', 'O'])], [], [],
                   masses=[4.0, 61.0])
    with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
        payload = _payload(sop)
    assert payload['lj_masses'] == [4.0, 61.0]
    assert caplog.records == []

    # -- test_c1_7b_lj_masses_uses_only_first_two_and_casts_to_float
    sop = _PayloadSOP([], [], [], masses=[4, 61, 999])
    masses = _payload(sop)['lj_masses']
    assert masses == [4.0, 61.0]
    assert all(isinstance(m, float) for m in masses)

    # -- test_c1_8_lj_masses_fallback_warns_and_uses_heuristic
    _failures = []
    for masses in [[], [4.0]]:
        try:
            caplog.clear()
            wells = [_PayloadWell('light', ['C', 'H']),
                     _PayloadWell('heavy', ['C', 'C', 'O', 'O'])]
            sop = _PayloadSOP(wells, [], [], masses=masses)
            with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
                payload = _payload(sop)
            heavy = 2 * 12.011 + 2 * 15.999
            assert payload['lj_masses'] == pytest.approx([28.0134, heavy])
            hits = [r for r in caplog.records
                    if r.name == 'kimeco.writers.automech_kin'
                    and r.levelno == logging.WARNING]
            assert len(hits) == 1
            assert 'Masses[amu]' in hits[0].getMessage()
        except AssertionError as _exc:
            _failures.append(
                f"test_c1_8_lj_masses_fallback_warns_and_uses_heuristic"
                f"[masses={masses!r}]: {_exc}")
    assert not _failures, '\n'.join(_failures)

    # -- test_c1_8b_lj_masses_fallback_when_sop_lacks_attribute
    caplog.clear()
    sop = _PayloadSOP([_PayloadWell('W', ['O', 'O'])], [], [])
    assert not hasattr(sop, 'masses')
    with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
        payload = _payload(sop)
    assert payload['lj_masses'] == pytest.approx([28.0134, 2 * 15.999])
    assert any('Masses[amu]' in r.getMessage() for r in caplog.records)

    # -- test_c1_8c_lj_masses_fallback_without_wells_uses_n2_twice
    caplog.clear()
    sop = _PayloadSOP([], [], [], masses=[])
    with caplog.at_level(logging.WARNING, 'kimeco.writers.automech_kin'):
        payload = _payload(sop)
    assert payload['lj_masses'] == [28.0134, 28.0134]


# ---------------------------------------------------------------------------
# C1.9-C1.10: global header keys
# ---------------------------------------------------------------------------
def test_payload_global_keys_and_repr_roundtrip(tmp_path) -> None:
    """C1.9-C1.10: global header keys are forwarded as float/str or None when
    absent; the payload with every new key survives the repr/literal_eval round
    trip in the emitted driver."""
    _tmp_root = tmp_path
    # -- test_c1_9_global_keys_forwarded
    sop = _PayloadSOP([], [], [], calculation_method='direct',
                   model_ene_limit=400, excess_ene_temp=40,
                   chem_eig_max=0.2)
    payload = _payload(sop)
    assert payload['calc_method'] == 'direct'
    assert payload['model_ene_limit'] == 400.0
    assert payload['excess_ene_temp'] == 40.0
    assert payload['chem_eig_max'] == 0.2
    for key in ('model_ene_limit', 'excess_ene_temp', 'chem_eig_max'):
        assert isinstance(payload[key], float)

    # -- test_c1_9b_global_keys_none_when_absent_or_missing
    explicit = _PayloadSOP([], [], [], calculation_method=None,
                        model_ene_limit=None, excess_ene_temp=None,
                        chem_eig_max=None)
    missing = _PayloadSOP([], [], [])
    for sop in (explicit, missing):
        payload = _payload(sop)
        for key in ('calc_method', 'model_ene_limit', 'excess_ene_temp',
                    'chem_eig_max'):
            assert key in payload
            assert payload[key] is None

    # -- test_c1_10_payload_survives_repr_roundtrip_with_new_keys
    tmp_path = _tmp_root / 'test_c1_10_payload_survives_repr_roundtrip_with_new_keys'
    tmp_path.mkdir(parents=True)
    # The payload is embedded via repr() in the driver: everything new must
    # be a literal (ast.literal_eval-able), geo rows included.
    well, bim = _bimol_endpoint()
    bar = _PayloadBarrier('TSrotd', [well, bim], 'rotd', sym_fact=2.353,
                       h_rotors=[_PayloadRotor(geo=_GEO)])
    sop = _PayloadSOP([well], [bim], [bar], masses=[4.0, 61.0],
                   calculation_method='direct', model_ene_limit=400.0,
                   excess_ene_temp=40.0, chem_eig_max=0.2)
    writer = _payload_writer(sop)
    writer.write(loc=str(tmp_path), filename='G0000E0001P00.py')
    script = (tmp_path / 'G0000E0001P00.py').read_text()
    line = next(ln for ln in script.splitlines()
                if ln.startswith('PES_PAYLOAD = '))
    payload = ast.literal_eval(line[len('PES_PAYLOAD = '):])
    assert payload == writer._build_payload()
    assert payload['lj_masses'] == [4.0, 61.0]
    assert payload['barriers'][0]['hind_rotors'][0]['geo'] == _GEO
    compile(script, 'driver.py', 'exec')

