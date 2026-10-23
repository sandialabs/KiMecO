from __future__ import annotations

import numpy as np

from kimeco.well import Well
from kimeco.enums import FreqMode


def _well(freqs: np.ndarray, bfc: float = 1.0) -> Well:
    w = Well(name="W", pes_ids=[0], freq_mode=FreqMode.BATCH)
    w._freq = freqs
    w.bfc = bfc
    return w


def test_batch_mode_frequencies() -> None:
    """Batch mode: freq * bfc**(100/freq); low frequencies are perturbed more
    than high ones; bfc 1 is a no-op."""
    # -- test_batch_frequencies_match_formula
    freqs = np.array([100.0, 500.0, 1500.0])
    bfc = 1.05
    w = _well(freqs, bfc)

    expected = freqs * bfc ** (100.0 / freqs)
    assert np.allclose(w.frequencies, expected)

    # -- test_batch_low_frequency_perturbed_more_than_high
    freqs = np.array([100.0, 1500.0])
    bfc = 1.1
    w = _well(freqs, bfc)

    factors = w.frequencies / freqs
    # With bfc > 1 the exponent 100/freq is larger for low frequencies,
    # so low frequencies are scaled more than high ones.
    assert factors[0] > factors[1]

    # -- test_batch_bfc_one_is_noop
    freqs = np.array([100.0, 500.0, 1500.0])
    w = _well(freqs, bfc=1.0)

    assert np.allclose(w.frequencies, freqs)


def test_individual_mode_uses_ifc_unchanged() -> None:
    freqs = np.array([100.0, 500.0])
    w = Well(name="W", pes_ids=[0], freq_mode=FreqMode.INDIVIDUAL)
    w._freq = freqs
    w.ifc = [1.2, 0.8]

    assert np.allclose(w.frequencies, freqs * np.array([1.2, 0.8]))


def test_set_uncertainties_per_mode_rotors_and_unknown_key(tmp_path, monkeypatch) -> None:
    import pytest
    monkeypatch.chdir(tmp_path)  # the error path writes Well.log in cwd
    settings = {'std_we': 1.0, 'std_bfc': 1.2, 'std_freq': 1.3, 'std_hrs': 0.1,
                'std_mrc': 1.4, 'std_fact': 0.5, 'std_be': 2.0, 'n_mdl': 5}

    # (a) batch mode, perturbed energy
    w = Well(name='W', pes_ids=[0], pert_e=True, freq_mode=FreqMode.BATCH)
    w._freq = np.array([100.0, 200.0, 300.0])
    w.h_rotors = ['h0', 'h1']
    w.m_rotors = ['m0']
    w.set_uncertainties(settings)
    assert w.uncertainties == {'W__we': 1.0, 'W__bfc': 1.2, 'W__hrs0': 0.1,
                               'W__hrs1': 0.1, 'W__mrc0': 1.4}

    # (b) individual mode, energy not perturbed
    w = Well(name='W', pes_ids=[0], pert_e=False, freq_mode=FreqMode.INDIVIDUAL)
    w._freq = np.array([100.0, 200.0, 300.0])
    w.h_rotors = ['h0']
    w.set_uncertainties(settings)
    assert w.uncertainties == {'W__freq00': 1.3, 'W__freq01': 1.3,
                               'W__freq02': 1.3, 'W__hrs0': 0.1}

    # (c) unknown std_ key
    w = Well(name='W', pes_ids=[0])
    with pytest.raises(TypeError, match='Unknown parameter'):
        w.set_uncertainties({'std_bogus': 1.0})
