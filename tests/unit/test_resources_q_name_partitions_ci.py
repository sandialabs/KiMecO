"""CI-safe tests for SLURM-partition discovery in the Resources section.

Defect C: ``q_name`` becomes a partition picker. ``_slurm_partitions`` queries
``sinfo`` and must degrade to an empty list whenever SLURM is unavailable, and
``_q_name_control`` renders a Dropdown when partitions exist and a free-text
Input otherwise. All subprocess access is mocked; no real SLURM is contacted.
"""

import subprocess
from types import SimpleNamespace

from dash import dcc

from kimeco.gui.input_sections import resources_section as rs
from kimeco.gui.input_sections.resources_section import (
    _q_name_control,
    _slurm_partitions,
)


def _fake_run(stdout):
    def _run(*_args, **_kwargs):
        return SimpleNamespace(stdout=stdout, returncode=0)
    return _run


def test_partitions_parsing(monkeypatch) -> None:
    """sinfo output parsing: standard lines, the default-partition star
    stripped, order-preserving dedup, blank lines skipped; empty or header-only
    output gives no partition."""
    _mp_root = monkeypatch
    # -- test_partitions_standard_parse
    with _mp_root.context() as monkeypatch:
        stdout = (
            "PARTITION AVAIL  TIMELIMIT  NODES  STATE\n"
            "short*    up      1:00:00      4   idle\n"
            "long      up   7-00:00:00      8   idle\n"
        )
        monkeypatch.setattr(rs.subprocess, "run", _fake_run(stdout))
        assert _slurm_partitions() == ["short", "long"]

    # -- test_partitions_strip_default_star
    with _mp_root.context() as monkeypatch:
        stdout = "HEADER\ngpu*   up  1:00  2 idle\n"
        monkeypatch.setattr(rs.subprocess, "run", _fake_run(stdout))
        assert _slurm_partitions() == ["gpu"]

    # -- test_partitions_dedup_order_preserving
    with _mp_root.context() as monkeypatch:
        stdout = (
            "HEADER\n"
            "a  up 1 idle\n"
            "b  up 1 idle\n"
            "a* up 1 mix\n"
            "b  up 1 alloc\n"
        )
        monkeypatch.setattr(rs.subprocess, "run", _fake_run(stdout))
        assert _slurm_partitions() == ["a", "b"]

    # -- test_partitions_skip_blank_lines
    with _mp_root.context() as monkeypatch:
        stdout = "HEADER\n\nshort up 1 idle\n\n"
        monkeypatch.setattr(rs.subprocess, "run", _fake_run(stdout))
        assert _slurm_partitions() == ["short"]

    # -- test_partitions_empty_stdout
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(rs.subprocess, "run", _fake_run(""))
        assert _slurm_partitions() == []

    # -- test_partitions_header_only
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(rs.subprocess, "run", _fake_run("PARTITION AVAIL\n"))
        assert _slurm_partitions() == []


def test_partitions_sinfo_failures_give_empty(monkeypatch) -> None:
    """A missing sinfo or a CalledProcessError gives an empty partition list."""
    _mp_root = monkeypatch
    # -- test_partitions_sinfo_missing
    with _mp_root.context() as monkeypatch:
        def _raise(*_a, **_k):
            raise FileNotFoundError("sinfo not found")
        monkeypatch.setattr(rs.subprocess, "run", _raise)
        assert _slurm_partitions() == []

    # -- test_partitions_called_process_error
    with _mp_root.context() as monkeypatch:
        def _raise(*_a, **_k):
            raise subprocess.CalledProcessError(1, "sinfo")
        monkeypatch.setattr(rs.subprocess, "run", _raise)
        assert _slurm_partitions() == []


def test_q_name_control(monkeypatch) -> None:
    """q_name is a dropdown when partitions are found, a free input otherwise,
    and the partitions are queried once."""
    _mp_root = monkeypatch
    # -- test_q_name_control_dropdown_when_partitions
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(rs, "_slurm_partitions", lambda: ["short", "long"])
        control = _q_name_control("short")
        assert isinstance(control, dcc.Dropdown)
        assert control.id == "res-q-name"
        assert [opt["value"] for opt in control.options] == ["short", "long"]
        assert control.value == "short"

    # -- test_q_name_control_input_when_no_partitions
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(rs, "_slurm_partitions", lambda: [])
        control = _q_name_control("day-long-cpu")
        assert isinstance(control, dcc.Input)
        assert control.id == "res-q-name"
        assert control.value == "day-long-cpu"

    # -- test_q_name_control_queries_partitions_once
    with _mp_root.context() as monkeypatch:
        calls = {"n": 0}

        def _counted():
            calls["n"] += 1
            return ["p1"]

        monkeypatch.setattr(rs, "_slurm_partitions", _counted)
        _q_name_control("p1")
        assert calls["n"] == 1


