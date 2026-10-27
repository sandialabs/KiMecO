"""CI-safe tests for the MESS global header keys captured by the reader.

``MessInputReader.read`` records, on the SOP, the header keywords the
automech driver must forward to ``mess_io``:

* ``Masses[amu]``               -> ``SOP.masses`` (collider first, as in the
  MESS manual; the first file's line; each file's own line is kept in
  ``SOP.pes_file_data[pes_id].masses``)
* ``CalculationMethod``         -> ``SOP.calculation_method``
* ``ModelEnergyLimit[<unit>]``  -> ``SOP.model_ene_limit`` (kcal/mol, the
  first file's value; per PES in ``pes_file_data``)
* ``ExcessEnergyOverTemperature`` -> ``SOP.excess_ene_temp``
* ``ChemicalEigenvalueMax``     -> ``SOP.chem_eig_max``

Contract exercised here (black-box, synthetic in-memory MESS files):

* every captured line is appended verbatim to the template;
* keys that must be the same in all files (CalculationMethod,
  ExcessEnergyOverTemperature, ChemicalEigenvalueMax, ...): a later file
  that disagrees logs one warning naming the file and sets
  ``_trigger_stop``; a key present in some files and absent from others
  stops too (an error naming the key; absence is a value of its own);
* ``Masses``: only the collider mass (index 0) must be the same in every
  file; the second value legitimately differs per PES;
* ``ModelEnergyLimit`` is kept per PES (never compared);
* absent keys leave the SOP defaults (``[]`` / ``None``) untouched;
* ``ModelEnergyLimit`` is normalised to kcal/mol (``1/cm`` and ``kJ/mol``
  converted, unknown units warned about and stored raw).

The per-key rules of every header key are covered in
``test_mess_multi_pes_read_ci.py``.

No MESS binary, database or automech install is needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.readers.mess_input import MessInputReader

DME_ROOT = Path(__file__).resolve().parent.parent / 'parse_pes' / 'dme'

_CM2KCAL = 349.755
_KJ2KCAL = 4.184


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _SpyLog:
    """Records warning/error messages; mirrors the KMOLogger surface used."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def warning(self, msg: str = '', *a: Any, **k: Any) -> None:
        self.warnings.append(str(msg))

    def error(self, msg: str = '', *a: Any, **k: Any) -> None:
        self.errors.append(str(msg))

    def info(self, *a: Any, **k: Any) -> None:
        pass

    def debug(self, *a: Any, **k: Any) -> None:
        pass


def _settings(names: list[str]) -> dict[str, Any]:
    return {
        'init_loc': str(DME_ROOT),
        'mess_inputs': names,
        'n_exp': 1,
        'score_sp': [],
        'freq_mode': FreqMode.BATCH,
        'rc_temp': [],
        'rc_pres': [],
        'pres_unit': 'bar',
        'force_new_molecules': True,
    }


def _reader(tmp_path: Path, files: list[list[str]]) -> MessInputReader:
    """A reader whose ``pes_files`` are the given in-memory MESS inputs.

    Real files must exist for ``__init__``; the dme inputs are used as
    stand-ins and then replaced by the synthetic content.
    """
    names = ['mess_roo_L3.inp', 'mess_ooqooh_L2.inp'][:len(files)]
    reader = MessInputReader(
        settings=_settings(names),
        mechanism_species=[],
        klog=KMOLogger(filename=str(tmp_path / 'header_keys.log')),
        postprocess=False,
    )
    reader.pes_files = [list(f) for f in files]
    return reader


def _read(tmp_path: Path, *files: list[str]) -> tuple[Any, list[list[str]],
                                                       MessInputReader]:
    reader = _reader(tmp_path, list(files))
    spy = _SpyLog()
    reader.klog = spy  # type: ignore[assignment]
    sop, tpls = reader.read()
    return sop, tpls, reader


_HEADER = [
    'TemperatureList[K] 500 600\n',
    'PressureList[bar] 0.1 1.0\n',
    'ExcessEnergyOverTemperature   40\n',
    'ModelEnergyLimit[kcal/mol]    400\n',
    'CalculationMethod             direct\n',
    'ChemicalEigenvalueMax         0.2\n',
    'Model\n',
    '  CollisionFrequency\n',
    '    LennardJones\n',
    '      Masses[amu]   4.0 61.0\n',
    '    End\n',
    'Well W1\n',
    'End\n',
]


# ---------------------------------------------------------------------------
# A1-A7: standard capture of each key + verbatim template line
# ---------------------------------------------------------------------------
def test_header_keys_captured_verbatim(tmp_path) -> None:
    """A1, A3, A6, A7: each key is captured and its line kept verbatim;
    A2: masses stop at the first non-numeric token; A7b: keys are case
    insensitive and indent tolerant."""
    sop, tpls, _ = _read(tmp_path, _HEADER)
    assert sop.masses == [4.0, 61.0], 'a1 bath first'
    assert all(isinstance(m, float) for m in sop.masses)
    assert sop.calculation_method == 'direct', 'a3'
    assert sop.excess_ene_temp == 40.0, 'a6'
    assert sop.chem_eig_max == 0.2, 'a7'
    for line in ('      Masses[amu]   4.0 61.0\n',
                 'CalculationMethod             direct\n',
                 'ExcessEnergyOverTemperature   40\n',
                 'ChemicalEigenvalueMax         0.2\n'):
        assert line in tpls[0], line

    lines = ['      Masses[amu]   28. 61. ! N2 , CH3CH2OO\n', 'Well W1\n', 'End\n']
    sop, tpls, _ = _read(tmp_path, lines)
    assert sop.masses == [28.0, 61.0], 'a2'
    assert lines[0] in tpls[0]

    lines = [
        '   masses[AMU] 4.0 61.0\n',
        '\tCALCULATIONMETHOD low-eigenvalue\n',
        '  excessenergyovertemperature 30\n',
        '  chemicaleigenvaluemax 0.1\n',
        'Well W1\n', 'End\n']
    sop, tpls, _ = _read(tmp_path, lines)
    assert sop.masses == [4.0, 61.0], 'a7b'
    assert sop.calculation_method == 'low-eigenvalue'
    assert sop.excess_ene_temp == 30.0
    assert sop.chem_eig_max == 0.1
    for line in lines[:4]:
        assert line in tpls[0], line


def test_model_energy_limit_normalised_to_kcal(tmp_path) -> None:
    """A4: 1/cm and kJ/mol converted, kcal/no unit/upper case kept, the
    template keeps the user's original line; A5: an unknown unit warns
    (unit casefolded), is stored raw and does not stop."""
    failures: list[str] = []
    for label, line, expected in (
            ('kcal', 'ModelEnergyLimit[kcal/mol] 400\n', 400.0),
            ('no_unit', 'ModelEnergyLimit 400\n', 400.0),
            ('wavenumber', 'ModelEnergyLimit[1/cm] 349755\n', 349755.0 / _CM2KCAL),
            ('kj', 'ModelEnergyLimit[kJ/mol] 418.4\n', 418.4 / _KJ2KCAL),
            ('upper_case_unit', 'ModelEnergyLimit[KCAL/MOL] 12.5\n', 12.5)):
        sop, tpls, _ = _read(tmp_path, [line, 'Well W1\n', 'End\n'])
        if sop.model_ene_limit != pytest.approx(expected):
            failures.append(f'{label}: {sop.model_ene_limit} != {expected}')
        if line not in tpls[0]:
            failures.append(f'{label}: template line altered')
    assert not failures, '\n'.join(failures)

    line = 'ModelEnergyLimit[eV] 17.0\n'
    sop, tpls, reader = _read(tmp_path, [line, 'Well W1\n', 'End\n'])
    assert sop.model_ene_limit == 17.0
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    assert any('ModelEnergyLimit' in w and 'ev' in w.casefold()
               for w in warnings)
    assert reader._trigger_stop is False
    assert line in tpls[0]


# ---------------------------------------------------------------------------
# A8: absent keys keep the SOP defaults; commented lines are ignored
# ---------------------------------------------------------------------------
def test_absent_or_commented_keys_leave_defaults(tmp_path) -> None:
    sop, _, reader = _read(tmp_path, ['Well W1\n', 'End\n'])
    assert sop.masses == []
    assert sop.calculation_method is None
    assert sop.model_ene_limit is None
    assert sop.excess_ene_temp is None
    assert sop.chem_eig_max is None
    assert reader._trigger_stop is False

    lines = [
        '!CalculationMethod low-eigenvalue\n',
        '! Masses[amu] 28. 61.\n',
        '!ModelEnergyLimit[kcal/mol] 999\n',
        'CalculationMethod direct\n',
        'Well W1\n', 'End\n']
    sop, tpls, reader = _read(tmp_path, lines)
    assert sop.calculation_method == 'direct'
    assert sop.masses == []
    assert sop.model_ene_limit is None
    assert reader._trigger_stop is False
    # The comments still travel to the template through the fall-through.
    assert lines[0] in tpls[0] and lines[1] in tpls[0]


# ---------------------------------------------------------------------------
# A9-A11: cross-file consistency
# ---------------------------------------------------------------------------
_FILE_A = [
    'ExcessEnergyOverTemperature 40\n',
    'ModelEnergyLimit[kcal/mol] 400\n',
    'CalculationMethod direct\n',
    'ChemicalEigenvalueMax 0.2\n',
    'Masses[amu] 4.0 61.0\n',
    'Well WA\n', 'End\n']


def _file_b(**overrides: str) -> list[str]:
    base = {
        'ExcessEnergyOverTemperature': '40',
        'ModelEnergyLimit[kcal/mol]': '400',
        'CalculationMethod': 'direct',
        'ChemicalEigenvalueMax': '0.2',
        'Masses[amu]': '4.0 61.0',
    }
    base.update(overrides)
    return [f'{k} {v}\n' for k, v in base.items()] + ['Well WB\n', 'End\n']


def test_consistent_files_do_not_stop(tmp_path) -> None:
    """A9 identical headers; A9b/A10 a different *species* mass is allowed
    (first file kept, no mass warning); A11b equal ModelEnergyLimit after
    unit conversion."""
    sop, tpls, reader = _read(tmp_path, _FILE_A, _file_b())
    assert reader._trigger_stop is False, 'a9'
    # Only the species-not-in-mechanism notices (force_new_molecules) remain.
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    assert all('mechanism file' in w for w in warnings)
    assert sop.masses == [4.0, 61.0]
    assert sop.calculation_method == 'direct'
    assert len(tpls) == 2
    assert 'Masses[amu] 4.0 61.0\n' in tpls[1]

    for species_mass in ('77.0', '109.0'):
        sop, _, reader = _read(
            tmp_path, _FILE_A, _file_b(**{'Masses[amu]': f'4.0 {species_mass}'}))
        assert sop.masses == [4.0, 61.0], species_mass
        assert reader._trigger_stop is False, species_mass
        assert not any('mass' in w.casefold()
                       for w in reader.klog.warnings), species_mass  # type: ignore[attr-defined]

    # 400 kcal/mol expressed in kJ/mol in the second file: same value.
    second = [ln for ln in _file_b() if not ln.startswith('ModelEnergyLimit')]
    second.insert(1, f'ModelEnergyLimit[kJ/mol] {400 * _KJ2KCAL}\n')
    sop, _, reader = _read(tmp_path, _FILE_A, second)
    assert sop.model_ene_limit == pytest.approx(400.0), 'a11b'
    assert reader._trigger_stop is False, 'a11b'



def test_key_only_in_a_later_file_stops(tmp_path) -> None:
    """A11c: a same-in-all-files key (or the Masses line) present in the
    second file only stops with one error per key naming both files; the
    per-PES ModelEnergyLimit is never reported."""
    sop, _, reader = _read(tmp_path, ['Well WA\n', 'End\n'], _file_b())
    assert reader._trigger_stop is True, 'a11c'
    errors = reader.klog.errors  # type: ignore[attr-defined]
    for label in ('CalculationMethod', 'ExcessEnergyOverTemperature',
                  'ChemicalEigenvalueMax', 'Masses'):
        hit = [e for e in errors if e.startswith(f'{label} is set in')]
        assert len(hit) == 1, (label, errors)
        assert 'absent from' in hit[0]
        assert reader.filenames[1] in hit[0].split('absent from')[0]
        assert reader.filenames[0] in hit[0].split('absent from')[1]
    assert not any('ModelEnergyLimit' in e for e in errors)
    # Presence errors are errors, never "Different ..." warnings.
    assert not any('Different' in w
                   for w in reader.klog.warnings)  # type: ignore[attr-defined]
    # Values are still read from the file that carries them.
    assert sop.calculation_method == 'direct'
    assert sop.model_ene_limit == 400.0


def test_mismatch_warns_with_filename_and_stops(tmp_path) -> None:
    """A10b a bath-mass mismatch and A11 any same-in-all-files key mismatch
    warn once naming the second file and stop; the first file's values are
    kept. ModelEnergyLimit is per PES and never stops
    (``test_mess_multi_pes_read_ci.py``)."""
    _, _, reader = _read(
        tmp_path, _FILE_A, _file_b(**{'Masses[amu]': '28.0 61.0'}))
    assert reader._trigger_stop is True
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    hit = [w for w in warnings if 'bath mass' in w.casefold()]
    assert len(hit) == 1
    assert reader.filenames[1] in hit[0]
    assert '4.0' in hit[0]

    failures: list[str] = []
    for key, value, label in (
            ('CalculationMethod', 'low-eigenvalue', 'CalculationMethod'),
            ('ExcessEnergyOverTemperature', '30', 'ExcessEnergyOverTemperature'),
            ('ChemicalEigenvalueMax', '0.1', 'ChemicalEigenvalueMax')):
        sop, _, reader = _read(tmp_path, _FILE_A, _file_b(**{key: value}))
        hit = [w for w in reader.klog.warnings if label in w]  # type: ignore[attr-defined]
        if reader._trigger_stop is not True:
            failures.append(f'{label}: no stop')
        if len(hit) != 1 or reader.filenames[1] not in hit[0]:
            failures.append(f'{label}: warnings {hit}')
        kept = (sop.calculation_method, sop.model_ene_limit,
                sop.excess_ene_temp, sop.chem_eig_max)
        if kept != ('direct', 400.0, 40.0, 0.2):
            failures.append(f'{label}: first-file values not kept: {kept}')
    assert not failures, '\n'.join(failures)
