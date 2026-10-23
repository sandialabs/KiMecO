"""CI-safe tests for graceful mechanism-not-loaded handling in validate_sop.

Defect B: when the mechanism is not loaded, ``validate_sop`` must not blow up
the callback with an unhandled raise. The None check now lives inside the try
block so the shared ``except`` renders a red error message, and a ``finally``
tears down the temporary log StreamHandler and restores the logger level so
repeated Load & Validate clicks do not leak handlers or mutate global logging.
"""

import logging

import pytest

from kimeco.gui.input_sections import sop_section
from kimeco.gui.input_sections.sop_section import validate_sop

LOGGER_NAME = "kmo_start"


class _ExplodingReader:
    """MessInputReader stand-in that fails the test if ever constructed."""

    def __init__(self, *args, **kwargs):
        raise AssertionError(
            "MessInputReader must not be built when mechanism is not loaded"
        )


def _msg_text(component) -> str:
    """Flatten a Dash component tree into its concatenated string content."""
    parts: list[str] = []

    def _walk(node):
        if isinstance(node, str):
            parts.append(node)
            return
        children = getattr(node, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for c in children:
                _walk(c)
        else:
            _walk(children)

    _walk(component)
    return " ".join(parts)


@pytest.fixture
def no_mechanism(monkeypatch):
    """Force get_loaded_kinmec -> None and guard MessInputReader."""
    monkeypatch.setattr(sop_section, "get_loaded_kinmec", lambda *_a, **_k: None)
    monkeypatch.setattr(sop_section, "MessInputReader", _ExplodingReader)


def test_mechanism_none_reports_invalid_without_raising(no_mechanism) -> None:
    """With no mechanism loaded validate_sop does not raise and reports the SOP
    as invalid."""
    # -- test_mechanism_none_does_not_raise
    result = validate_sop(1, "mech.yaml", ["a.inp"], [])
    assert isinstance(result, tuple)
    assert len(result) == 6

    # -- test_mechanism_none_reports_invalid
    result = validate_sop(1, "mech.yaml", ["a.inp"], [])
    # sop-valid-store data is the 3rd output.
    assert result[2] is False
    text = _msg_text(result[0]).lower()
    assert "not loaded" in text


def test_no_handler_leak_and_logger_level_restored(no_mechanism) -> None:
    """No handler leaks, the logger level is restored, and repeated calls do not
    accumulate handlers."""
    # -- test_mechanism_none_leaves_no_leaked_handler
    logger = logging.getLogger(LOGGER_NAME)
    before = list(logger.handlers)
    validate_sop(1, "mech.yaml", ["a.inp"], [])
    assert logger.handlers == before

    # -- test_logger_level_restored
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.WARNING)
    validate_sop(1, "mech.yaml", ["a.inp"], [])
    assert logger.level == logging.WARNING

    # -- test_repeated_calls_do_not_accumulate_handlers
    logger = logging.getLogger(LOGGER_NAME)
    baseline = len(logger.handlers)
    for _ in range(5):
        validate_sop(1, "mech.yaml", ["a.inp"], [])
    assert len(logger.handlers) == baseline


def test_early_guards_add_no_handler(monkeypatch) -> None:
    """The empty cantera-yaml and empty MESS-files early guards add no handler."""
    _mp_root = monkeypatch
    # -- test_empty_ct_yaml_early_guard_adds_no_handler: Edge: missing ct_yaml
    #    short-circuits before any handler is created.
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(sop_section, "MessInputReader", _ExplodingReader)
        logger = logging.getLogger(LOGGER_NAME)
        before = list(logger.handlers)
        result = validate_sop(1, "", ["a.inp"], [])
        assert len(result) == 6
        assert result[2] is False
        assert logger.handlers == before

    # -- test_empty_mess_files_early_guard_adds_no_handler: Edge: empty
    #    mess_files list also short-circuits cleanly.
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(sop_section, "MessInputReader", _ExplodingReader)
        logger = logging.getLogger(LOGGER_NAME)
        before = list(logger.handlers)
        result = validate_sop(1, "mech.yaml", [], [])
        assert len(result) == 6
        assert result[2] is False
        assert logger.handlers == before


