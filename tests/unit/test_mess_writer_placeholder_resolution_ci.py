from __future__ import annotations

from typing import Any, cast

import pytest

from kimeco.writers.mess import MessWriter


class _DummyRotor:
    def __init__(self) -> None:
        self._sym = 3.5
        self.iem = 1200.0
        self.file = "pes_surface.dat"
        self.qlem = 800.0

    @property
    def symFact(self) -> float:
        return self._sym


class _DummyWell:
    def __init__(self) -> None:
        self.m_rotors = [_DummyRotor()]
        self.energy = 12.0

    def __getattr__(self, name: str) -> Any:
        if name == "r_scan(0)":
            return "scan-values"
        raise AttributeError(name)


class _DummySOP:
    def __init__(self) -> None:
        self.items = {"WELL": _DummyWell()}
        self.parameters_names: dict[str, str] = {}


def test_resolve_plain_placeholder() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    assert writer._resolve_placeholder("WELL.energy") == 12.0


def test_resolve_indexed_placeholder() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    assert writer._resolve_placeholder("WELL.m_rotors[0].symFact") == 3.5
    assert writer._resolve_placeholder("WELL.m_rotors[0].iem") == 1200.0
    assert (
        writer._resolve_placeholder("WELL.m_rotors[0].file")
        == "pes_surface.dat"
    )
    assert writer._resolve_placeholder("WELL.m_rotors[0].qlem") == 800.0


def test_resolve_method_like_token_is_preserved() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    assert writer._resolve_placeholder("WELL.r_scan(0)") == "scan-values"


def test_resolve_invalid_index_token_raises_value_error() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    with pytest.raises(ValueError, match="Invalid indexed token"):
        writer._resolve_placeholder("WELL.m_rotors[x].symFact")


def test_resolve_out_of_bounds_index_raises_value_error() -> None:
    writer = MessWriter(SOP=cast(Any, _DummySOP()), tpl=[])

    with pytest.raises(ValueError, match="Cannot index token"):
        writer._resolve_placeholder("WELL.m_rotors[1].symFact")
