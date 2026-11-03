"""CI-safe tests for ``QueueingSystem`` (Slurm queue bookkeeping), with no
Slurm access: submission and the running-job query are patched where needed.

* Multi-PES kin jobs: one Slurm array per model (``n_pes`` slots),
  ``factually_ready`` and ``_pickup_kin`` on per-slot MESS outputs, and an
  absent ``use_automech`` byte-identical to ``False``.
* The automech branch: python driver scripts instead of MESS ``.inp``
  inputs, the leading-underscore pass-1 output bookkeeping, and
  ``clean_files`` per job status.
* Sim jobs: ``factually_ready`` counts unique template scripts (regression:
  it compared len(scripts) with n_exp, so jobs with shared cantera
  templates were never submitted).
* Submission limits: max_cpu / max_mem / max_jobs / max_user_jobs.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus, QueueingSystem


# ===========================================================================
# Multi-PES kin jobs (classic MESS path)
# ===========================================================================
def _mp_settings(tmp_path: Path) -> dict:
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
        "q_name": "day-long-cpu",
        "max_user_jobs": 128,
        "scratch_base": str(tmp_path) + "/",
        "project_name": "GAME_TEST",
    }


def _mp_qs(tmp_path: Path) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_test.log"))
    return QueueingSystem(settings=_mp_settings(tmp_path), nel=4, klog=klog)


def test_create_sub_file_kin_classic(tmp_path) -> None:
    """The classic kin submission file is a Slurm array over the PES slots
    running mess on each .inp, stores n_pes, and is byte-identical whether
    use_automech is absent or False."""
    _tmp_root = tmp_path
    # -- test_create_sub_file_kin_uses_slurm_array_and_stores_n_pes
    tmp_path = _tmp_root / 'test_create_sub_file_kin_uses_slurm_array_and_stores_n_pes'
    tmp_path.mkdir(parents=True)
    qs = _mp_qs(tmp_path)

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

    # -- test_kin_slurm_absent_vs_false_use_automech_is_byte_identical
    tmp_path = _tmp_root / 'test_kin_slurm_absent_vs_false_use_automech_is_byte_identical'
    tmp_path.mkdir(parents=True)
    # An absent use_automech key must behave exactly like an explicit False.
    # Same location so the embedded scratchdir path is identical; only the
    # use_automech flag varies between the two writes.
    slurm = tmp_path / "G0000E0009.slurm"
    klog = KMOLogger(filename=str(tmp_path / "byte.log"))

    settings_absent = _mp_settings(tmp_path)
    qs_absent = QueueingSystem(settings=settings_absent, nel=4, klog=klog)
    qs_absent.add_to_q(
        name="G0000E0009", idx=0, location=str(tmp_path),
        jtype="kin", ressources=(2, 500), n_pes=2)
    bytes_absent = slurm.read_bytes()

    settings_false = _mp_settings(tmp_path)
    settings_false["use_automech"] = False
    qs_false = QueueingSystem(settings=settings_false, nel=4, klog=klog)
    qs_false.add_to_q(
        name="G0000E0009", idx=0, location=str(tmp_path),
        jtype="kin", ressources=(2, 500), n_pes=2)
    bytes_false = slurm.read_bytes()

    assert bytes_absent == bytes_false
    assert b"mess G0000E0009P${FORMATTED_ID}.inp" in bytes_absent

    # -- test_create_sub_file_kin_classic_runs_mess
    tmp_path = _tmp_root / 'test_create_sub_file_kin_classic_runs_mess'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=False)
    _kin_job(qs, tmp_path, "G0000E0002", n_pes=2)

    content = (tmp_path / "G0000E0002.slurm").read_text()
    assert "mess G0000E0002P${FORMATTED_ID}.inp" in content
    assert ".py" not in content


def test_factually_ready_kin_classic(tmp_path) -> None:
    """A classic kin job is ready only with exactly n_pes non-empty .inp files."""
    _tmp_root = tmp_path
    # -- test_factually_ready_kin_requires_exact_count_and_non_empty_files
    tmp_path = _tmp_root / 'test_factually_ready_kin_requires_exact_count_and_non_empty_files'
    tmp_path.mkdir(parents=True)
    qs = _mp_qs(tmp_path)
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

    # -- test_factually_ready_kin_false_path_keys_off_inp
    tmp_path = _tmp_root / 'test_factually_ready_kin_false_path_keys_off_inp'
    tmp_path.mkdir(parents=True)
    settings = _mp_settings(tmp_path)
    settings["use_automech"] = False
    klog = KMOLogger(filename=str(tmp_path / "false_ready.log"))
    qs = QueueingSystem(settings=settings, nel=4, klog=klog)
    qs.add_to_q(
        name="G0000E0010", idx=0, location=str(tmp_path),
        jtype="kin", ressources=(2, 500), n_pes=2)
    job = qs.kin_q[0]

    # A .py driver must not satisfy the classic (mess) path.
    (tmp_path / "G0000E0010P00.py").write_text("driver")
    (tmp_path / "G0000E0010P01.py").write_text("driver")
    assert not qs.factually_ready(job)

    (tmp_path / "G0000E0010P00.inp").write_text("input-0")
    (tmp_path / "G0000E0010P01.inp").write_text("input-1")
    assert qs.factually_ready(job)


def test_pickup_kin_classic(tmp_path, monkeypatch) -> None:
    """Classic kin pickup: all outputs and clean err files mark the job picked
    up; a non-empty log err marks it failed and removes the outputs."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_pickup_kin_marks_picked_up_when_all_outputs_and_errs_are_clean
    tmp_path = _tmp_root / 'test_pickup_kin_marks_picked_up_when_all_outputs_and_errs_are_clean'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _mp_qs(tmp_path)
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

    # -- test_pickup_kin_marks_failed_on_non_empty_log_err_and_removes_outputs
    tmp_path = _tmp_root / 'test_pickup_kin_marks_failed_on_non_empty_log_err_and_removes_outputs'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _mp_qs(tmp_path)
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


# ===========================================================================
# use_automech branch: driver scripts, pass-1 copies, clean_files
# ===========================================================================
def _am_settings(tmp_path: Path, use_automech: bool) -> dict:
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


def _am_qs(tmp_path: Path, use_automech: bool = True) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_automech.log"))
    return QueueingSystem(
        settings=_am_settings(tmp_path, use_automech), nel=4, klog=klog)


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
    qs = _am_qs(tmp_path, use_automech=True)
    _kin_job(qs, tmp_path, "G0000E0001", n_pes=3)

    content = (tmp_path / "G0000E0001.slurm").read_text()
    assert "python G0000E0001P${FORMATTED_ID}.py" in content
    assert "mess " not in content


# ---------------------------------------------------------------------------
# factually_ready: globs P*.py under automech
# ---------------------------------------------------------------------------
def test_factually_ready_automech_keys_off_py_and_excludes_underscore(
        tmp_path: Path) -> None:
    qs = _am_qs(tmp_path, use_automech=True)
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
def test_pickup_kin_automech(tmp_path, monkeypatch) -> None:
    """Automech kin pickup ignores the leading-underscore pass-1 copies when
    counting n_pes outputs; on failure it removes the final .out and keeps the
    underscore copy."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_pickup_kin_excludes_underscore_pass1_and_counts_n_pes
    tmp_path = _tmp_root / 'test_pickup_kin_excludes_underscore_pass1_and_counts_n_pes'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _am_qs(tmp_path, use_automech=True)
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

    # -- test_pickup_kin_failed_removes_final_out_keeps_underscore
    tmp_path = _tmp_root / 'test_pickup_kin_failed_removes_final_out_keeps_underscore'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _am_qs(tmp_path, use_automech=True)
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
        ('type', np.str_, 3), ('n_pes', np.int16),
        ('collector_id', np.int32)])
    return np.array(
        [(0, name, str(tmp_path), status, 2, 500, 'kin', 1, 0)],
        dtype=dtype)[0]


def test_kin_job_array_dtype_matches_queue_jobdata(tmp_path) -> None:
    """The hand-built job record of the clean_files tests stays in lockstep
    with QueueingSystem.jobdata (collector_id appended last, int32)."""
    qs = _am_qs(tmp_path, use_automech=True)
    assert _kin_job_array(tmp_path, 'G0000E0001', 'ready').dtype == qs.jobdata
    assert qs.jobdata.names[-1] == 'collector_id'
    assert qs.jobdata['collector_id'] == np.int32


def test_clean_files_success(tmp_path) -> None:
    """A finished automech kin job removes the drivers, underscore copies and
    per-slot log/inp files, and keeps the final outputs."""
    _tmp_root = tmp_path
    # -- test_clean_files_success_removes_py_and_underscore
    tmp_path = _tmp_root / 'test_clean_files_success_removes_py_and_underscore'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=True)
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

    # -- test_clean_files_success_removes_per_slot_log_and_inp: On success the
    #    per-slot .log and .inp artifacts are swept too.
    tmp_path = _tmp_root / 'test_clean_files_success_removes_per_slot_log_and_inp'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=True)
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

    # -- test_clean_files_success_keeps_final_outputs: Cleanup must never touch
    #    the per-slot MESS outputs being read back.
    tmp_path = _tmp_root / 'test_clean_files_success_keeps_final_outputs'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=True)
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


def test_clean_files_failed(tmp_path) -> None:
    """A failed automech kin job removes the logs but retains the .inp and .py
    inputs for the retry."""
    _tmp_root = tmp_path
    # -- test_clean_files_failed_removes_log_but_retains_inp: Per-slot .log is
    #    always swept; .inp is kept for resubmission.
    tmp_path = _tmp_root / 'test_clean_files_failed_removes_log_but_retains_inp'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=True)
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

    # -- test_clean_files_failed_retains_py
    tmp_path = _tmp_root / 'test_clean_files_failed_retains_py'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=True)
    name = "G0000E0007"
    py = tmp_path / f"{name}P00.py"
    under = tmp_path / f"_{name}P00.out"
    for f in (py, under):
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.FAILED.value)
    qs.clean_files(job, clear_err=False)

    # On failure the driver script is kept so the job can be resubmitted.
    assert py.exists()


def test_clean_files_leaves_ready_and_sim_jobs_untouched(tmp_path) -> None:
    """A ready kin job keeps every per-slot artifact; a sim job leaves the per-
    slot kin artifacts alone."""
    _tmp_root = tmp_path
    # -- test_clean_files_ready_job_keeps_every_per_slot_artifact: READY jobs
    #    are pending resubmission: nothing is deleted.
    tmp_path = _tmp_root / 'test_clean_files_ready_job_keeps_every_per_slot_artifact'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=True)
    name = "G0000E0010"
    artifacts = [tmp_path / f"{name}P00.{ext}"
                 for ext in ("log", "inp", "py", "aux")]
    for f in artifacts:
        f.write_text("x")

    job = _kin_job_array(tmp_path, name, JobStatus.READY.value)
    qs.clean_files(job, clear_err=True)

    assert all(f.exists() for f in artifacts)

    # -- test_clean_files_sim_job_leaves_per_slot_kin_artifacts: The per-slot
    #    sweep is gated on job type 'kin'.
    tmp_path = _tmp_root / 'test_clean_files_sim_job_leaves_per_slot_kin_artifacts'
    tmp_path.mkdir(parents=True)
    qs = _am_qs(tmp_path, use_automech=True)
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


# ===========================================================================
# Sim jobs: factually_ready counts unique templates
# ===========================================================================
def _sim_exp(tpl_idx: int, new_tpl: bool) -> SimpleNamespace:
    return SimpleNamespace(tpl_idx=tpl_idx, new_tpl=new_tpl)


def _sim_settings(tmp_path: Path, experiments: list) -> dict:
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
        "q_name": "day-long-cpu",
        "max_user_jobs": 128,
        "scratch_base": str(tmp_path) + "/",
        "project_name": "GAME_TEST",
        "experiments": experiments,
    }


def _sim_qs(tmp_path: Path, experiments: list) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_sim_test.log"))
    return QueueingSystem(
        settings=_sim_settings(tmp_path, experiments),
        nel=4,
        klog=klog,
    )


def test_factually_ready_sim_template_counts(tmp_path) -> None:
    """Sim readiness counts unique template scripts: all unique, shared, all the
    same template; an empty script is not ready."""
    _tmp_root = tmp_path
    # -- test_factually_ready_sim_all_unique_templates: When every experiment
    #    has a unique template, n_exp scripts needed.
    tmp_path = _tmp_root / 'test_factually_ready_sim_all_unique_templates'
    tmp_path.mkdir(parents=True)
    exps = [_sim_exp(0, True), _sim_exp(1, True), _sim_exp(2, True)]
    qs = _sim_qs(tmp_path, exps)
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

    # -- test_factually_ready_sim_shared_templates_requires_unique_count:
    #    Experiments sharing a template only produce one script.
    tmp_path = _tmp_root / 'test_factually_ready_sim_shared_templates_requires_unique_count'
    tmp_path.mkdir(parents=True)
    # 3 experiments, but exp 1 reuses exp 0's template
    exps = [_sim_exp(0, True), _sim_exp(0, False), _sim_exp(2, True)]
    qs = _sim_qs(tmp_path, exps)
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

    # -- test_factually_ready_sim_all_same_template: All experiments share one
    #    template → only 1 script is expected.
    tmp_path = _tmp_root / 'test_factually_ready_sim_all_same_template'
    tmp_path.mkdir(parents=True)
    exps = [_sim_exp(0, True), _sim_exp(0, False), _sim_exp(0, False)]
    qs = _sim_qs(tmp_path, exps)
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

    # -- test_factually_ready_sim_empty_script_not_ready: An empty script file
    #    means the write is not yet complete.
    tmp_path = _tmp_root / 'test_factually_ready_sim_empty_script_not_ready'
    tmp_path.mkdir(parents=True)
    exps = [_sim_exp(0, True)]
    qs = _sim_qs(tmp_path, exps)
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


# ===========================================================================
# Submission limits
# ===========================================================================
def _lim_settings(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
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
        "q_name": "day-long-cpu",
        "max_user_jobs": 128,
        "scratch_base": str(tmp_path) + "/",
        "project_name": "GAME_TEST",
        "experiments": [],
    }
    cfg.update(overrides)
    return cfg


def _lim_qs(tmp_path: Path, **overrides: Any) -> QueueingSystem:
    klog = KMOLogger(filename=str(tmp_path / "q_sys_limits_test.log"))
    return QueueingSystem(
        settings=_lim_settings(tmp_path, **overrides),
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


def test_max_jobs_and_max_user_jobs_block_then_resume(tmp_path, monkeypatch) -> None:
    """max_jobs and max_user_jobs stop submission, which resumes once jobs
    finish."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_max_jobs_stops_submission_then_resumes_after_finish
    tmp_path = _tmp_root / 'test_max_jobs_stops_submission_then_resumes_after_finish'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _lim_qs(tmp_path, max_jobs=1, max_cpu=64, max_mem=64000)
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

    # -- test_max_user_jobs_blocks_and_then_resumes
    tmp_path = _tmp_root / 'test_max_user_jobs_blocks_and_then_resumes'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _lim_qs(
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


def test_max_cpu_and_max_mem_block_submission(tmp_path, monkeypatch) -> None:
    """A second submission that would exceed max_cpu or max_mem is held back."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_max_cpu_blocks_second_submission
    tmp_path = _tmp_root / 'test_max_cpu_blocks_second_submission'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _lim_qs(tmp_path, max_jobs=8, max_cpu=2, max_mem=64000)
        submitted, _running_ids = _patch_runtime(qs, monkeypatch)

        qs.add_to_q("JCPU1", 0, str(tmp_path), "kin", (2, 100), n_pes=1)
        qs.add_to_q("JCPU2", 1, str(tmp_path), "kin", (2, 100), n_pes=1)

        qs.run()
        qs.run()

        assert submitted == ["JCPU1"]
        assert qs.kin_q[1]["status"] == JobStatus.READY.value

    # -- test_max_mem_blocks_second_submission
    tmp_path = _tmp_root / 'test_max_mem_blocks_second_submission'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        qs = _lim_qs(tmp_path, max_jobs=8, max_cpu=64, max_mem=1000)
        submitted, _running_ids = _patch_runtime(qs, monkeypatch)

        qs.add_to_q("JMEM1", 0, str(tmp_path), "kin", (1, 1000), n_pes=1)
        qs.add_to_q("JMEM2", 1, str(tmp_path), "kin", (1, 1000), n_pes=1)

        qs.run()
        qs.run()

        assert submitted == ["JMEM1"]
        assert qs.kin_q[1]["status"] == JobStatus.READY.value




# ===========================================================================
# Prompt mode (use_automech + prompt_reactions): the collector job, submitted
# with afterok on the array, tracked next to it, its files and logs kept out
# of the kin globs. _pickup_kin ignores the PED / microcanonical outputs in
# every mode.
# ===========================================================================
import fnmatch  # noqa: E402
from subprocess import PIPE  # noqa: E402

from kimeco.q_sys import (COLLECTOR_SUBMIT_FAILED,  # noqa: E402
                          SIDE_OUTPUT_SUFFIXES)
from kimeco.templates.kin_arr_py_tpl import kin_arr_py_tpl  # noqa: E402
from kimeco.templates.slurm_arr import slurmarrtpl  # noqa: E402

PNAME = 'G0001E0007'
_POPEN_KWARGS = {'shell': False, 'stdout': PIPE, 'stdin': PIPE,
                 'stderr': PIPE}


def _prompt_qs(tmp_path: Path, prompt: bool = True, use_automech: bool = True,
               **extra: Any) -> QueueingSystem:
    settings = _am_settings(tmp_path, use_automech)
    settings['prompt_reactions'] = prompt
    settings.update(extra)
    klog = KMOLogger(filename=str(tmp_path / 'q_sys_prompt.log'))
    return QueueingSystem(settings=settings, nel=4, klog=klog)


def _ready_job(qs: QueueingSystem, loc: Path, n_pes: int = 2,
               name: str = PNAME, ext: str = 'py', collector: bool = True):
    """Kin job in slot 0 with its drivers (and collector script) written."""
    qs.add_to_q(name=name, idx=0, location=str(loc), jtype='kin',
                ressources=(2, 500), n_pes=n_pes)
    for slot in range(n_pes):
        (loc / f'{name}P{slot:02d}.{ext}').write_text('driver')
    if collector:
        (loc / f'prompt_{name}.py').write_text('collector')
    return qs.kin_q[0]


class _FakePopen:
    """Popen stand-in: one scripted (returncode, stdout, stderr) per call,
    or an exception to raise."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        code, out, err = reply
        return SimpleNamespace(returncode=code,
                               communicate=lambda: (out.encode(),
                                                    err.encode()))


def _submitting(monkeypatch, tmp_path: Path, replies: list) -> _FakePopen:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('kimeco.q_sys.time.sleep', lambda _: None)
    popen = _FakePopen(replies)
    monkeypatch.setattr('kimeco.q_sys.Popen', popen)
    return popen


@pytest.mark.parametrize('array_id, collector_id', [(4242, 4243),
                                                    (777, 90001)])
def test_submit_prompt_chains_collector_on_array_id(
        tmp_path, monkeypatch, array_id, collector_id) -> None:
    """Two sbatch calls: the array, then the collector with
    --dependency=afterok:<captured array id> --kill-on-invalid-dep=yes and
    its own .slurm (written by add_to_q); both ids recorded, RUNNING."""
    popen = _submitting(monkeypatch, tmp_path, [
        (0, f'Submitted batch job {array_id}\n', ''),
        (0, f'Submitted batch job {collector_id}\n', '')])
    qs = _prompt_qs(tmp_path)
    job = _ready_job(qs, tmp_path)
    qs.submit(job)
    assert [c[0] for c in popen.calls] == [
        ['sbatch', f'{PNAME}.slurm'],
        ['sbatch', f'--dependency=afterok:{array_id}',
         '--kill-on-invalid-dep=yes', f'prompt_{PNAME}.slurm']]
    assert all(c[1] == _POPEN_KWARGS for c in popen.calls)
    assert (tmp_path / popen.calls[1][0][-1]).is_file()
    rec = qs.kin_q[0]
    assert (int(rec['sub_id']), int(rec['collector_id'])) == (array_id,
                                                              collector_id)
    assert rec['status'] == JobStatus.RUNNING.value
    assert qs.collector_submit_failed(0) is False


@pytest.mark.parametrize('prompt, use_automech', [(False, True), (True, False)],
                         ids=['prompt_off', 'no_automech'])
def test_submit_non_prompt_single_sbatch_unchanged(tmp_path, monkeypatch,
                                                   prompt,
                                                   use_automech) -> None:
    """Outside prompt mode (prompt off, or prompt without use_automech): one
    sbatch call, argv and Popen kwargs as before, collector field 0, no
    collector .slurm."""
    popen = _submitting(monkeypatch, tmp_path,
                        [(0, 'Submitted batch job 31\n', '')])
    qs = _prompt_qs(tmp_path, prompt=prompt, use_automech=use_automech)
    job = _ready_job(qs, tmp_path, ext='py' if use_automech else 'inp',
                     collector=False)
    qs.submit(job)
    assert popen.calls == [(['sbatch', f'{PNAME}.slurm'], _POPEN_KWARGS)]
    assert int(qs.kin_q[0]['sub_id']) == 31
    assert int(qs.kin_q[0]['collector_id']) == 0
    assert qs.kin_q[0]['status'] == JobStatus.RUNNING.value
    assert not (tmp_path / f'prompt_{PNAME}.slurm').exists()


def test_submit_prompt_array_failure_submits_no_collector(
        tmp_path, monkeypatch) -> None:
    popen = _submitting(monkeypatch, tmp_path,
                        [(1, '', 'sbatch: error: invalid partition')])
    qs = _prompt_qs(tmp_path)
    qs.submit(_ready_job(qs, tmp_path))
    assert len(popen.calls) == 1
    assert qs.kin_q[0]['status'] == JobStatus.READY.value
    assert int(qs.kin_q[0]['collector_id']) == 0
    assert qs.collector_submit_failed(0) is False


@pytest.mark.parametrize('reply, needle', [
    ((1, '', 'sbatch: error: Job dependency problem'),
     'Job dependency problem'),
    ((0, 'unexpected', ''), 'unexpected'),
    (OSError('sbatch not found'), 'sbatch not found'),
], ids=['rc1', 'unparsable', 'oserror'])
def test_submit_prompt_collector_failure_records_sentinel(
        tmp_path, monkeypatch, reply, needle) -> None:
    """A failed collector sbatch never raises: the array id is kept, status
    RUNNING, the collector field holds COLLECTOR_SUBMIT_FAILED (-1) and an
    error naming the job and the array is logged."""
    _submitting(monkeypatch, tmp_path,
                [(0, 'Submitted batch job 4242\n', ''), reply])
    qs = _prompt_qs(tmp_path)
    errors: list[str] = []
    monkeypatch.setattr(qs.klog, 'error', lambda msg, *a, **k:
                        errors.append(str(msg)))
    qs.submit(_ready_job(qs, tmp_path))
    rec = qs.kin_q[0]
    assert COLLECTOR_SUBMIT_FAILED == -1
    assert int(rec['sub_id']) == 4242
    assert int(rec['collector_id']) == COLLECTOR_SUBMIT_FAILED
    assert rec['status'] == JobStatus.RUNNING.value
    assert qs.collector_submit_failed(0) is True
    assert len(errors) == 1, errors
    assert f'prompt collector of {PNAME} (array 4242)' in errors[0]
    assert needle in errors[0]


def test_collector_submit_failed_only_for_submitted_jobs(tmp_path) -> None:
    """True only for a RUNNING or FINISHED job holding the sentinel (the
    fields of unused or waiting slots mean nothing)."""
    qs = _prompt_qs(tmp_path)
    _ready_job(qs, tmp_path)
    for status, collector_id, expected in (
            (JobStatus.RUNNING, -1, True), (JobStatus.FINISHED, -1, True),
            (JobStatus.READY, -1, False), (JobStatus.PICKED_UP, -1, False),
            (JobStatus.NOT_IN_QUEUE, -1, False),
            (JobStatus.RUNNING, 4243, False), (JobStatus.RUNNING, 0, False)):
        qs.kin_q[0]['status'] = status.value
        qs.kin_q[0]['collector_id'] = collector_id
        assert qs.collector_submit_failed(0) is expected, (status,
                                                           collector_id)


def test_factually_ready_prompt_needs_collector_files(tmp_path) -> None:
    """Prompt mode: the drivers are not enough, the collector script and
    .slurm must exist and be non-empty (so the array never goes without
    its collector); the collector script is not counted as a driver."""
    qs = _prompt_qs(tmp_path)
    job = _ready_job(qs, tmp_path, collector=False)
    script = tmp_path / f'prompt_{PNAME}.py'
    slurm = tmp_path / f'prompt_{PNAME}.slurm'
    assert slurm.stat().st_size > 0
    assert not qs.factually_ready(job)
    script.write_text('')
    assert not qs.factually_ready(job)
    script.write_text('collector')
    assert qs.factually_ready(job)
    slurm.write_text('')
    assert not qs.factually_ready(job)
    slurm.unlink()
    assert not qs.factually_ready(job)

    plain = tmp_path / 'plain'
    plain.mkdir()
    qs = _prompt_qs(plain, prompt=False)
    job = _ready_job(qs, plain, collector=False)
    assert qs.factually_ready(job)


def test_create_sub_file_prompt_keeps_array_and_adds_collector(
        tmp_path) -> None:
    """The array .slurm is byte-identical to the non-prompt one (template
    computed here); prompt mode adds prompt_<name>.slurm: one job, 1 CPU,
    the kin memory, the queue, logs/prompt_<name>.* (not matching the
    logs/<name>_* glob), MPLBACKEND=Agg, then python prompt_<name>.py; no
    --exclude line when exclude_nodes is empty."""
    array = tmp_path / f'{PNAME}.slurm'
    expected = slurmarrtpl.format(
        n_exp=1, exclude_nodes='', nprocs=2, filename=PNAME,
        sub_queue='day-long-cpu', mem_mb=500, scratchdir=str(tmp_path)) + \
        kin_arr_py_tpl.format(filename=PNAME)
    _prompt_qs(tmp_path, prompt=False).add_to_q(
        name=PNAME, idx=0, location=str(tmp_path), jtype='kin',
        ressources=(2, 500), n_pes=2)
    assert array.read_text() == expected
    assert sorted(p.name for p in tmp_path.iterdir()
                  if p.suffix == '.slurm') == [array.name]
    array.unlink()

    qs = _prompt_qs(tmp_path)
    qs.add_to_q(name=PNAME, idx=0, location=str(tmp_path), jtype='kin',
                ressources=(2, 500), n_pes=2)
    assert array.read_text() == expected
    lines = (tmp_path / f'prompt_{PNAME}.slurm').read_text().splitlines()
    for line in ('#SBATCH -c 1', '#SBATCH --mem=500',
                 '#SBATCH -p day-long-cpu',
                 f'#SBATCH -o logs/prompt_{PNAME}.stdout',
                 f'#SBATCH -e logs/prompt_{PNAME}.err',
                 'export MPLBACKEND=Agg', f'python prompt_{PNAME}.py'):
        assert line in lines, (line, lines)
    assert lines.index('export MPLBACKEND=Agg') < lines.index(
        f'python prompt_{PNAME}.py')
    assert not any('--exclude' in ln or '--array' in ln for ln in lines)
    for log in (f'logs/prompt_{PNAME}.stdout', f'logs/prompt_{PNAME}.err'):
        assert not fnmatch.fnmatch(log, f'logs/{PNAME}_*')
    assert int(qs.kin_q[0]['collector_id']) == 0

    other = tmp_path / 'excl'
    other.mkdir()
    _prompt_qs(other, exclude_nodes='n1,n2').add_to_q(
        name=PNAME, idx=0, location=str(other), jtype='kin',
        ressources=(2, 500), n_pes=1)
    assert '#SBATCH --exclude=n1,n2' in (
        other / f'prompt_{PNAME}.slurm').read_text().splitlines()


def test_sim_job_in_prompt_mode_has_no_collector(tmp_path) -> None:
    qs = _prompt_qs(tmp_path, experiments=[_sim_exp(0, True)], n_exp=1)
    qs.add_to_q(name=f'{PNAME}S', idx=0, location=str(tmp_path),
                jtype='sim', ressources=(1, 500))
    assert int(qs.sim_q[0]['collector_id']) == 0
    assert not list(tmp_path.glob('prompt_*'))


def _running(qs: QueueingSystem, idx: int, sub_id: int, collector_id: int,
             jtype: str = 'kin') -> None:
    q = qs.kin_q if jtype == 'kin' else qs.sim_q
    q[idx]['sub_id'] = sub_id
    q[idx]['collector_id'] = collector_id
    q[idx]['status'] = JobStatus.RUNNING.value


@pytest.mark.parametrize('squeue, status', [
    ([100, 101], JobStatus.RUNNING), ([101], JobStatus.RUNNING),
    ([100], JobStatus.RUNNING), ([], JobStatus.FINISHED),
    ([999], JobStatus.FINISHED)],
    ids=['both', 'collector_only', 'array_only', 'none', 'other_job'])
def test_actualize_finishes_only_when_array_and_collector_left(
        tmp_path, monkeypatch, squeue, status) -> None:
    qs = _prompt_qs(tmp_path)
    _ready_job(qs, tmp_path)
    _running(qs, 0, 100, 101)
    monkeypatch.setattr(qs, 'get_all_running',
                        lambda: np.array(squeue, dtype=np.int32))
    qs.actualize()
    assert JobStatus(qs.kin_q[0]['status']) == status


def test_actualize_without_collector_and_mixed_queue(tmp_path,
                                                     monkeypatch) -> None:
    """Collector 0 (non-prompt kin, sim) or the sentinel: FINISHED as soon
    as the array left (as before). Mixed queue: only the job whose
    collector is gone finishes; PICKED_UP / FAILED -> NOT_IN_QUEUE."""
    qs = _prompt_qs(tmp_path, experiments=[_sim_exp(0, True)], n_exp=1)
    for idx in range(4):
        qs.add_to_q(name=f'G0001E000{idx}', idx=idx, location=str(tmp_path),
                    jtype='kin', ressources=(1, 100), n_pes=1)
    qs.add_to_q(name='G0001E0000S', idx=0, location=str(tmp_path),
                jtype='sim', ressources=(1, 100))
    _running(qs, 0, 100, 101)                       # collector listed
    _running(qs, 1, 200, 0)                         # no collector
    _running(qs, 2, 300, COLLECTOR_SUBMIT_FAILED)   # sbatch failed
    qs.kin_q[3]['status'] = JobStatus.PICKED_UP.value
    _running(qs, 0, 400, 0, jtype='sim')
    monkeypatch.setattr(qs, 'get_all_running',
                        lambda: np.array([101], dtype=np.int32))
    qs.actualize()
    assert [JobStatus(s) for s in qs.kin_q['status']] == [
        JobStatus.RUNNING, JobStatus.FINISHED, JobStatus.FINISHED,
        JobStatus.NOT_IN_QUEUE]
    assert JobStatus(qs.sim_q[0]['status']) == JobStatus.FINISHED


def test_prompt_status_flow_waits_for_collector(tmp_path,
                                                monkeypatch) -> None:
    """Through run(): READY -> both submitted -> RUNNING; array leaves the
    queue -> still RUNNING; collector leaves -> FINISHED; nothing
    resubmitted."""
    popen = _submitting(monkeypatch, tmp_path, [
        (0, 'Submitted batch job 500\n', ''),
        (0, 'Submitted batch job 501\n', '')])
    qs = _prompt_qs(tmp_path)
    _ready_job(qs, tmp_path)
    squeue = {500, 501}
    monkeypatch.setattr(qs, 'get_all_running', lambda: np.array(
        sorted(squeue), dtype=np.int32))
    assert JobStatus(qs.kin_q[0]['status']) == JobStatus.READY
    qs.run()
    assert JobStatus(qs.kin_q[0]['status']) == JobStatus.RUNNING
    assert len(popen.calls) == 2
    squeue.discard(500)
    qs.run()
    assert JobStatus(qs.kin_q[0]['status']) == JobStatus.RUNNING
    squeue.discard(501)
    qs.run()
    assert JobStatus(qs.kin_q[0]['status']) == JobStatus.FINISHED
    assert len(popen.calls) == 2


def _outputs(loc: Path, name: str, side: bool = True) -> list[Path]:
    paths = [loc / f'{name}P00.out', loc / f'{name}P01.out']
    if side:
        paths += [loc / f'{name}P{s:02d}{suffix}' for s in (0, 1)
                  for suffix in SIDE_OUTPUT_SUFFIXES]
    for path in paths:
        path.write_text('data')
    return paths


@pytest.mark.parametrize('use_automech', [True, False])
def test_pickup_kin_ignores_ped_and_ke_outputs_in_every_mode(
        tmp_path, monkeypatch, use_automech) -> None:
    """Regression (all modes): P*_ped.out / P*_ke.out next to the rate
    outputs no longer break the n_pes count (6 != 2 kept the job from ever
    being picked up)."""
    monkeypatch.setattr('kimeco.q_sys.time.sleep', lambda _: None)
    qs = _prompt_qs(tmp_path, prompt=False, use_automech=use_automech)
    job = _kin_job(qs, tmp_path, PNAME, n_pes=2)
    job['status'] = JobStatus.RUNNING.value
    (tmp_path / 'logs').mkdir()
    for slot in (0, 1):
        (tmp_path / 'logs' / f'{PNAME}_{slot}.err').write_text('')
    _outputs(tmp_path, PNAME)
    assert qs._pickup_kin(job) is True
    assert JobStatus(job['status']) == JobStatus.PICKED_UP


def test_rate_outputs_excludes_side_and_pass1_outputs(tmp_path) -> None:
    rates = _outputs(tmp_path, PNAME)[:2]
    (tmp_path / f'_{PNAME}P00.out').write_text('pass1')
    assert SIDE_OUTPUT_SUFFIXES == ('_ped.out', '_ke.out')
    assert QueueingSystem._rate_outputs(f'{tmp_path}/{PNAME}') == [
        str(p) for p in rates]


def test_pickup_kin_failure_branches_with_side_outputs(tmp_path,
                                                       monkeypatch) -> None:
    """A non-empty logs/<name>_*.err still removes every non-underscore
    P*.out, side outputs included (unchanged); a non-empty P*.err removes
    the rate outputs only."""
    monkeypatch.setattr('kimeco.q_sys.time.sleep', lambda _: None)
    for case in ('log_err', 'p_err'):
        loc = tmp_path / case
        (loc / 'logs').mkdir(parents=True)
        qs = _prompt_qs(loc, prompt=False)
        job = _kin_job(qs, loc, PNAME, n_pes=2)
        job['status'] = JobStatus.RUNNING.value
        (loc / 'logs' / f'{PNAME}_0.err').write_text(
            'boom' if case == 'log_err' else '')
        (loc / 'logs' / f'{PNAME}_1.err').write_text('')
        if case == 'p_err':
            (loc / f'{PNAME}P00.err').write_text('boom')
        outs = _outputs(loc, PNAME)
        pass1 = loc / f'_{PNAME}P00.out'
        pass1.write_text('pass1')
        assert qs._pickup_kin(job) is False
        assert JobStatus(job['status']) == JobStatus.FAILED
        assert pass1.exists()
        removed = outs if case == 'log_err' else outs[:2]
        assert [p for p in outs if not p.exists()] == removed, case


def test_pickup_kin_prompt_ignores_collector_err(tmp_path,
                                                 monkeypatch) -> None:
    """A non-empty collector log (logs/prompt_<name>.err) is not one of
    the array's logs/<name>_*.err: the job is picked up."""
    monkeypatch.setattr('kimeco.q_sys.time.sleep', lambda _: None)
    qs = _prompt_qs(tmp_path)
    job = _kin_job(qs, tmp_path, PNAME, n_pes=2)
    job['status'] = JobStatus.FINISHED.value
    (tmp_path / 'logs').mkdir()
    for slot in (0, 1):
        (tmp_path / 'logs' / f'{PNAME}_{slot}.err').write_text('')
    (tmp_path / 'logs' / f'prompt_{PNAME}.err').write_text('Traceback\n')
    _outputs(tmp_path, PNAME)
    assert qs._pickup_kin(job) is True
    assert JobStatus(job['status']) == JobStatus.PICKED_UP


def _artifacts(loc: Path, name: str) -> dict[str, Path]:
    (loc / 'logs').mkdir(exist_ok=True)
    names = {
        'slurm': f'{name}.slurm', 'log': f'{name}.log', 'aux': f'{name}.aux',
        'p_log': f'{name}P00.log', 'p_inp': f'{name}P00.inp',
        'p_aux': f'{name}P00.aux', 'p_py': f'{name}P00.py',
        'pass1': f'_{name}P00.out', 'ped': f'{name}P00_ped.out',
        'ke': f'{name}P00_ke.out', 'rate': f'{name}P00.out',
        'c_py': f'prompt_{name}.py', 'c_slurm': f'prompt_{name}.slurm',
        'c_json': f'prompt_{name}.json', 'arr_err': f'logs/{name}_0.err',
        'c_err': f'logs/prompt_{name}.err',
        'c_out': f'logs/prompt_{name}.stdout',
        'p_stderr': f'{name}P00.stderr', 'p_failed': f'{name}P00.out.failed'}
    paths = {key: loc / rel for key, rel in names.items()}
    for path in paths.values():
        path.write_text('x')
    return paths


def test_clean_files_prompt_picked_up_and_failed(tmp_path) -> None:
    """Prompt PICKED_UP: also removes the PED / microcanonical outputs and
    the collector script and .slurm, and the driver's MESS ``.stderr``;
    keeps the rate .out, the prompt JSON, logs/ and a failed pass's
    ``.out.failed``. Prompt FAILED: removes nothing (diagnosis)."""
    loc = tmp_path / 'picked'
    loc.mkdir()
    paths = _artifacts(loc, PNAME)
    _prompt_qs(loc).clean_files(
        _kin_job_array(loc, PNAME, JobStatus.PICKED_UP.value),
        clear_err=True)
    kept = {k for k, p in paths.items() if p.exists()}
    assert kept == {'rate', 'c_json', 'arr_err', 'c_err', 'c_out',
                    'p_failed'}

    loc = tmp_path / 'failed'
    loc.mkdir()
    paths = _artifacts(loc, PNAME)
    _prompt_qs(loc).clean_files(
        _kin_job_array(loc, PNAME, JobStatus.FAILED.value), clear_err=False)
    assert all(p.exists() for p in paths.values())


@pytest.mark.parametrize('prompt, use_automech', [(False, True), (True, False)],
                         ids=['prompt_off', 'no_automech'])
def test_clean_files_non_prompt_unchanged(tmp_path, prompt,
                                          use_automech) -> None:
    """Outside prompt mode: PICKED_UP keeps the side outputs (never deleted
    before), anything named prompt_* and ``.out.failed``, and removes the
    driver's MESS ``.stderr``; FAILED still removes P*.log and keeps the
    drivers and the ``.stderr``."""
    loc = tmp_path / 'picked'
    loc.mkdir()
    paths = _artifacts(loc, PNAME)
    qs = _prompt_qs(loc, prompt=prompt, use_automech=use_automech)
    qs.clean_files(_kin_job_array(loc, PNAME, JobStatus.PICKED_UP.value),
                   clear_err=True)
    kept = {k for k, p in paths.items() if p.exists()}
    assert kept == {'rate', 'ped', 'ke', 'c_py', 'c_slurm', 'c_json',
                    'arr_err', 'c_err', 'c_out', 'p_failed'}

    loc = tmp_path / 'failed'
    loc.mkdir()
    paths = _artifacts(loc, PNAME)
    qs = _prompt_qs(loc, prompt=prompt, use_automech=use_automech)
    qs.clean_files(_kin_job_array(loc, PNAME, JobStatus.FAILED.value),
                   clear_err=False)
    gone = {k for k, p in paths.items() if not p.exists()}
    assert gone == {'slurm', 'log', 'aux', 'p_log', 'p_aux'}


# ---------------------------------------------------------------------------
# Automech driver files: <name>P<slot>.stderr and <name>P<slot>.out.failed
# ---------------------------------------------------------------------------
def _stderr_files(loc: Path, name: str = PNAME) -> list[Path]:
    paths = [loc / f'{name}P00.stderr', loc / f'{name}P01.stderr']
    for path in paths:
        path.write_text('MESS warning: reference energy\n')
    return paths


@pytest.mark.parametrize('prompt', [False, True], ids=['non_prompt', 'prompt'])
def test_clean_files_picked_up_removes_driver_stderr(tmp_path,
                                                     prompt) -> None:
    """A picked-up automech kin job (prompt or not) loses its per-PES MESS
    ``.stderr`` files; its rate outputs and another model's ``.stderr``
    stay."""
    stderr = _stderr_files(tmp_path)
    other = tmp_path / 'G0001E0002P00.stderr'
    other.write_text('other model')
    rates = [tmp_path / f'{PNAME}P0{s}.out' for s in (0, 1)]
    for path in rates:
        path.write_text('rates')
    _prompt_qs(tmp_path, prompt=prompt).clean_files(
        _kin_job_array(tmp_path, PNAME, JobStatus.PICKED_UP.value),
        clear_err=True)
    assert not any(p.exists() for p in stderr)
    assert other.read_text() == 'other model'
    assert all(p.read_text() == 'rates' for p in rates)


@pytest.mark.parametrize('prompt', [False, True], ids=['non_prompt', 'prompt'])
def test_clean_files_failed_keeps_driver_stderr(tmp_path, prompt) -> None:
    """A failed kin job keeps its ``.stderr`` and ``.out.failed`` files (the
    diagnosis of the failed MESS pass)."""
    stderr = _stderr_files(tmp_path)
    failed = tmp_path / f'{PNAME}P01.out.failed'
    failed.write_text('partial')
    _prompt_qs(tmp_path, prompt=prompt).clean_files(
        _kin_job_array(tmp_path, PNAME, JobStatus.FAILED.value),
        clear_err=False)
    assert all(p.exists() for p in stderr)
    assert failed.read_text() == 'partial'


def test_clean_files_ready_and_sim_jobs_keep_driver_stderr(tmp_path) -> None:
    """A READY kin job (pending resubmission) and a finished sim job of the
    same name leave the ``.stderr`` files alone."""
    stderr = _stderr_files(tmp_path)
    qs = _am_qs(tmp_path, use_automech=True)
    qs.clean_files(_kin_job_array(tmp_path, PNAME, JobStatus.READY.value),
                   clear_err=True)
    sim = _kin_job_array(tmp_path, PNAME, JobStatus.PICKED_UP.value)
    sim['type'] = 'sim'
    qs.clean_files(sim, clear_err=True)
    assert all(p.exists() for p in stderr)


def _running_kin_job(tmp_path: Path) -> tuple[QueueingSystem, Any]:
    qs = _am_qs(tmp_path, use_automech=True)
    job = _kin_job(qs, tmp_path, PNAME, n_pes=2)
    job['status'] = JobStatus.RUNNING.value
    (tmp_path / 'logs').mkdir()
    for slot in (0, 1):
        (tmp_path / 'logs' / f'{PNAME}_{slot}.err').write_text('')
    return qs, job


def test_pickup_kin_ignores_driver_stderr(tmp_path, monkeypatch) -> None:
    """Every rate output present and a non-empty ``P00.stderr`` (MESS
    warnings): picked up. The legacy ``P*.err`` check does not match
    ``.stderr``."""
    monkeypatch.setattr('kimeco.q_sys.time.sleep', lambda _: None)
    qs, job = _running_kin_job(tmp_path)
    _outputs(tmp_path, PNAME, side=False)
    _stderr_files(tmp_path)
    assert qs._pickup_kin(job) is True
    assert JobStatus(job['status']) == JobStatus.PICKED_UP


def test_pickup_kin_never_counts_out_failed(tmp_path, monkeypatch) -> None:
    """Slot 0 has its rate output, slot 1 only ``.out.failed``: not picked
    up (one rate output for two PESs), status unchanged, nothing deleted."""
    monkeypatch.setattr('kimeco.q_sys.time.sleep', lambda _: None)
    qs, job = _running_kin_job(tmp_path)
    rate = tmp_path / f'{PNAME}P00.out'
    rate.write_text('rates')
    failed = tmp_path / f'{PNAME}P01.out.failed'
    failed.write_text('partial')
    assert QueueingSystem._rate_outputs(f'{tmp_path}/{PNAME}') == [str(rate)]
    assert qs._pickup_kin(job) is True
    assert JobStatus(job['status']) == JobStatus.RUNNING
    assert rate.exists() and failed.read_text() == 'partial'
