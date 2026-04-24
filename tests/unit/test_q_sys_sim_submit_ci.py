"""CI tests for sim job submission via QueueingSystem.factually_ready.

Regression coverage for the bug where factually_ready checked
len(scripts) == n_exp instead of the number of unique template scripts,
causing sim jobs with shared cantera templates to never be submitted.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import QueueingSystem


def _exp(tpl_idx: int, new_tpl: bool) -> SimpleNamespace:
    return SimpleNamespace(tpl_idx=tpl_idx, new_tpl=new_tpl)


def _settings(tmp_path: Path, experiments: list) -> dict:
    return {
        "max_jobs": 32,
        "max_cpu": 128,
        "max_mem": 64000,
        "cpu_kin": 2,
        "cpu_sim": 1,
        "mem_kin": 500,
        "mem_sim": 500,
        "n_exp": len(experiments),
        "exclude_nodes": "",
        "max_user_jobs": 128,
        "scratch_base": str(tmp_path) + "/",
        "project_name": "GAME_TEST",
        "experiments": experiments,
    }


def _qs(tmp_path: Path, experiments: list) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_sim_test.log"))
    return QueueingSystem(
        settings=_settings(tmp_path, experiments),
        nel=4,
        nhlp=0,
        klog=klog,
    )


# ---------------------------------------------------------------------------
# factually_ready — unique-template counting
# ---------------------------------------------------------------------------


def test_factually_ready_sim_all_unique_templates(tmp_path: Path) -> None:
    """When every experiment has a unique template, n_exp scripts needed."""
    exps = [_exp(0, True), _exp(1, True), _exp(2, True)]
    qs = _qs(tmp_path, exps)
    qs.add_to_q(
        name="G0000E0000S",
        idx=0,
        location=str(tmp_path),
        jtype="sim",
        ressources=(1, 500),
    )
    job = qs.sim_q[0]

    # No scripts yet → not ready
    assert not qs.factually_ready(job)

    # Write only 2 out of 3 scripts → still not ready
    (tmp_path / "G0000E0000S_exp00.py").write_text("script0")
    (tmp_path / "G0000E0000S_exp01.py").write_text("script1")
    assert not qs.factually_ready(job)

    # Write the third → ready
    (tmp_path / "G0000E0000S_exp02.py").write_text("script2")
    assert qs.factually_ready(job)


def test_factually_ready_sim_shared_templates_requires_unique_count(
    tmp_path: Path,
) -> None:
    """Experiments sharing a template only produce one script.
    factually_ready must accept fewer scripts than n_exp in that case.
    """
    # 3 experiments, but exp 1 reuses exp 0's template
    exps = [_exp(0, True), _exp(0, False), _exp(2, True)]
    qs = _qs(tmp_path, exps)
    qs.add_to_q(
        name="G0000E0001S",
        idx=0,
        location=str(tmp_path),
        jtype="sim",
        ressources=(1, 500),
    )
    job = qs.sim_q[0]

    # Only 2 unique tpl_idx values (0 and 2) → 2 scripts expected
    assert not qs.factually_ready(job)

    # Writing n_exp=3 scripts would be wrong; only 2 unique ones
    (tmp_path / "G0000E0001S_exp00.py").write_text("script0")
    assert not qs.factually_ready(job)

    (tmp_path / "G0000E0001S_exp02.py").write_text("script2")
    assert qs.factually_ready(job)


def test_factually_ready_sim_all_same_template(tmp_path: Path) -> None:
    """All experiments share one template → only 1 script is expected."""
    exps = [_exp(0, True), _exp(0, False), _exp(0, False)]
    qs = _qs(tmp_path, exps)
    qs.add_to_q(
        name="G0000E0002S",
        idx=0,
        location=str(tmp_path),
        jtype="sim",
        ressources=(1, 500),
    )
    job = qs.sim_q[0]

    assert not qs.factually_ready(job)

    (tmp_path / "G0000E0002S_exp00.py").write_text("script0")
    assert qs.factually_ready(job)


def test_factually_ready_sim_empty_script_not_ready(tmp_path: Path) -> None:
    """An empty script file means the write is not yet complete."""
    exps = [_exp(0, True)]
    qs = _qs(tmp_path, exps)
    qs.add_to_q(
        name="G0000E0003S",
        idx=0,
        location=str(tmp_path),
        jtype="sim",
        ressources=(1, 500),
    )
    job = qs.sim_q[0]

    (tmp_path / "G0000E0003S_exp00.py").write_text("")
    assert not qs.factually_ready(job)

    (tmp_path / "G0000E0003S_exp00.py").write_text("content")
    assert qs.factually_ready(job)
