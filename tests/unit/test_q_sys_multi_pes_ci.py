from __future__ import annotations

from pathlib import Path

import pytest

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus, QueueingSystem


def _settings(tmp_path: Path) -> dict:
    return {
        "max_jobs": 32,
        "max_cpu": 128,
        "max_mem": 64000,
        "cpu_kin": 2,
        "cpu_sim": 1,
        "mem_kin": 500,
        "mem_sim": 500,
        "n_exp": 2,
        "exclude_nodes": "",
        "max_user_jobs": 128,
        "scratch_base": str(tmp_path) + "/",
        "project_name": "GAME_TEST",
    }


def _queueing_system(tmp_path: Path) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_test.log"))
    return QueueingSystem(settings=_settings(tmp_path), nel=4, nhlp=0, klog=klog)


def test_create_sub_file_kin_uses_slurm_array_and_stores_n_pes(tmp_path: Path) -> None:
    qs = _queueing_system(tmp_path)

    qs.add_to_q(
        name="G0000E0001",
        idx=0,
        location=str(tmp_path),
        jtype="kin",
        ressources=(2, 500),
        n_pes=3,
    )

    sub_file = tmp_path / "G0000E0001.slurm"
    assert sub_file.exists()

    content = sub_file.read_text()
    assert "#SBATCH --array=0-2" in content
    assert "mess G0000E0001P${FORMATTED_ID}.inp" in content
    assert int(qs.kin_q[0]["n_pes"]) == 3


def test_factually_ready_kin_requires_exact_count_and_non_empty_files(
    tmp_path: Path,
) -> None:
    qs = _queueing_system(tmp_path)
    qs.add_to_q(
        name="G0000E0002",
        idx=0,
        location=str(tmp_path),
        jtype="kin",
        ressources=(2, 500),
        n_pes=2,
    )
    job = qs.kin_q[0]

    assert not qs.factually_ready(job)

    (tmp_path / "G0000E0002P00.inp").write_text("input-0")
    (tmp_path / "G0000E0002P01.inp").write_text("input-1")
    assert qs.factually_ready(job)

    (tmp_path / "G0000E0002P02.inp").write_text("extra")
    assert not qs.factually_ready(job)


def test_pickup_kin_marks_picked_up_when_all_outputs_and_errs_are_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _queueing_system(tmp_path)
    qs.add_to_q(
        name="G0000E0003",
        idx=0,
        location=str(tmp_path),
        jtype="kin",
        ressources=(2, 500),
        n_pes=2,
    )
    job = qs.kin_q[0]
    job["status"] = JobStatus.RUNNING.value

    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "G0000E0003_0.err").write_text("")
    (logs / "G0000E0003_1.err").write_text("")
    (tmp_path / "G0000E0003P00.out").write_text("ok")
    (tmp_path / "G0000E0003P01.out").write_text("ok")

    monkeypatch.setattr("kimeco.q_sys.time.sleep", lambda _: None)

    clear_err = qs._pickup_kin(job)

    assert clear_err is True
    assert JobStatus(job["status"]) == JobStatus.PICKED_UP


def test_pickup_kin_marks_failed_on_non_empty_log_err_and_removes_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qs = _queueing_system(tmp_path)
    qs.add_to_q(
        name="G0000E0004",
        idx=0,
        location=str(tmp_path),
        jtype="kin",
        ressources=(2, 500),
        n_pes=2,
    )
    job = qs.kin_q[0]
    job["status"] = JobStatus.RUNNING.value

    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "G0000E0004_0.err").write_text("boom")
    (logs / "G0000E0004_1.err").write_text("")

    out0 = tmp_path / "G0000E0004P00.out"
    out1 = tmp_path / "G0000E0004P01.out"
    out0.write_text("partial")
    out1.write_text("partial")

    monkeypatch.setattr("kimeco.q_sys.time.sleep", lambda _: None)

    clear_err = qs._pickup_kin(job)

    assert clear_err is False
    assert JobStatus(job["status"]) == JobStatus.FAILED
    assert not out0.exists()
    assert not out1.exists()
