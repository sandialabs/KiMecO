"""CI-safe tests: per-PES Lennard-Jones parameters in the SOP.

With several MESS input files, ``SOP.epsilons`` / ``SOP.sigmas`` hold
``[collider, file 0, file 1, ...]`` and the parameter names run
``__epsilon0..N`` / ``__sigma0..N``. These tests check that indices of two
digits (``__epsilon10``, ``__epsilon11``) behave like one-digit ones in
every consumer of the names (type lookup, ``SOP.update``, uncertainties, SOP
DB rows, the perturbator) and that ``SOP.from_db_row`` rejects any row whose
length differs from the SOP read from the inputs (old multi-file projects,
whose rows have another layout, must not be silently misaligned).

Inputs: 11 synthetic one-well files built with the helpers of
``test_mess_multi_pes_read_ci.py``, and the two DME inputs of
``tests/parse_pes/dme`` (a two-file SOP with real items). No MESS binary.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kimeco.enums import FreqMode, Ptype
from kimeco.logger_config import KMOLogger
from kimeco.parameters import SOP
from kimeco.readers.mess_input import MessInputReader
from kimeco.scoring_f.scoring import get_parameter_type
from tests.unit.test_mess_multi_pes_read_ci import (assert_clean, mess_file,
                                                    read, well)
from tests.unit.test_perturbator_boundary_coverage_ci import _scripted_pert

DME_ROOT = Path(__file__).resolve().parent.parent / 'parse_pes' / 'dme'
N_FILES = 11
# The DME pair: 102 parameters with per-PES LJ entries (6 LJ names). The
# layout before per-PES LJ parameters had 104 (4 LJ names and 4 duplicated
# CH2OCH2OOH rotor entries).
DME_PAIR_N_PARAMS = 102
DME_PAIR_OLD_N_PARAMS = 104


def _eleven_file_sop(tmp_path: Path) -> SOP:
    """11 one-well files; file k has second values eps 100+k, sig 3+k/10."""
    files = [mess_file(well(f'W{k}', -float(k)),
                       eps=f'7.95 {100 + k}', sig=f'2.715 {3 + k / 10}')
             for k in range(N_FILES)]
    sop, tpls, reader = read(tmp_path, *files)
    assert_clean(reader)
    assert len(tpls) == N_FILES
    return sop


def _uncertainty_settings(**specific: float) -> dict[str, Any]:
    settings: dict[str, Any] = {f'std_{p.value}': 0.1 for p in Ptype}
    settings['std_epsilon'] = 0.2
    settings['std_sigma'] = 0.05
    settings['specific_std'] = dict(specific)
    return settings


def _dme_pair(tmp_path: Path) -> SOP:
    user = json.loads((DME_ROOT / 'input.json').read_text())
    settings = {
        'init_loc': str(DME_ROOT), 'mess_inputs': user['mess_inputs'],
        'n_exp': 1, 'score_sp': [], 'freq_mode': FreqMode.BATCH,
        'rc_temp': [550.0, 600.0], 'rc_pres': [0.1, 1.0],
        'pres_unit': 'bar', 'force_new_molecules': True}
    reader = MessInputReader(
        settings=settings, mechanism_species=[],
        klog=KMOLogger(filename=str(tmp_path / 'dme.log')),
        postprocess=False)
    sop, _ = reader.read()
    assert reader._trigger_stop is False
    return sop


# ---------------------------------------------------------------------------
# L2: LJ indices of two digits
# ---------------------------------------------------------------------------
def test_lj_layout_of_eleven_files(tmp_path) -> None:
    """[collider, file 0..10]: 12 entries, names __epsilon0..11 in order,
    one written pair per file."""
    sop = _eleven_file_sop(tmp_path)
    assert sop.epsilons == [7.95] + [100.0 + k for k in range(N_FILES)]
    assert sop.sigmas == pytest.approx(
        [2.715] + [3 + k / 10 for k in range(N_FILES)])
    eps_names = [n for n in sop.parameters_names if n.startswith('__epsilon')]
    sig_names = [n for n in sop.parameters_names if n.startswith('__sigma')]
    assert eps_names == [f'__epsilon{k}' for k in range(N_FILES + 1)]
    assert sig_names == [f'__sigma{k}' for k in range(N_FILES + 1)]
    assert len(sop.r_epsilons_pes) == N_FILES
    assert sop.r_epsilons_pes[10] == f' {7.95: 7.4f} {110.0: 7.4f}'


def test_two_digit_lj_names_type_and_update(tmp_path) -> None:
    """__epsilon11 / __sigma10 are EPSI / SIG; update() touches only that
    index (not index 1)."""
    sop = _eleven_file_sop(tmp_path)
    assert get_parameter_type('__epsilon11') is Ptype.EPSI
    assert get_parameter_type('__epsilon1') is Ptype.EPSI
    assert get_parameter_type('__sigma10') is Ptype.SIG

    before_eps, before_sig = list(sop.epsilons), list(sop.sigmas)
    sop.update('__epsilon11', 555.0)
    sop.update('__sigma10', 9.5)
    assert sop.epsilons[11] == 555.0
    assert sop.epsilons[:11] == before_eps[:11]
    assert sop.sigmas[10] == 9.5
    assert sop.sigmas[:10] + sop.sigmas[11:] == \
        before_sig[:10] + before_sig[11:]
    assert sop.parameters_names['__epsilon11'] == 555.0
    assert sop.r_epsilons_pes[10] == f' {7.95: 7.4f} {555.0: 7.4f}'
    assert sop.r_epsilons_pes[0] == f' {7.95: 7.4f} {100.0: 7.4f}'


def test_two_digit_lj_specific_uncertainty(tmp_path) -> None:
    """specific_std on __epsilon11 sets only that name; __epsilon1 keeps the
    global std_epsilon."""
    sop = _eleven_file_sop(tmp_path)
    sop.set_uncertainties(_uncertainty_settings(__epsilon11=0.3))
    assert sop.uncertainties['__epsilon11'] == 0.3
    assert sop.uncertainties['__epsilon1'] == 0.2
    assert sop.uncertainties['__epsilon10'] == 0.2
    assert sop.uncertainties['__sigma11'] == 0.05
    assert {f'__epsilon{k}' for k in range(12)} <= set(sop.uncertainties)


def test_two_digit_lj_db_row_round_trip(tmp_path) -> None:
    """A row with index 11 edited restores only epsilons[11]."""
    sop = _eleven_file_sop(tmp_path)
    names = list(sop.parameters_names)
    row = list(sop.parameters_names.values())
    row[names.index('__epsilon11')] = 321.0
    restored = SOP.from_db_row(sop, row)
    assert restored.epsilons[11] == 321.0
    assert restored.epsilons[1] == 100.0
    assert restored.epsilons[:11] == sop.epsilons[:11]
    assert sop.epsilons[11] == 110.0  # template untouched
    assert list(restored.parameters_names.values()) == row


def test_perturbator_moves_only_selected_two_digit_index(tmp_path) -> None:
    """select=['__epsilon11'] perturbs epsilons[11] only (not [1])."""
    i_sop = _eleven_file_sop(tmp_path)
    i_sop.set_uncertainties(_uncertainty_settings())
    sop = SOP.from_db_row(i_sop, list(i_sop.parameters_names.values()))
    pert, draws = _scripted_pert(['__epsilon11'], i_sop)
    for method in ('perturb_well', 'perturb_bimolecular', 'perturb_barrier'):
        setattr(pert, method, lambda _item: None)
    pert.perturb(sop)
    assert sop.epsilons[11] == pytest.approx(110.0 * 1.01)
    assert sop.epsilons[:11] == i_sop.epsilons[:11]
    assert sop.sigmas == i_sop.sigmas
    assert {param for param, _ in draws} == {'__epsilon11'}


# ---------------------------------------------------------------------------
# L3: strict SOP DB row length (old multi-file layouts)
# ---------------------------------------------------------------------------
def test_dme_pair_layout(tmp_path) -> None:
    """The DME pair holds 3 LJ entries per list (collider + 2 files)."""
    sop = _dme_pair(tmp_path)
    assert len(sop.parameters_names) == DME_PAIR_N_PARAMS
    assert sop.epsilons == [7.95, 206.15, 206.15]
    assert sop.sigmas == [2.715, 4.71, 4.71]


@pytest.mark.parametrize('case', ['old_lj_layout', 'old_full_length',
                                  'one_extra', 'empty'])
def test_from_db_row_length_mismatch_raises(tmp_path, case) -> None:
    """A row shorter (no __epsilon2/__sigma2) or longer (the 104 values of
    the old DME layout, one extra value) than the template raises, before
    anything is restored."""
    sop = _dme_pair(tmp_path)
    names = list(sop.parameters_names)
    row = list(sop.parameters_names.values())
    if case == 'old_lj_layout':
        bad = [v for n, v in zip(names, row)
               if n not in ('__epsilon2', '__sigma2')]
    elif case == 'old_full_length':
        bad = row[:DME_PAIR_OLD_N_PARAMS] + [1.0] * (
            DME_PAIR_OLD_N_PARAMS - len(row))
    elif case == 'one_extra':
        bad = row + [1.0]
    else:
        bad = []
    assert len(bad) != len(row)
    with pytest.raises(ValueError, match=(
            rf'SOP DB row holds {len(bad)} values but the SOP read from the '
            rf'MESS inputs has {len(row)} parameters')):
        SOP.from_db_row(sop, bad)
    assert list(sop.parameters_names.values()) == row


def test_from_db_row_new_layout_round_trips(tmp_path) -> None:
    """A row of the current layout restores the values, including the second
    file's LJ entries."""
    sop = _dme_pair(tmp_path)
    names = list(sop.parameters_names)
    row = list(sop.parameters_names.values())
    row[names.index('__epsilon2')] = 250.0
    row[names.index('__sigma1')] = 5.0
    restored = SOP.from_db_row(sop, row)
    assert restored.epsilons == [7.95, 206.15, 250.0]
    assert restored.sigmas == [2.715, 5.0, 4.71]
    assert list(restored.parameters_names.values()) == row
    assert restored.r_epsilons_pes == [f' {7.95: 7.4f} {206.15: 7.4f}',
                                       f' {7.95: 7.4f} {250.0: 7.4f}']
