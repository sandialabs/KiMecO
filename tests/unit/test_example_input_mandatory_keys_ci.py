"""CI-safe tests asserting the shipped ``example/input.json`` is complete.

``KMOInput.basic_checks`` cancels the run when any key of
``default_settings.mandatory_keys`` is missing (or has the wrong type), so a
tracked example input that omits one is a latent defect: users copy it and the
run dies at start-up. This is exactly how a missing ``q_name`` slipped
through. Pure JSON + dict work -- no SLURM, MESS or subprocess access.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kimeco.default_settings import mandatory_keys


_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_INPUT = _REPO_ROOT / 'example' / 'input.json'


def _example_json() -> dict:
    with open(_EXAMPLE_INPUT, mode='r') as handle:
        return json.load(fp=handle)


def test_example_input_exists_and_is_valid_json() -> None:
    assert _EXAMPLE_INPUT.is_file()
    assert isinstance(_example_json(), dict)


@pytest.mark.parametrize('key', sorted(mandatory_keys))
def test_example_input_defines_mandatory_key(key: str) -> None:
    """Every mandatory keyword is present, correctly typed and non-empty."""
    data = _example_json()

    assert key in data, (
        f"'{key}' is mandatory but missing from example/input.json")
    assert isinstance(data[key], type(mandatory_keys[key])), (
        f"'{key}' should be {type(mandatory_keys[key])}, "
        f"got {type(data[key])}")
    assert len(data[key]) > 0, f"'{key}' is mandatory but empty"


def test_example_input_passes_the_basic_checks_mandatory_loop() -> None:
    """Mirror of the ``basic_checks`` mandatory-key loop: nothing cancels."""
    data = _example_json()
    missing = [key for key in mandatory_keys if key not in data]
    mistyped = [
        key for key, value in mandatory_keys.items()
        if key in data and not isinstance(data[key], type(value))
    ]

    assert missing == []
    assert mistyped == []


def test_example_input_q_name_is_a_non_blank_string() -> None:
    """Regression: q_name was absent, so every run cancelled at start-up."""
    q_name = _example_json().get('q_name')

    assert isinstance(q_name, str)
    assert q_name.strip() == q_name
    assert q_name != ''
