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
extra.

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


def _module_path(module: str) -> Path:
    parts = module.split(".")
    pkg = REPO.joinpath(*parts)
    return pkg / "__init__.py" if pkg.is_dir() else pkg.with_suffix(".py")


def _run_python(code: str, *, env: dict[str, str] | None = None,
                python: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [python or sys.executable, "-c", code],
        capture_output=True, text=True, timeout=300,
        cwd=str(REPO), env=env)


# ---------------------------------------------------------------------------
# Standard cases: every public module imports in a fresh interpreter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("module", PUBLIC_MODULES)
def test_module_source_exists(module: str) -> None:
    assert _module_path(module).is_file(), (
        f"{module} has no source file at {_module_path(module)}")


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


def _import_all(prelude: str = "") -> subprocess.CompletedProcess:
    """Import every public module in one fresh interpreter, reporting each
    failing module with its traceback (one process keeps the suite fast)."""
    return _run_python(_IMPORT_ALL.format(prelude=prelude,
                                          modules=PUBLIC_MODULES))


def test_all_public_modules_import_in_fresh_interpreter() -> None:
    result = _import_all()
    assert result.returncode == 0, (
        f"public module import failures:\n{result.stderr[-4000:]}")


def test_all_public_modules_import_without_automech_extra() -> None:
    """The base install (no ``[automech]``) must import every public module.

    Setting ``sys.modules[name] = None`` makes any ``import name`` raise
    ImportError even where the automech packages are really installed.
    """
    block = "\n".join(f"sys.modules[{m!r}] = None" for m in AUTOMECH_MODULES)
    result = _import_all(prelude=block)
    assert result.returncode == 0, (
        "a public module requires an automech module at import time:\n"
        f"{result.stderr[-4000:]}")


def test_blocking_automech_modules_actually_blocks() -> None:
    """Sanity check of the blocking technique used above."""
    result = _run_python(
        "import sys; sys.modules['mess_io'] = None; import mess_io")
    assert result.returncode != 0
    assert "ImportError" in result.stderr or "ModuleNotFoundError" in result.stderr


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


@pytest.mark.parametrize("script", ["kmo", "kmo_start"])
def test_console_script_help_exits_zero(script: str) -> None:
    target = CONSOLE_SCRIPTS[script]
    module, func = target.split(":")
    code = (
        "import sys\n"
        f"from {module} import {func}\n"
        f"sys.argv = [{script!r}, '--help']\n"
        f"{func}()\n"
    )
    result = _run_python(code)
    assert result.returncode == 0, (
        f"{script} --help exited {result.returncode}:\n{result.stderr[-2000:]}")
    assert "usage" in (result.stdout + result.stderr).lower()


# ---------------------------------------------------------------------------
# Standard + edge cases: the agentic pipeline is gone for good
# ---------------------------------------------------------------------------
def test_agentic_pipeline_folder_absent() -> None:
    assert not (REPO / "agentic_pipeline").exists()
    assert not (REPO / "tests" / "unit" / "test_agentic_pipeline_ci.py").exists()


def test_agentic_pipeline_not_importable() -> None:
    assert find_spec("agentic_pipeline") is None
    result = _run_python("import agentic_pipeline")
    assert result.returncode != 0


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
