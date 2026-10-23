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

from kimeco.default_settings import mandatory_keys


_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLE_INPUT = _REPO_ROOT / 'example' / 'input.json'


def _example_json() -> dict:
    with open(_EXAMPLE_INPUT, mode='r') as handle:
        return json.load(fp=handle)


def test_example_input_defines_every_mandatory_key() -> None:
    """The example input exists and is valid JSON; every mandatory keyword
    is present, correctly typed and non-empty (the ``basic_checks``
    mandatory-key loop cancels nothing); ``q_name`` is a non-blank string
    (regression: it was absent, so every run cancelled at start-up)."""
    assert _EXAMPLE_INPUT.is_file()
    data = _example_json()
    assert isinstance(data, dict)

    failures: list[str] = []
    for key in sorted(mandatory_keys):
        expected = type(mandatory_keys[key])
        if key not in data:
            failures.append(f"'{key}' is mandatory but missing from example/input.json")
        elif not isinstance(data[key], expected):
            failures.append(f"'{key}' should be {expected}, got {type(data[key])}")
        elif len(data[key]) == 0:
            failures.append(f"'{key}' is mandatory but empty")
    assert not failures, "\n".join(failures)

    q_name = data.get('q_name')
    assert isinstance(q_name, str)
    assert q_name.strip() == q_name
    assert q_name != ''
