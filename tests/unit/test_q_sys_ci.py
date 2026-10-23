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
        ('type', np.str_, 3), ('n_pes', np.int16)])
    return np.array(
        [(0, name, str(tmp_path), status, 2, 500, 'kin', 1)], dtype=dtype)[0]


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


