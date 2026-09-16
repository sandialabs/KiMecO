"""CI-safe tests for the MESS global header keys captured by the reader.

``MessInputReader.read`` now records, on the SOP, the header keywords the
automech driver must forward to ``mess_io``:

* ``Masses[amu]``               -> ``SOP.masses`` (bath first, species second)
* ``CalculationMethod``         -> ``SOP.calculation_method``
* ``ModelEnergyLimit[<unit>]``  -> ``SOP.model_ene_limit`` (kcal/mol)
* ``ExcessEnergyOverTemperature`` -> ``SOP.excess_ene_temp``
* ``ChemicalEigenvalueMax``     -> ``SOP.chem_eig_max``

Contract exercised here (black-box, synthetic in-memory MESS files):

* every captured line is appended verbatim to the template;
* the first file wins; a later file that disagrees logs a warning naming the
  file and sets ``_trigger_stop`` (only the *bath* mass, index 0, is compared
  for ``Masses`` - the species mass legitimately differs per PES);
* absent keys leave the SOP defaults (``[]`` / ``None``) untouched;
* ``ModelEnergyLimit`` is normalised to kcal/mol (``1/cm`` and ``kJ/mol``
  converted, unknown units warned about and stored raw).

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
def test_a1_masses_captured_bath_first(tmp_path) -> None:
    sop, tpls, _ = _read(tmp_path, _HEADER)
    assert sop.masses == [4.0, 61.0]
    assert all(isinstance(m, float) for m in sop.masses)
    assert '      Masses[amu]   4.0 61.0\n' in tpls[0]


def test_a2_masses_stop_at_first_non_numeric_token(tmp_path) -> None:
    lines = [
        '      Masses[amu]   28. 61. ! N2 , CH3CH2OO\n',
        'Well W1\n', 'End\n']
    sop, tpls, _ = _read(tmp_path, lines)
    assert sop.masses == [28.0, 61.0]
    assert lines[0] in tpls[0]


def test_a3_calculation_method_captured(tmp_path) -> None:
    sop, tpls, _ = _read(tmp_path, _HEADER)
    assert sop.calculation_method == 'direct'
    assert 'CalculationMethod             direct\n' in tpls[0]


@pytest.mark.parametrize('line, expected', [
    ('ModelEnergyLimit[kcal/mol] 400\n', 400.0),
    ('ModelEnergyLimit 400\n', 400.0),
    ('ModelEnergyLimit[1/cm] 349755\n', 349755.0 / _CM2KCAL),
    ('ModelEnergyLimit[kJ/mol] 418.4\n', 418.4 / _KJ2KCAL),
    ('ModelEnergyLimit[KCAL/MOL] 12.5\n', 12.5),
], ids=['kcal', 'no_unit', 'wavenumber', 'kj', 'upper_case_unit'])
def test_a4_model_energy_limit_normalised_to_kcal(
        tmp_path, line: str, expected: float) -> None:
    sop, tpls, _ = _read(tmp_path, [line, 'Well W1\n', 'End\n'])
    assert sop.model_ene_limit == pytest.approx(expected)
    # The template keeps the user's original unit/value untouched.
    assert line in tpls[0]


def test_a5_model_energy_limit_unknown_unit_warns_and_stores_raw(
        tmp_path) -> None:
    line = 'ModelEnergyLimit[eV] 17.0\n'
    sop, tpls, reader = _read(tmp_path, [line, 'Well W1\n', 'End\n'])
    assert sop.model_ene_limit == 17.0
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    # The unit is reported casefolded (the reader parses it that way).
    assert any('ModelEnergyLimit' in w and 'ev' in w.casefold()
               for w in warnings)
    assert reader._trigger_stop is False
    assert line in tpls[0]


def test_a6_excess_energy_over_temperature_captured(tmp_path) -> None:
    sop, tpls, _ = _read(tmp_path, _HEADER)
    assert sop.excess_ene_temp == 40.0
    assert 'ExcessEnergyOverTemperature   40\n' in tpls[0]


def test_a7_chemical_eigenvalue_max_captured(tmp_path) -> None:
    sop, tpls, _ = _read(tmp_path, _HEADER)
    assert sop.chem_eig_max == 0.2
    assert 'ChemicalEigenvalueMax         0.2\n' in tpls[0]


def test_a7b_keys_are_case_insensitive_and_indent_tolerant(tmp_path) -> None:
    lines = [
        '   masses[AMU] 4.0 61.0\n',
        '\tCALCULATIONMETHOD low-eigenvalue\n',
        '  excessenergyovertemperature 30\n',
        '  chemicaleigenvaluemax 0.1\n',
        'Well W1\n', 'End\n']
    sop, tpls, _ = _read(tmp_path, lines)
    assert sop.masses == [4.0, 61.0]
    assert sop.calculation_method == 'low-eigenvalue'
    assert sop.excess_ene_temp == 30.0
    assert sop.chem_eig_max == 0.1
    for line in lines[:4]:
        assert line in tpls[0]


# ---------------------------------------------------------------------------
# A8: absent keys keep the SOP defaults; commented lines are ignored
# ---------------------------------------------------------------------------
def test_a8_absent_keys_leave_defaults(tmp_path) -> None:
    sop, _, reader = _read(tmp_path, ['Well W1\n', 'End\n'])
    assert sop.masses == []
    assert sop.calculation_method is None
    assert sop.model_ene_limit is None
    assert sop.excess_ene_temp is None
    assert sop.chem_eig_max is None
    assert reader._trigger_stop is False


def test_a8b_commented_header_lines_are_ignored(tmp_path) -> None:
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


def test_a9_identical_headers_across_files_do_not_stop(tmp_path) -> None:
    sop, tpls, reader = _read(tmp_path, _FILE_A, _file_b())
    assert reader._trigger_stop is False
    # Only the species-not-in-mechanism notices (force_new_molecules) remain.
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    assert all('mechanism file' in w for w in warnings)
    assert sop.masses == [4.0, 61.0]
    assert sop.calculation_method == 'direct'
    assert len(tpls) == 2
    assert 'Masses[amu] 4.0 61.0\n' in tpls[1]


def test_a9b_first_file_wins(tmp_path) -> None:
    # Second file carries a different *species* mass: allowed, first kept.
    sop, _, _ = _read(tmp_path, _FILE_A, _file_b(**{'Masses[amu]': '4.0 77.0'}))
    assert sop.masses == [4.0, 61.0]


def test_a10_species_mass_difference_does_not_stop(tmp_path) -> None:
    _, _, reader = _read(
        tmp_path, _FILE_A, _file_b(**{'Masses[amu]': '4.0 109.0'}))
    assert reader._trigger_stop is False
    assert not any('mass' in w.casefold()
                   for w in reader.klog.warnings)  # type: ignore[attr-defined]


def test_a10b_bath_mass_mismatch_warns_with_filename_and_stops(
        tmp_path) -> None:
    _, _, reader = _read(
        tmp_path, _FILE_A, _file_b(**{'Masses[amu]': '28.0 61.0'}))
    assert reader._trigger_stop is True
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    hit = [w for w in warnings if 'bath mass' in w.casefold()]
    assert len(hit) == 1
    assert reader.filenames[1] in hit[0]
    assert '4.0' in hit[0]


@pytest.mark.parametrize('key, value, label', [
    ('CalculationMethod', 'low-eigenvalue', 'CalculationMethod'),
    ('ModelEnergyLimit[kcal/mol]', '800', 'ModelEnergyLimit'),
    ('ExcessEnergyOverTemperature', '30', 'ExcessEnergyOverTemperature'),
    ('ChemicalEigenvalueMax', '0.1', 'ChemicalEigenvalueMax'),
])
def test_a11_scalar_key_mismatch_warns_with_filename_and_stops(
        tmp_path, key: str, value: str, label: str) -> None:
    sop, _, reader = _read(tmp_path, _FILE_A, _file_b(**{key: value}))
    assert reader._trigger_stop is True
    warnings = reader.klog.warnings  # type: ignore[attr-defined]
    hit = [w for w in warnings if label in w]
    assert len(hit) == 1
    assert reader.filenames[1] in hit[0]
    # First file value is the one kept on the SOP.
    assert sop.calculation_method == 'direct'
    assert sop.model_ene_limit == 400.0
    assert sop.excess_ene_temp == 40.0
    assert sop.chem_eig_max == 0.2


def test_a11b_model_energy_limit_equal_after_unit_conversion_does_not_stop(
        tmp_path) -> None:
    # 400 kcal/mol expressed in kJ/mol in the second file: same value.
    second = _file_b(**{'ModelEnergyLimit[kcal/mol]': '0'})
    second = [ln for ln in second if not ln.startswith('ModelEnergyLimit')]
    second.insert(1, f'ModelEnergyLimit[kJ/mol] {400 * _KJ2KCAL}\n')
    sop, _, reader = _read(tmp_path, _FILE_A, second)
    assert sop.model_ene_limit == pytest.approx(400.0)
    assert reader._trigger_stop is False


def test_a11c_key_only_in_second_file_is_adopted_without_stop(
        tmp_path) -> None:
    first = ['Well WA\n', 'End\n']
    sop, _, reader = _read(tmp_path, first, _file_b())
    assert reader._trigger_stop is False
    assert sop.masses == [4.0, 61.0]
    assert sop.calculation_method == 'direct'
    assert sop.model_ene_limit == 400.0
    assert sop.excess_ene_temp == 40.0
    assert sop.chem_eig_max == 0.2
