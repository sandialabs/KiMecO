"""CI-safe tests for the automech per-slot MESS driver emitter.

These tests exercise ``AutomechKinWriter`` without automech/``mess_io``
installed: the emitter only *serializes* SOP data into a self-contained
python driver script (it never imports ``mess_io`` in the main process), so
we can assert on the emitted source text and that it ``compile()``s.

Fakes mirror the real accessor surface the serializer reads (SOP.wells_in /
bimols_in / barriers / factor / power / epsilons / sigmas / temp / pres;
Well.name/.energy/.structure/.frequencies/.elec_levels/.h_rotors/.m_rotors;
Bimolecular.name/.energy/.fragments; Barrier.connected/.barrierless/.energy/
.structure/.frequencies/.elec_levels/.h_rotors/.ifreq/.r_lenergy/.r_renergy/
.symFact/.pes_ids/.dummy).
"""
from __future__ import annotations

import ast
import re
from typing import Any, cast

import pytest

from kimeco.writers.automech_kin import AutomechKinWriter


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


@pytest.mark.parametrize('shape', sorted(_SHAPES))
def test_emitted_script_compiles(tmp_path, shape) -> None:
    script, _ = _emit(tmp_path, _SHAPES[shape])
    # No import/exec of mess_io: just verify the source is valid python.
    compile(script, f'{shape}.py', 'exec')


@pytest.mark.parametrize('shape', sorted(_SHAPES))
def test_emitted_script_uses_only_public_mess_io(tmp_path, shape) -> None:
    script, _ = _emit(tmp_path, _SHAPES[shape])
    assert 'from mess_io.writer import' in script
    assert 'from mess_io import well_lumped_input_file' in script
    # No private mess_io internals leaked into the driver.
    assert 'mess_io._' not in script


@pytest.mark.parametrize('shape', sorted(_SHAPES))
def test_emitted_script_has_no_database_reference(tmp_path, shape) -> None:
    script, _ = _emit(tmp_path, _SHAPES[shape])
    lowered = script.lower()
    for token in ('kin_db', 'get_rates_for_kin_id', 'sqlite', 'kimeco.database'):
        assert token not in lowered
    assert 'KIN_DB' not in script


@pytest.mark.parametrize('shape', sorted(_SHAPES))
def test_emitted_script_two_pass_structure(tmp_path, shape) -> None:
    script, _ = _emit(tmp_path, _SHAPES[shape])
    # Pass 1 writes the base input and runs mess, the pass-1 output is moved
    # to a leading-underscore intermediate, and pass 2 (WellExtension caps via
    # well_lumped_input_file) runs only behind the merged-well gate; the
    # second _run_mess therefore sits deeper inside main() than the first.
    assert 'well_lumped_input_file(' in script
    assert 'pass1_copy = "_" + base' in script
    assert 'os.replace(out_name, pass1_copy)' in script
    assert 'shutil' not in script
    # Two mess invocations (pass 1 + pass 2), regardless of indentation.
    run_lines = [ln for ln in script.splitlines()
                 if ln.strip() == '_run_mess(inp_name)']
    assert len(run_lines) == 2
    # Pass 2 is nested one level deeper: it lives in the merging branch.
    indent = [len(ln) - len(ln.lstrip()) for ln in run_lines]
    assert indent[1] > indent[0]


@pytest.mark.parametrize('shape', sorted(_SHAPES))
def test_emitted_script_contains_sop_species_names(tmp_path, shape) -> None:
    script, species = _emit(tmp_path, _SHAPES[shape])
    for name in species:
        assert repr(name) in script


def test_rotor_payload_skips_fourier_and_keeps_scan_rotor(tmp_path) -> None:
    # The rotor PES has one scan-based (kept) and one Fourier (skipped)
    # hindered rotor plus one multirotor; all must serialize and compile.
    script, _ = _emit(tmp_path, _rotor_pes)
    compile(script, 'rotor.py', 'exec')
    # Multirotor potential-surface file is referenced as a bare literal.
    assert "'pot_surf.dat'" in script


def test_bimolecular_only_pes_emits_both_bimols(tmp_path) -> None:
    script, species = _emit(tmp_path, _bimolecular_only)
    assert species == ['R', 'P']
    # Barrierless phasespace kind is serialized (no 'file' attr on barrier).
    assert "'phasespace'" in script


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


@pytest.mark.parametrize('builder', [_rotor_pes, _two_point_rotor_pes],
                         ids=['hindered_multi_rotor', 'two_point_scan_rotor'])
def test_rotor_hindered_uses_fourier_potential_form(tmp_path, builder) -> None:
    script, _ = _emit(tmp_path, builder)
    assert _FOURIER_KWARG in script
    # The spline form (mess_io default) must not be requested anywhere.
    assert 'PotentialSpline' not in script
    compile(script, 'fourier_form.py', 'exec')


def test_rotor_hindered_call_has_fourier_kwarg_exactly_once(tmp_path) -> None:
    script, _ = _emit(tmp_path, _rotor_pes)
    body = _hind_rot_str_source(script)
    assert body.count(_FOURIER_KWARG) == 1
    # The potential grid is still forwarded alongside the new form kwarg.
    assert 'potential=pot' in body


def test_two_point_scan_rotor_payload_serialized(tmp_path) -> None:
    # symmetry 2, two scan points -> step = (360 / 2) / 2 = 90 degrees.
    script, species = _emit(tmp_path, _two_point_rotor_pes)
    assert species == ['W2P', 'B2P']
    expected = '[[0.0, 0.0], [90.0, 2.7]]'
    if expected not in script:
        # Whitespace-tolerant fallback in case repr formatting changes.
        pattern = re.compile(
            r'\[\s*\[\s*0\.0\s*,\s*0\.0\s*\]\s*,'
            r'\s*\[\s*90\.0\s*,\s*2\.7\s*\]\s*\]')
        assert pattern.search(script), 'two-point potential grid not emitted'
    wells = _payload_wells(script)
    rotors = wells['W2P']['hind_rotors']
    assert len(rotors) == 1
    assert rotors[0]['potential'] == [[0.0, 0.0], [90.0, 2.7]]
    assert rotors[0]['symmetry'] == 2


def test_fourier_flag_rotor_still_skipped_with_fourier_form(tmp_path) -> None:
    # A well whose only hindered rotor is flagged ``fourier`` carries no scan
    # grid: it must still be dropped from the payload, independently of the
    # potential_form requested in the template.
    def _fourier_only() -> tuple[_FakeSOP, list[str]]:
        w = _FakeWell('WF', ['C', 'C', 'H', 'H', 'H', 'H'],
                      h_rotors=[_FakeRotor(fourier=True)])
        prod = _FakeWell('PF', ['C', 'O'])
        bim = _FakeBimolecular('BF', prod, _FakeWell('HF', ['H']))
        bar = _FakeBarrier('TSF', connected=[w, bim],
                           symbols=['C', 'C', 'H', 'H'])
        return _FakeSOP([w], [bim], [bar]), ['WF', 'BF']

    script, _ = _emit(tmp_path, _fourier_only)
    wells = _payload_wells(script)
    assert wells['WF']['hind_rotors'] == []
    assert _FOURIER_KWARG in script
    compile(script, 'fourier_only.py', 'exec')


def test_no_rotor_shape_still_emits_fourier_form_in_template(tmp_path) -> None:
    # The kwarg lives in the static template, so it is present even when no
    # species carries a hindered rotor.
    script, _ = _emit(tmp_path, _single_well)
    assert _FOURIER_KWARG in script
    assert 'PotentialSpline' not in script
    wells = _payload_wells(script)
    assert all(w['hind_rotors'] == [] for w in wells.values())
