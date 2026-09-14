"""CI-safe tests proving that the declared extras are actually installable
and importable, i.e. that ``pip install -e .[automech,test]`` yields an
environment where every dependency of every extra imports.

Contract exercised here
-----------------------
* Every distribution listed in ``pyproject.toml`` (``dependencies`` plus the
  ``test`` and ``automech`` extras) maps to at least one importable module.
  The distribution -> module map (:data:`DIST_TO_MODULES`) is the source of
  truth for the parametrized import test and is itself checked against
  ``pyproject.toml`` so a new requirement cannot be added silently.
* The ``automech`` gate (``KMOInput._check_automech``) passes against the
  *real* ``mess_io`` / ``phydat`` when the extra is installed.
* ``python -c "import mess_io, phydat, kimeco"`` -- the verification command
  documented in README / MANUAL / wiki -- succeeds in a fresh interpreter.
  This is the regression test for the transitive-import closure of
  ``mess_io`` (``autoio`` pulls ``IPython`` and ``py3Dmol`` at import time,
  which is why both are pinned in the ``automech`` extra).

Skip-vs-fail policy
-------------------
Base dependencies and the ``test`` extra are always required (pytest itself
is running). ``automech`` dependencies are optional: when they are missing
the corresponding cases **skip**, unless the extra is listed in the
``KIMECO_REQUIRE_EXTRAS`` environment variable (comma separated, case
insensitive), in which case a missing dependency **fails**. The
``test-automech-extra`` job in ``.github/workflows/tests.yml`` sets
``KIMECO_REQUIRE_EXTRAS=automech,test`` so CI proves the extra really
installs; a plain ``pip install -e .[test]`` developer environment only
skips.

Only the standard library, ``pytest`` and ``packaging`` (a setuptools/pip
dependency, always present) are needed to *run* this module; ``tomllib``
(3.11+) is only required by the map-vs-pyproject cross-check.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

packaging_requirements = pytest.importorskip("packaging.requirements")
packaging_utils = pytest.importorskip("packaging.utils")
Requirement = packaging_requirements.Requirement
canonicalize_name = packaging_utils.canonicalize_name

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"

REQUIRE_EXTRAS_ENV = "KIMECO_REQUIRE_EXTRAS"
BASE_GROUP = "base"
KNOWN_EXTRAS = frozenset({"test", "automech"})
ALWAYS_REQUIRED_GROUPS = frozenset({BASE_GROUP, "test"})

# Distribution name (as written in pyproject) -> importable module(s).
# Every module listed must import once the owning group is installed.
DIST_TO_MODULES: dict[str, dict[str, tuple[str, ...]]] = {
    BASE_GROUP: {
        "ase": ("ase",),
        "cantera": ("cantera",),
        "numpy": ("numpy",),
        "pandas": ("pandas",),
        "sqlalchemy": ("sqlalchemy",),
        "sqlalchemy-utils": ("sqlalchemy_utils",),
        "dash": ("dash",),
        "scipy": ("scipy",),
        "plotly": ("plotly",),
        "pint": ("pint",),
        "pyarrow": ("pyarrow",),
    },
    "test": {
        "pytest": ("pytest",),
    },
    "automech": {
        "autoio": ("mess_io", "mess_io.writer"),
        "autochem": ("phydat", "phydat.phycon", "automol"),
        "ipython": ("IPython",),
        "mako": ("mako",),
        "more-itertools": ("more_itertools",),
        "networkx": ("networkx",),
        "pint": ("pint",),
        "py3dmol": ("py3Dmol",),
        "pyparsing": ("pyparsing",),
        "pyyaml": ("yaml",),
        "qcelemental": ("qcelemental",),
        "rdkit": ("rdkit",),
        "scipy": ("scipy",),
        "xarray": ("xarray",),
    },
}

# The symbols the automech gate (KMOInput._check_automech) imports and that
# the emitted per-PES driver imports on the compute node.
GATE_WRITER_SYMBOLS = (
    "molecule", "atom", "core_rigidrotor", "core_multirotor",
    "core_phasespace", "core_rotd", "rotor_hindered", "rotor_internal",
    "well", "bimolecular", "ts_sadpt", "ts_variational",
    "global_energy_transfer_input", "global_rates_input_v1",
    "messrates_inp_str", "energy_down", "collision_frequency",
)

DOCUMENTED_VERIFY_COMMAND = "import mess_io, phydat, kimeco"


# ---------------------------------------------------------------------------
# Helpers (the KIMECO_REQUIRE_EXTRAS contract lives here)
# ---------------------------------------------------------------------------
def parse_required_extras(raw: str | None) -> frozenset[str]:
    """Parse ``KIMECO_REQUIRE_EXTRAS`` into a set of canonical extra names.

    ``None`` / empty / whitespace-only -> empty set. Names are comma
    separated, surrounding whitespace is ignored and matching is case
    insensitive. Any name that is not a declared extra raises ``ValueError``
    so a typo in CI cannot silently downgrade a failure into a skip.
    """
    if raw is None:
        return frozenset()
    names = {tok.strip().lower() for tok in raw.split(",") if tok.strip()}
    unknown = names - KNOWN_EXTRAS
    if unknown:
        raise ValueError(
            f"{REQUIRE_EXTRAS_ENV}={raw!r} names unknown extras "
            f"{sorted(unknown)}; declared extras are {sorted(KNOWN_EXTRAS)}")
    return frozenset(names)


def required_extras() -> frozenset[str]:
    return parse_required_extras(os.environ.get(REQUIRE_EXTRAS_ENV))


def group_is_required(group: str) -> bool:
    """Base deps and the ``test`` extra are always required; other extras
    only when listed in ``KIMECO_REQUIRE_EXTRAS``."""
    return group in ALWAYS_REQUIRED_GROUPS or group in required_extras()


def import_or_skip(group: str, module: str) -> Any:
    """Import ``module``; on ImportError fail if ``group`` is required,
    otherwise skip with an actionable message."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        hint = (f"install it with 'pip install -e .[{group}]'"
                if group != BASE_GROUP else "install it with 'pip install -e .'")
        message = (f"cannot import {module!r} ({group} group): {exc}; {hint}")
        if group_is_required(group):
            pytest.fail(message)
        pytest.skip(message)


def _pyproject_groups() -> dict[str, list[str]]:
    tomllib = pytest.importorskip("tomllib")
    with PYPROJECT.open("rb") as fh:
        project = tomllib.load(fh)["project"]
    groups = {BASE_GROUP: list(project["dependencies"])}
    groups.update({k: list(v)
                   for k, v in project["optional-dependencies"].items()})
    return groups


def _import_cases() -> list[tuple[str, str, str]]:
    return [(group, dist, module)
            for group, dists in DIST_TO_MODULES.items()
            for dist, modules in dists.items()
            for module in modules]


# ---------------------------------------------------------------------------
# Standard cases: every declared dependency imports
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("group,dist,module", _import_cases(),
                         ids=lambda x: x)
def test_declared_dependency_imports(group: str, dist: str,
                                     module: str) -> None:
    mod = import_or_skip(group, module)
    assert mod is not None
    assert sys.modules[module] is mod


def test_dist_to_module_map_covers_pyproject_exactly() -> None:
    """The map must list exactly the distributions declared in pyproject,
    group by group, so adding/removing a requirement forces a map update
    (and hence an import test)."""
    groups = _pyproject_groups()
    assert set(groups) == set(DIST_TO_MODULES), (
        f"pyproject groups {sorted(groups)} vs map groups "
        f"{sorted(DIST_TO_MODULES)}")
    for group, reqs in groups.items():
        declared = {canonicalize_name(Requirement(r).name) for r in reqs}
        mapped = {canonicalize_name(d) for d in DIST_TO_MODULES[group]}
        assert declared == mapped, (
            f"group {group!r}: pyproject declares {sorted(declared)} but "
            f"DIST_TO_MODULES maps {sorted(mapped)}")


def test_known_extras_match_pyproject() -> None:
    groups = _pyproject_groups()
    assert set(groups) - {BASE_GROUP} == set(KNOWN_EXTRAS)


def test_every_mapped_module_name_is_importable_dotted_path() -> None:
    for _group, dist, module in _import_cases():
        assert module and all(part.isidentifier()
                              for part in module.split(".")), (
            f"{dist}: {module!r} is not a valid dotted module path")


# ---------------------------------------------------------------------------
# Standard cases: the automech gate against the real packages
# ---------------------------------------------------------------------------
def test_automech_gate_symbols_importable() -> None:
    writer = import_or_skip("automech", "mess_io.writer")
    mess_io = import_or_skip("automech", "mess_io")
    import_or_skip("automech", "phydat.phycon")
    missing = [s for s in GATE_WRITER_SYMBOLS if not hasattr(writer, s)]
    assert not missing, f"mess_io.writer lacks gate symbols {missing}"
    assert callable(getattr(mess_io, "well_lumped_input_file", None))


def test_check_automech_passes_with_real_extra_installed() -> None:
    """With the extra installed the gate must neither warn nor cancel."""
    import_or_skip("automech", "mess_io.writer")
    import_or_skip("automech", "phydat.phycon")
    from kimeco.user_input import KMOInput

    warnings: list[str] = []
    obj = KMOInput.__new__(KMOInput)
    obj.klog = type("Log", (), {"warning": lambda self, m: warnings.append(str(m))})()
    obj.cancel_run = False

    obj._check_automech()

    assert obj.cancel_run is False
    assert warnings == []


def test_gate_symbol_list_matches_user_input_source() -> None:
    """Keep GATE_WRITER_SYMBOLS in sync with the names imported in
    ``KMOInput._check_automech`` (parsed with ast, never executed)."""
    import ast

    src = (REPO / "kimeco" / "user_input.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "_check_automech"):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.ImportFrom)
                        and sub.module == "mess_io.writer"):
                    imported.update(a.name for a in sub.names)
    assert imported == set(GATE_WRITER_SYMBOLS)


# ---------------------------------------------------------------------------
# Regression: mess_io transitive-import closure in a fresh interpreter
# ---------------------------------------------------------------------------
def test_documented_verify_command_succeeds_in_fresh_interpreter() -> None:
    """``python -c "import mess_io, phydat, kimeco"`` is the verification
    command documented in README/MANUAL/wiki. Run it in a clean subprocess so
    an ``IPython`` / ``py3Dmol`` pulled in transitively by ``mess_io`` cannot
    be masked by modules already in this process' ``sys.modules``."""
    import_or_skip("automech", "mess_io")
    proc = subprocess.run(
        [sys.executable, "-c", DOCUMENTED_VERIFY_COMMAND],
        capture_output=True, text=True, timeout=300, cwd=str(REPO))
    assert proc.returncode == 0, (
        f"documented verification command failed:\n{proc.stderr[-2000:]}")


@pytest.mark.parametrize("module", ["IPython", "py3Dmol"])
def test_mess_io_transitive_dependencies_are_declared(module: str) -> None:
    """Both packages are imported transitively by ``autoio``; they must be
    part of the automech extra (regression for the ModuleNotFoundError seen
    after ``pip install -e .[automech]`` without them)."""
    automech_modules = {m for mods in DIST_TO_MODULES["automech"].values()
                        for m in mods}
    assert module in automech_modules
    import_or_skip("automech", module)


# ---------------------------------------------------------------------------
# Edge cases: KIMECO_REQUIRE_EXTRAS parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", [None, "", "   ", ",", " , "])
def test_parse_required_extras_empty(raw: str | None) -> None:
    assert parse_required_extras(raw) == frozenset()


@pytest.mark.parametrize("raw,expected", [
    ("automech", {"automech"}),
    ("test", {"test"}),
    ("automech,test", {"automech", "test"}),
    ("test,automech", {"automech", "test"}),
    (" automech , test ", {"automech", "test"}),
    ("AUTOMECH", {"automech"}),
    ("AutoMech,TEST", {"automech", "test"}),
    ("automech,automech", {"automech"}),
    ("automech,,test,", {"automech", "test"}),
])
def test_parse_required_extras_valid(raw: str, expected: set[str]) -> None:
    assert parse_required_extras(raw) == frozenset(expected)


@pytest.mark.parametrize("raw", ["bogus", "automech,bogus", "agentic",
                                 "automech test", "[automech]", "base"])
def test_parse_required_extras_rejects_unknown(raw: str) -> None:
    with pytest.raises(ValueError, match=REQUIRE_EXTRAS_ENV):
        parse_required_extras(raw)


def test_required_extras_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv(REQUIRE_EXTRAS_ENV, "Automech")
    assert required_extras() == frozenset({"automech"})
    monkeypatch.delenv(REQUIRE_EXTRAS_ENV)
    assert required_extras() == frozenset()


def test_base_and_test_groups_always_required(monkeypatch) -> None:
    monkeypatch.delenv(REQUIRE_EXTRAS_ENV, raising=False)
    assert group_is_required(BASE_GROUP)
    assert group_is_required("test")
    assert not group_is_required("automech")


# ---------------------------------------------------------------------------
# Edge cases: skip-vs-fail contract
# ---------------------------------------------------------------------------
_MISSING = "kimeco_definitely_missing_module_for_tests"


def test_missing_optional_dependency_skips_when_not_required(
        monkeypatch) -> None:
    monkeypatch.delenv(REQUIRE_EXTRAS_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception) as info:
        import_or_skip("automech", _MISSING)
    assert "[automech]" in str(info.value)


def test_missing_optional_dependency_fails_when_required(monkeypatch) -> None:
    monkeypatch.setenv(REQUIRE_EXTRAS_ENV, "automech")
    with pytest.raises(pytest.fail.Exception) as info:
        import_or_skip("automech", _MISSING)
    assert _MISSING in str(info.value)


def test_missing_optional_dependency_fails_when_required_case_insensitive(
        monkeypatch) -> None:
    monkeypatch.setenv(REQUIRE_EXTRAS_ENV, "AUTOMECH , Test")
    with pytest.raises(pytest.fail.Exception):
        import_or_skip("automech", _MISSING)


def test_requiring_other_extra_does_not_require_automech(monkeypatch) -> None:
    monkeypatch.setenv(REQUIRE_EXTRAS_ENV, "test")
    with pytest.raises(pytest.skip.Exception):
        import_or_skip("automech", _MISSING)


@pytest.mark.parametrize("group", [BASE_GROUP, "test"])
def test_missing_base_or_test_dependency_always_fails(group: str,
                                                      monkeypatch) -> None:
    monkeypatch.delenv(REQUIRE_EXTRAS_ENV, raising=False)
    with pytest.raises(pytest.fail.Exception):
        import_or_skip(group, _MISSING)


def test_present_module_is_returned_regardless_of_policy(monkeypatch) -> None:
    monkeypatch.delenv(REQUIRE_EXTRAS_ENV, raising=False)
    assert import_or_skip("automech", "json") is importlib.import_module("json")
    monkeypatch.setenv(REQUIRE_EXTRAS_ENV, "automech")
    assert import_or_skip("automech", "json") is importlib.import_module("json")


def test_invalid_require_extras_env_is_an_error_not_a_skip(monkeypatch) -> None:
    monkeypatch.setenv(REQUIRE_EXTRAS_ENV, "autmech")  # typo
    with pytest.raises(ValueError):
        import_or_skip("automech", _MISSING)
