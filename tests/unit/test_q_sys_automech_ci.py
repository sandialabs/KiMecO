"""CI-safe tests for the automech branch of the queueing system.

Covers create_sub_file, factually_ready, _pickup_kin and clean_files behavior
when ``use_automech`` is enabled: python driver scripts instead of MESS ``.inp``
inputs, and the leading-underscore pass-1 output bookkeeping.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus, QueueingSystem


def _settings(tmp_path: Path, use_automech: bool) -> dict:
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
        "q_name": "day-long-cpu",
        "scratch_base": str(tmp_path) + "/",
        "project_name": "GAME_TEST",
        "use_automech": use_automech,
    }


def _qs(tmp_path: Path, use_automech: bool = True) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_automech.log"))
    return QueueingSystem(
        settings=_settings(tmp_path, use_automech), nel=4, klog=klog)


def _kin_job(qs: QueueingSystem, tmp_path: Path, name: str, n_pes: int):
    qs.add_to_q(
        name=name,
        idx=0,
        location=str(tmp_path),
        jtype="kin",
        ressources=(2, 500),
        n_pes=n_pes,
    )
    return qs.kin_q[0]


# ---------------------------------------------------------------------------
# create_sub_file: python driver vs mess input
# ---------------------------------------------------------------------------
def test_create_sub_file_kin_automech_runs_python_driver(
        tmp_path: Path) -> None:
    qs = _qs(tmp_path, use_automech=True)
    _kin_job(qs, tmp_path, "G0000E0001", n_pes=3)

    content = (tmp_path / "G0000E0001.slurm").read_text()
    assert "python G0000E0001P${FORMATTED_ID}.py" in content
    assert "mess " not in content


def test_create_sub_file_kin_classic_runs_mess(tmp_path: Path) -> None:
    qs = _qs(tmp_path, use_automech=False)
    _kin_job(qs, tmp_path, "G0000E0002", n_pes=2)

    content = (tmp_path / "G0000E0002.slurm").read_text()
    assert "mess G0000E0002P${FORMATTED_ID}.inp" in content
    assert ".py" not in content


# ---------------------------------------------------------------------------
# factually_ready: globs P*.py under automech
# ---------------------------------------------------------------------------
def test_factually_ready_automech_keys_off_py_and_excludes_underscore(
        tmp_path: Path) -> None:
    qs = _qs(tmp_path, use_automech=True)
    job = _kin_job(qs, tmp_path, "G0000E0003", n_pes=2)

    assert not qs.factually_ready(job)

    (tmp_path / "G0000E0003P00.py").write_text("driver-0")
    (tmp_path / "G0000E0003P01.py").write_text("driver-1")
    # Leading-underscore pass-1 artifacts must not count toward readiness.
    (tmp_path / "_G0000E0003P00.py").write_text("noise")
    assert qs.factually_ready(job)

    # A .inp is irrelevant on the automech path.
    (tmp_path / "G0000E0003P02.inp").write_text("ignored")
    assert qs.factually_ready(job)


# ---------------------------------------------------------------------------
# _pickup_kin: counts final outputs, excludes underscore pass-1 files
# ---------------------------------------------------------------------------
def test_pickup_kin_excludes_underscore_pass1_and_counts_n_pes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qs = _qs(tmp_path, use_automech=True)
    job = _kin_job(qs, tmp_path, "G0000E0004", n_pes=2)
    job["status"] = JobStatus.RUNNING.value

    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "G0000E0004_0.err").write_text("")
    (logs / "G0000E0004_1.err").write_text("")
    # Final outputs (exactly n_pes) plus leading-underscore pass-1 copies.
    (tmp_path / "G0000E0004P00.out").write_text("ok")
    (tmp_path / "G0000E0004P01.out").write_text("ok")
    (tmp_path / "_G0000E0004P00.out").write_text("pass1")
    (tmp_path / "_G0000E0004P01.out").write_text("pass1")

    monkeypatch.setattr("kimeco.q_sys.time.sleep", lambda _: None)

    clear_err = qs._pickup_kin(job)

    # Underscore files are excluded, so the count matches n_pes -> PICKED_UP.
    assert clear_err is True
    assert JobStatus(job["status"]) == JobStatus.PICKED_UP


def test_pickup_kin_failed_removes_final_out_keeps_underscore(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qs = _qs(tmp_path, use_automech=True)
    job = _kin_job(qs, tmp_path, "G0000E0005", n_pes=2)
    job["status"] = JobStatus.RUNNING.value

    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "G0000E0005_0.err").write_text("boom")
    (logs / "G0000E0005_1.err").write_text("")

    final0 = tmp_path / "G0000E0005P00.out"
    final1 = tmp_path / "G0000E0005P01.out"
    under0 = tmp_path / "_G0000E0005P00.out"
    under1 = tmp_path / "_G0000E0005P01.out"
    for f in (final0, final1, under0, under1):
        f.write_text("data")

    monkeypatch.setattr("kimeco.q_sys.time.sleep", lambda _: None)

    clear_err = qs._pickup_kin(job)

    assert clear_err is False
    assert JobStatus(job["status"]) == JobStatus.FAILED
    # Only the final outputs are removed; pass-1 copies are retained.
    assert not final0.exists() and not final1.exists()
    assert under0.exists() and under1.exists()


# ---------------------------------------------------------------------------
# clean_files: removes .py + underscore pass-1 on success, keeps .py on FAIL
# ---------------------------------------------------------------------------
def _kin_job_array(tmp_path: Path, name: str, status: str):
    dtype = np.dtype([
        ('sub_id', np.int32), ('name', np.str_, 20), ('loc', np.str_, 150),
        ('status', np.str_, 10), ('cpu', np.int16), ('mem', np.int32),
        ('type', np.str_, 3), ('n_pes', np.int16)])
    return np.array(
        [(0, name, str(tmp_path), status, 2, 500, 'kin', 1)], dtype=dtype)[0]


def test_clean_files_success_removes_py_and_underscore(tmp_path: Path) -> None:
    qs = _qs(tmp_path, use_automech=True)
    name = "G0000E0006"
    py = tmp_path / f"{name}P00.py"
    aux = tmp_path / f"{name}P00.aux"
    under = tmp_path / f"_{name}P00.out"
    for f in (py, aux, under):
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.PICKED_UP.value)
    qs.clean_files(job, clear_err=True)

    assert not py.exists()
    assert not aux.exists()
    assert not under.exists()


def test_clean_files_success_removes_per_slot_log_and_inp(
        tmp_path: Path) -> None:
    """On success the per-slot .log and .inp artifacts are swept too."""
    qs = _qs(tmp_path, use_automech=True)
    name = "G0000E0008"
    p_log = tmp_path / f"{name}P00.log"
    p_inp = tmp_path / f"{name}P00.inp"
    p_aux = tmp_path / f"{name}P00.aux"
    for f in (p_log, p_inp, p_aux):
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.PICKED_UP.value)
    qs.clean_files(job, clear_err=True)

    assert not p_log.exists()
    assert not p_inp.exists()
    assert not p_aux.exists()


def test_clean_files_failed_removes_log_but_retains_inp(
        tmp_path: Path) -> None:
    """Per-slot .log is always swept; .inp is kept for resubmission."""
    qs = _qs(tmp_path, use_automech=True)
    name = "G0000E0009"
    p_log = tmp_path / f"{name}P00.log"
    p_inp = tmp_path / f"{name}P00.inp"
    p_py = tmp_path / f"{name}P00.py"
    for f in (p_log, p_inp, p_py):
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.FAILED.value)
    qs.clean_files(job, clear_err=False)

    # .log carries no resubmission value and is removed on both branches.
    assert not p_log.exists()
    # Inputs and drivers survive so the job can be resubmitted as-is.
    assert p_inp.exists()
    assert p_py.exists()


def test_clean_files_ready_job_keeps_every_per_slot_artifact(
        tmp_path: Path) -> None:
    """READY jobs are pending resubmission: nothing is deleted."""
    qs = _qs(tmp_path, use_automech=True)
    name = "G0000E0010"
    artifacts = [tmp_path / f"{name}P00.{ext}"
                 for ext in ("log", "inp", "py", "aux")]
    for f in artifacts:
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.READY.value)
    qs.clean_files(job, clear_err=True)

    assert all(f.exists() for f in artifacts)


def test_clean_files_sim_job_leaves_per_slot_kin_artifacts(
        tmp_path: Path) -> None:
    """The per-slot sweep is gated on job type 'kin'."""
    qs = _qs(tmp_path, use_automech=True)
    name = "G0000E0011"
    p_log = tmp_path / f"{name}P00.log"
    p_inp = tmp_path / f"{name}P00.inp"
    for f in (p_log, p_inp):
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.PICKED_UP.value)
    job['type'] = 'sim'
    qs.clean_files(job, clear_err=True)

    assert p_log.exists()
    assert p_inp.exists()


def test_clean_files_success_keeps_final_outputs(tmp_path: Path) -> None:
    """Cleanup must never touch the per-slot MESS outputs being read back."""
    qs = _qs(tmp_path, use_automech=True)
    name = "G0000E0012"
    out0 = tmp_path / f"{name}P00.out"
    out1 = tmp_path / f"{name}P01.out"
    for f in (out0, out1):
        f.write_text("rates")
        (tmp_path / f.name.replace(".out", ".log")).write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.PICKED_UP.value)
    qs.clean_files(job, clear_err=True)

    assert out0.exists() and out1.exists()
    assert not (tmp_path / f"{name}P00.log").exists()
    assert not (tmp_path / f"{name}P01.log").exists()


def test_clean_files_failed_retains_py(tmp_path: Path) -> None:
    qs = _qs(tmp_path, use_automech=True)
    name = "G0000E0007"
    py = tmp_path / f"{name}P00.py"
    under = tmp_path / f"_{name}P00.out"
    for f in (py, under):
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.FAILED.value)
    qs.clean_files(job, clear_err=False)

    # On failure the driver script is kept so the job can be resubmitted.
    assert py.exists()
