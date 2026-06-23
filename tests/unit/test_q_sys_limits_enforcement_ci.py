from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus, QueueingSystem


def _settings(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "max_jobs": 32,
        "max_cpu": 128,
        "max_mem": 64000,
        "cpu_kin": 2,
        "cpu_sim": 1,
        "mem_kin": 500,
        "mem_sim": 500,
        "n_exp": 1,
        "exclude_nodes": "",
        "max_user_jobs": 128,
        "scratch_base": str(tmp_path) + "/",
        "project_name": "GAME_TEST",
        "experiments": [],
    }
    cfg.update(overrides)
    return cfg


def _queueing_system(tmp_path: Path, **overrides: Any) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_limits_test.log"))
    return QueueingSystem(
        settings=_settings(tmp_path, **overrides),
        nel=4,
        klog=klog,
    )


def _patch_runtime(
    qs: QueueingSystem,
    monkeypatch: pytest.MonkeyPatch,
    external_ids: set[int] | None = None,
) -> tuple[list[str], set[int]]:
    submitted: list[str] = []
    running_ids: set[int] = set(external_ids or set())
    next_id: int = 1000

    def fake_submit(job: Any) -> None:
        nonlocal next_id
        jid = next_id
        next_id += 1
        name = str(job["name"])
        for q in qs.queues:
            match = np.where(q["name"] == name)[0]
            if len(match) == 0:
                continue
            q_idx = int(match[0])
            q["sub_id"][q_idx] = np.int32(jid)
            q["status"][q_idx] = JobStatus.RUNNING.value
            break
        running_ids.add(jid)
        submitted.append(name)

    def fake_get_all_running() -> np.ndarray:
        ids = np.array(sorted(running_ids), dtype=np.int32)
        qs.current_user_jobs = len(ids)
        return ids

    monkeypatch.setattr(qs, "submit", fake_submit)
    monkeypatch.setattr(qs, "get_all_running", fake_get_all_running)
    return submitted, running_ids


def test_max_jobs_stops_submission_then_resumes_after_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qs = _queueing_system(tmp_path, max_jobs=1, max_cpu=64, max_mem=64000)
    submitted, running_ids = _patch_runtime(qs, monkeypatch)

    qs.add_to_q("J0001", 0, str(tmp_path), "kin", (1, 100), n_pes=1)
    qs.add_to_q("J0002", 1, str(tmp_path), "kin", (1, 100), n_pes=1)

    qs.run()
    assert submitted == ["J0001"]
    assert qs.kin_q[1]["status"] == JobStatus.READY.value

    # One running job keeps max_jobs saturated.
    qs.run()
    assert submitted == ["J0001"]

    # Mark running job as finished in SLURM and actualize resources.
    running_ids.clear()
    qs.run()
    assert submitted == ["J0001"]
    assert qs.kin_q[0]["status"] == JobStatus.FINISHED.value

    # Next scheduling pass can submit the waiting job.
    qs.run()
    assert submitted == ["J0001", "J0002"]
    assert qs.kin_q[1]["status"] == JobStatus.RUNNING.value


def test_max_cpu_blocks_second_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qs = _queueing_system(tmp_path, max_jobs=8, max_cpu=2, max_mem=64000)
    submitted, _running_ids = _patch_runtime(qs, monkeypatch)

    qs.add_to_q("JCPU1", 0, str(tmp_path), "kin", (2, 100), n_pes=1)
    qs.add_to_q("JCPU2", 1, str(tmp_path), "kin", (2, 100), n_pes=1)

    qs.run()
    qs.run()

    assert submitted == ["JCPU1"]
    assert qs.kin_q[1]["status"] == JobStatus.READY.value


def test_max_mem_blocks_second_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qs = _queueing_system(tmp_path, max_jobs=8, max_cpu=64, max_mem=1000)
    submitted, _running_ids = _patch_runtime(qs, monkeypatch)

    qs.add_to_q("JMEM1", 0, str(tmp_path), "kin", (1, 1000), n_pes=1)
    qs.add_to_q("JMEM2", 1, str(tmp_path), "kin", (1, 1000), n_pes=1)

    qs.run()
    qs.run()

    assert submitted == ["JMEM1"]
    assert qs.kin_q[1]["status"] == JobStatus.READY.value


def test_max_user_jobs_blocks_and_then_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qs = _queueing_system(
        tmp_path,
        max_jobs=8,
        max_cpu=64,
        max_mem=64000,
        max_user_jobs=1,
    )
    submitted, running_ids = _patch_runtime(
        qs,
        monkeypatch,
        external_ids={999},
    )

    qs.add_to_q("JUSR1", 0, str(tmp_path), "kin", (1, 100), n_pes=1)

    # External job saturates user quota, so nothing should be submitted.
    qs.run()
    assert submitted == []
    assert qs.kin_q[0]["status"] == JobStatus.READY.value

    # Once quota is free, scheduler submits again.
    running_ids.clear()
    qs.run()
    assert submitted == ["JUSR1"]
    assert qs.kin_q[0]["status"] == JobStatus.RUNNING.value
