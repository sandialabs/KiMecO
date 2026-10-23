"""CI-safe installation and import tests.

These tests follow the documented installation procedure from the user's
point of view: after ``pip install -e .`` (no extras) every public ``kimeco``
module must import, the console entry points must resolve and answer
``--help``, and nothing in the package may depend on the removed
``agentic_pipeline`` package or on ``anthropic``.

Imports are probed in a fresh subprocess so a module that only imports
because something else already populated ``sys.modules`` is caught. A
second pass blocks the automech modules (``mess_io``, ``phydat``, ``autoio``,
``autochem``) to prove the base install works without the ``[automech]``
extra. Every fresh-interpreter command of this module is started at once by
the module-scoped :func:`fresh_runs` fixture (not autouse, so
``-k editable_install`` starts none of them), which bounds the wall time by
the slowest process instead of their sum.

``test_editable_install_in_fresh_venv`` performs a real editable install in a
throw-away venv and is opt-in via ``KIMECO_RUN_INSTALL_TEST=1`` (it is run in
CI by .github/workflows/tests.yml).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import venv
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path

import pytest

from tests.unit.test_installation_extras_ci import (
    DOCUMENTED_VERIFY_COMMAND, import_or_skip)

REPO = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO / "kimeco"

PUBLIC_MODULES = [
    "kimeco",
    "kimeco.main",
    "kimeco.core",
    "kimeco.user_input",
    "kimeco.rate_coef",
    "kimeco.q_sys",
    "kimeco.simulation",
    "kimeco.writers.mess",
    "kimeco.writers.automech_kin",
    "kimeco.database.kimeco_db",
    "kimeco.postprocessing.postprocess",
    "kimeco.gui.kimecoapp",
    "kimeco.gui.kmo_start",
    "kimeco.gui.kinsection",
    "kimeco.gui.sopsection",
    "kimeco.gui.simsection",
    "kimeco.gui.corsection",
    "kimeco.gui.dbsection",
]

AUTOMECH_MODULES = ("mess_io", "phydat", "autoio", "autochem")

CONSOLE_SCRIPTS = {
    "kmo": "kimeco.main:main",
    "kmo_start": "kimeco.gui.kmo_start:main",
    "kmoui": "kimeco.gui.kimecoapp:main",
    "kmopp": "kimeco.postprocessing.postprocess:main",
}

FORBIDDEN_SOURCE_PATTERNS = (
    re.compile(r"\bagentic_pipeline\b"),
    re.compile(r"^\s*import\s+anthropic\b", re.M),
    re.compile(r"^\s*from\s+anthropic\b", re.M),
)


def _is_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _run_python(code: str, *, env: dict[str, str] | None = None,
                python: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [python or sys.executable, "-c", code],
        capture_output=True, text=True, timeout=300,
        cwd=str(REPO), env=env)


_IMPORT_ALL = """
import importlib, sys, traceback
{prelude}
failures = []
for name in {modules!r}:
    try:
        importlib.import_module(name)
    except Exception:
        failures.append(name + ":\\n" + traceback.format_exc())
if failures:
    sys.stderr.write("\\n".join(failures))
    sys.exit(1)
"""

_BLOCK_AUTOMECH = "\n".join(f"sys.modules[{m!r}] = None" for m in AUTOMECH_MODULES)


def _help_code(script: str) -> str:
    module, func = CONSOLE_SCRIPTS[script].split(":")
    return ("import sys\n"
            f"from {module} import {func}\n"
            f"sys.argv = [{script!r}, '--help']\n"
            f"{func}()\n")


# Every fresh-interpreter command of this module, by key.
FRESH_COMMANDS = {
    "import_all": _IMPORT_ALL.format(prelude="", modules=PUBLIC_MODULES),
    # Setting ``sys.modules[name] = None`` makes any ``import name`` raise
    # ImportError even where the automech packages are really installed.
    "import_all_no_automech": _IMPORT_ALL.format(prelude=_BLOCK_AUTOMECH,
                                                 modules=PUBLIC_MODULES),
    "block_probe": "import sys; sys.modules['mess_io'] = None; import mess_io",
    "help_kmo": _help_code("kmo"),
    "help_kmo_start": _help_code("kmo_start"),
    "import_agentic": "import agentic_pipeline",
    "verify_command": DOCUMENTED_VERIFY_COMMAND,
}


@pytest.fixture(scope="module")
def fresh_runs() -> dict[str, subprocess.CompletedProcess]:
    """Start every command of :data:`FRESH_COMMANDS` concurrently in its own
    fresh interpreter, then collect each result (timeout 300 s each)."""
    procs = {key: subprocess.Popen([sys.executable, "-c", code],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True,
                                   cwd=str(REPO))
             for key, code in FRESH_COMMANDS.items()}
    results: dict[str, subprocess.CompletedProcess] = {}
    try:
        for key, proc in procs.items():
            out, err = proc.communicate(timeout=300)
            results[key] = subprocess.CompletedProcess(
                proc.args, proc.returncode, out, err)
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
    return results


# ---------------------------------------------------------------------------
# Standard cases: every public module imports in a fresh interpreter
# ---------------------------------------------------------------------------
def test_all_public_modules_import_in_fresh_interpreter(fresh_runs) -> None:
    result = fresh_runs["import_all"]
    assert result.returncode == 0, (
        f"public module import failures:\n{result.stderr[-4000:]}")


def test_all_public_modules_import_without_automech_extra(fresh_runs) -> None:
    """The base install (no ``[automech]``) must import every public module.

    Also checks the blocking technique itself: a blocked ``mess_io`` really
    fails to import.
    """
    probe = fresh_runs["block_probe"]
    assert probe.returncode != 0
    assert "ImportError" in probe.stderr or "ModuleNotFoundError" in probe.stderr
    result = fresh_runs["import_all_no_automech"]
    assert result.returncode == 0, (
        "a public module requires an automech module at import time:\n"
        f"{result.stderr[-4000:]}")


def test_documented_verify_command_succeeds_in_fresh_interpreter(
        fresh_runs) -> None:
    """``python -c "import mess_io, phydat, kimeco"`` is the verification
    command documented in README/MANUAL/wiki. It runs in a clean subprocess so
    an ``IPython`` / ``py3Dmol`` pulled in transitively by ``mess_io`` cannot
    be masked by modules already in this process' ``sys.modules``."""
    import_or_skip("automech", "mess_io")
    proc = fresh_runs["verify_command"]
    assert proc.returncode == 0, (
        f"documented verification command failed:\n{proc.stderr[-2000:]}")


# ---------------------------------------------------------------------------
# Standard cases: console entry points
# ---------------------------------------------------------------------------
def _console_entry_points() -> dict[str, metadata.EntryPoint]:
    eps = metadata.entry_points(group="console_scripts")
    return {ep.name: ep for ep in eps if ep.name in CONSOLE_SCRIPTS}


def test_console_entry_points_registered_and_loadable() -> None:
    try:
        metadata.distribution("kimeco")
    except metadata.PackageNotFoundError:
        if _is_ci():
            raise
        pytest.skip("kimeco is not installed in this interpreter")
    eps = _console_entry_points()
    assert set(eps) == set(CONSOLE_SCRIPTS), (
        f"console scripts registered: {set(eps)}")
    for name, ep in eps.items():
        assert ep.value == CONSOLE_SCRIPTS[name]
        assert callable(ep.load()), f"{name} entry point is not callable"


def test_console_script_help_exits_zero(fresh_runs) -> None:
    failures: list[str] = []
    for script in ("kmo", "kmo_start"):
        result = fresh_runs[f"help_{script}"]
        if result.returncode != 0:
            failures.append(f"{script} --help exited {result.returncode}:\n"
                            f"{result.stderr[-2000:]}")
        elif "usage" not in (result.stdout + result.stderr).lower():
            failures.append(f"{script} --help printed no usage")
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Standard + edge cases: the agentic pipeline is gone for good
# ---------------------------------------------------------------------------
def test_agentic_pipeline_folder_absent() -> None:
    assert not (REPO / "agentic_pipeline").exists()
    assert not (REPO / "tests" / "unit" / "test_agentic_pipeline_ci.py").exists()


def test_agentic_pipeline_not_importable(fresh_runs) -> None:
    assert find_spec("agentic_pipeline") is None
    assert fresh_runs["import_agentic"].returncode != 0


def _python_sources() -> list[Path]:
    files: list[Path] = []
    for root in (PACKAGE_DIR, REPO / "tests"):
        files.extend(p for p in root.rglob("*.py")
                     if "__pycache__" not in p.parts)
    return files


def test_no_source_references_agentic_pipeline_or_anthropic() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        if path.resolve() == Path(__file__).resolve():
            continue  # this file names the patterns on purpose
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in FORBIDDEN_SOURCE_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(REPO)}: {pattern.pattern}")
    assert not offenders, "\n".join(offenders)


def test_installed_top_level_excludes_agentic_pipeline() -> None:
    """The installed distribution must not export ``agentic_pipeline`` as a
    top-level package. Strict in CI; locally a missing/stale install skips."""
    try:
        dist = metadata.distribution("kimeco")
    except metadata.PackageNotFoundError:
        if _is_ci():
            raise
        pytest.skip("kimeco is not installed in this interpreter")
    top_level = dist.read_text("top_level.txt")
    if top_level is None:
        if _is_ci():
            raise AssertionError("installed kimeco has no top_level.txt")
        pytest.skip("stale egg-info: no top_level.txt")
    names = {ln.strip() for ln in top_level.splitlines() if ln.strip()}
    assert "kimeco" in names
    assert "agentic_pipeline" not in names


# ---------------------------------------------------------------------------
# Opt-in: real editable install in a fresh venv (documented procedure)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.environ.get("KIMECO_RUN_INSTALL_TEST") != "1",
    reason="set KIMECO_RUN_INSTALL_TEST=1 to run the editable-install test")
def test_editable_install_in_fresh_venv(tmp_path: Path) -> None:
    """Follow the documented ``pip install -e .`` procedure in a throw-away
    venv and verify the resulting installation.

    ``--system-site-packages`` reuses the runtime dependencies already present
    in the calling interpreter (so no network access is needed); the install
    itself uses ``--no-deps`` for the same reason. What is exercised is the
    build/metadata/entry-point side of the install, not dependency resolution.
    """
    venv_dir = tmp_path / "venv"
    # symlinks=True mirrors the ``python -m venv`` CLI default on POSIX (the
    # EnvBuilder API defaults to copying the interpreter, which breaks the
    # interpreter's $ORIGIN-relative RPATH on relocated/conda pythons).
    venv.EnvBuilder(system_site_packages=True, with_pip=True, clear=True,
                    symlinks=(os.name != "nt")).create(venv_dir)
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    py = str(bin_dir / "python")

    install = subprocess.run(
        [py, "-m", "pip", "install", "--no-build-isolation", "--no-deps",
         "-e", str(REPO)],
        capture_output=True, text=True, timeout=600, cwd=str(REPO))
    assert install.returncode == 0, install.stderr[-3000:]

    # Imports resolve to the repo checkout (editable) and the GUI imports.
    probe = _run_python(
        "import kimeco, kimeco.gui.kimecoapp, pathlib\n"
        "print(pathlib.Path(kimeco.__file__).resolve())",
        python=py)
    assert probe.returncode == 0, probe.stderr[-2000:]
    assert Path(probe.stdout.strip()).resolve() == (
        PACKAGE_DIR / "__init__.py").resolve()

    # All four console scripts were generated and two of them answer --help.
    for name in CONSOLE_SCRIPTS:
        assert (bin_dir / name).exists(), f"{name} script missing in venv"
    for name in ("kmo", "kmo_start"):
        result = subprocess.run([str(bin_dir / name), "--help"],
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, (
            f"{name} --help exited {result.returncode}:\n{result.stderr[-2000:]}")

    # Installed metadata reflects pyproject (extras + python floor).
    meta_probe = _run_python(
        "from importlib import metadata\n"
        "d = metadata.distribution('kimeco')\n"
        "print(sorted(d.metadata.get_all('Provides-Extra') or []))\n"
        "print(d.metadata.get('Requires-Python'))\n",
        python=py)
    assert meta_probe.returncode == 0, meta_probe.stderr[-2000:]
    extras_line, requires_line = meta_probe.stdout.strip().splitlines()[-2:]
    assert extras_line == "['automech', 'test']"
    assert requires_line == ">=3.11"
