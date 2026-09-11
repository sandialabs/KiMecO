"""CI-safe tests for the packaging / installation metadata.

These tests pin the installation contract introduced when the agentic
pipeline was removed from the package:

* the only optional-dependency extras are ``test`` and ``automech``;
* ``pip install kimeco[automech]`` pulls the exact automech dependency set;
* ``setup.py`` mirrors ``pyproject.toml`` (extras, dependencies, python floor);
* the minimum Python version is ``>=3.11`` everywhere (pyproject, setup.py,
  conda recipe, CI matrices, install scripts, documentation);
* no agentic / anthropic / pydantic dependency remains in any packaging file;
* the documented installation procedure (README, MANUAL, wiki) matches the
  declared extras and python floor;
* the ``use_automech`` guard points users to ``kimeco[automech]``.

Only the standard library plus ``packaging`` (a setuptools/pip dependency,
always present in CI) is used. ``setup.py`` is parsed with ``ast`` and never
executed. ``pyproject.toml`` is read with ``tomllib``, hence the module-level
skip below 3.11 -- which is also the package floor, so nothing is lost.
"""
from __future__ import annotations

import ast
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

if sys.version_info < (3, 11):  # pragma: no cover - floor is 3.11
    pytest.skip("kimeco requires Python >= 3.11 (tomllib)",
                allow_module_level=True)

import tomllib  # noqa: E402

packaging_requirements = pytest.importorskip("packaging.requirements")
packaging_utils = pytest.importorskip("packaging.utils")
Requirement = packaging_requirements.Requirement
canonicalize_name = packaging_utils.canonicalize_name

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "pyproject.toml"
SETUP_PY = REPO / "setup.py"
REQUIREMENTS_TXT = REPO / "requirements.txt"
META_YAML = REPO / "meta.yaml"
CONDA_BUILD_CONFIG = REPO / "conda_build_config.yaml"
TESTS_YML = REPO / ".github" / "workflows" / "tests.yml"
GITLAB_CI = REPO / ".gitlab-ci.yml"
KMO_INSTALL_TEST = REPO / "kmo_install_test.sh"
README = REPO / "README.md"
MANUAL = REPO / "MANUAL.md"
WIKI_INSTALL = REPO / "wiki" / "Installation-from-Source.md"
DOC_FILES = (README, MANUAL, WIKI_INSTALL)

EXPECTED_EXTRAS = {"test", "automech"}
EXPECTED_PYTHON_FLOOR = ">=3.11"
EXPECTED_AUTOMECH = [
    "autoio>=0.2026.0",
    "autochem>=0.2025.0,<2.0.0",
    "mako>=1.3.10",
    "more-itertools>=10.8.0",
    "networkx>=3.3",
    "pint>=0.25",
    "pyparsing>=3.2.5",
    "pyyaml>=6.0.3",
    "qcelemental>=0.29.0",
    "rdkit>=2025.9.1",
    "scipy>=1.12",
    "xarray>=2023.8",
]
FORBIDDEN_TOKENS = ("anthropic", "pydantic", "agentic")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pyproject() -> dict[str, Any]:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _setup_kwargs() -> dict[str, Any]:
    """Return the keyword arguments of the ``setup(...)`` call in setup.py.

    The file is parsed with ``ast`` and literal-evaluated, so it is never
    executed and no setuptools side effect can occur.
    """
    tree = ast.parse(SETUP_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setup"):
            kwargs: dict[str, Any] = {}
            for kw in node.keywords:
                try:
                    kwargs[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    # e.g. packages=find_packages() -- not a literal.
                    kwargs[kw.arg] = None
            return kwargs
    raise AssertionError("no setup(...) call found in setup.py")


def _fenced_code_blocks(path: Path) -> str:
    """Concatenate the contents of all fenced code blocks in a markdown file."""
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL)
    assert blocks, f"{path.name}: no fenced code blocks found"
    return "\n".join(blocks)


def _pip_install_extras(text: str) -> set[str]:
    """Extract every ``[extra]`` referenced in ``pip install ...`` commands."""
    found: set[str] = set()
    for line in text.splitlines():
        if "pip install" not in line:
            continue
        for match in re.finditer(r"(?:kimeco|\.)\[([A-Za-z0-9_,\-]+)\]", line):
            found.update(x.strip() for x in match.group(1).split(","))
    return found


def _is_ci() -> bool:
    import os
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


# ---------------------------------------------------------------------------
# Standard cases: extras and dependency contract
# ---------------------------------------------------------------------------
def test_pyproject_extras_are_exactly_test_and_automech() -> None:
    extras = _pyproject()["project"]["optional-dependencies"]
    assert set(extras) == EXPECTED_EXTRAS, (
        f"optional-dependencies keys must be exactly {EXPECTED_EXTRAS}; "
        f"got {set(extras)} (no 'agentic' extra may remain)")


def test_pyproject_automech_extra_exact_list() -> None:
    extras = _pyproject()["project"]["optional-dependencies"]
    assert extras["automech"] == EXPECTED_AUTOMECH


def test_setup_py_extras_mirror_pyproject() -> None:
    setup_extras = _setup_kwargs()["extras_require"]
    pyproject_extras = _pyproject()["project"]["optional-dependencies"]
    assert set(setup_extras) == set(pyproject_extras)
    for key in pyproject_extras:
        assert setup_extras[key] == pyproject_extras[key], (
            f"extras_require[{key!r}] in setup.py differs from pyproject")


def test_setup_py_install_requires_mirrors_pyproject_dependencies() -> None:
    assert (_setup_kwargs()["install_requires"]
            == _pyproject()["project"]["dependencies"])


# ---------------------------------------------------------------------------
# Standard cases: python floor everywhere
# ---------------------------------------------------------------------------
def test_python_floor_identical_in_pyproject_and_setup_py() -> None:
    assert _pyproject()["project"]["requires-python"] == EXPECTED_PYTHON_FLOOR
    assert _setup_kwargs()["python_requires"] == EXPECTED_PYTHON_FLOOR


def test_pyproject_classifiers_list_311_and_312_not_310() -> None:
    classifiers = _pyproject()["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.11" in classifiers
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Programming Language :: Python :: 3.10" not in classifiers


def test_conda_recipe_python_floor_is_311() -> None:
    meta = META_YAML.read_text(encoding="utf-8")
    python_pins = re.findall(r"^\s*-\s*python\s*([^\n#]*)", meta, flags=re.M)
    assert len(python_pins) == 2, (
        f"meta.yaml should pin python once in host and once in run; "
        f"got {python_pins}")
    for pin in python_pins:
        assert pin.strip() == ">=3.11", f"meta.yaml python pin {pin!r}"

    config = CONDA_BUILD_CONFIG.read_text(encoding="utf-8")
    versions = re.findall(r"^\s*-\s*([0-9.]+)\s*$", config, flags=re.M)
    assert versions == ["3.11"], (
        f"conda_build_config.yaml must build for 3.11 only; got {versions}")


def test_ci_python_versions_consistent() -> None:
    tests_yml = TESTS_YML.read_text(encoding="utf-8")
    match = re.search(r"python-version:\s*\[([^\]]*)\]", tests_yml)
    assert match, "tests.yml: python-version matrix not found"
    matrix = [v.strip().strip('"\'') for v in match.group(1).split(",")]
    assert matrix == ["3.11", "3.12"]

    for path in (GITLAB_CI, KMO_INSTALL_TEST):
        text = path.read_text(encoding="utf-8")
        pins = re.findall(r"python=([0-9.]+)", text)
        assert pins, f"{path.name}: no python=X.Y pin found"
        assert set(pins) == {"3.11"}, f"{path.name}: python pins {pins}"

    for path in (TESTS_YML, GITLAB_CI, KMO_INSTALL_TEST):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"python[-=: \"']*3\.10\b", text), (
            f"{path.name} still pins python 3.10")


def test_tests_yml_installs_test_extra_without_agentic() -> None:
    tests_yml = TESTS_YML.read_text(encoding="utf-8")
    install_lines = [ln for ln in tests_yml.splitlines()
                     if "pip install" in ln and "-e" in ln]
    assert install_lines, "tests.yml: no editable pip install line"
    assert any("[test]" in ln for ln in install_lines), install_lines
    assert not any("agentic" in ln for ln in install_lines), install_lines


@pytest.mark.parametrize("path", [PYPROJECT, SETUP_PY, REQUIREMENTS_TXT,
                                  META_YAML, TESTS_YML],
                         ids=lambda p: p.name)
def test_no_agentic_dependency_tokens_in_packaging_files(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()
    for token in FORBIDDEN_TOKENS:
        assert token not in text, f"{path.name} still mentions {token!r}"


# ---------------------------------------------------------------------------
# Standard cases: documented installation procedure
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.name)
def test_docs_install_procedure_pip_first(doc: Path) -> None:
    """Each installation document must describe the supported procedure:
    a python=3.11 conda env, the requirements.txt mamba shortcut, an
    editable pip install, and the ``[automech]`` extra."""
    code = _fenced_code_blocks(doc)
    for needle in ("python=3.11",
                   "mamba install -c conda-forge --file requirements.txt",
                   "pip install -e .",
                   "[automech]"):
        assert needle in code, (
            f"{doc.relative_to(REPO)}: fenced install code is missing "
            f"{needle!r}")
    assert "python=3.10" not in code, (
        f"{doc.relative_to(REPO)}: still documents python=3.10")


@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.name)
def test_docs_extras_exist_in_pyproject(doc: Path) -> None:
    """Every ``pip install ...[extra]`` in the docs must reference a declared
    extra, and the automech extra must be documented."""
    declared = set(_pyproject()["project"]["optional-dependencies"])
    referenced = _pip_install_extras(doc.read_text(encoding="utf-8"))
    assert referenced, (
        f"{doc.relative_to(REPO)}: no 'pip install ...[extra]' command found")
    unknown = referenced - declared
    assert not unknown, (
        f"{doc.relative_to(REPO)} references undeclared extras {unknown}")
    assert "automech" in referenced, (
        f"{doc.relative_to(REPO)} does not document the [automech] extra")


# ---------------------------------------------------------------------------
# Standard case: the use_automech guard advertises the extra
# ---------------------------------------------------------------------------
class _WarningRecorder:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: Any) -> None:
        self.warnings.append(str(message))


def _stub_mess_io(monkeypatch) -> None:
    from kimeco import user_input  # noqa: F401 - ensure importable

    mess_io = types.ModuleType("mess_io")
    writer = types.ModuleType("mess_io.writer")
    for sym in ("molecule", "atom", "core_rigidrotor", "core_multirotor",
                "core_phasespace", "core_rotd", "rotor_hindered",
                "rotor_internal", "well", "bimolecular", "ts_sadpt",
                "ts_variational", "global_energy_transfer_input",
                "global_rates_input_v1", "messrates_inp_str", "energy_down",
                "collision_frequency"):
        setattr(writer, sym, lambda *a, **k: "")
    mess_io.writer = writer  # type: ignore[attr-defined]
    mess_io.well_lumped_input_file = lambda *a, **k: ""  # type: ignore
    monkeypatch.setitem(sys.modules, "mess_io", mess_io)
    monkeypatch.setitem(sys.modules, "mess_io.writer", writer)


def test_check_automech_warning_points_to_automech_extra(
        tmp_path: Path, monkeypatch) -> None:
    from kimeco.user_input import KMOInput

    _stub_mess_io(monkeypatch)
    # Block phydat so the guard fails on the autochem half of the extra.
    monkeypatch.setitem(sys.modules, "phydat", None)
    monkeypatch.delitem(sys.modules, "phydat.phycon", raising=False)

    obj = KMOInput.__new__(KMOInput)
    recorder = _WarningRecorder()
    obj.klog = recorder
    obj.cancel_run = False

    obj._check_automech()

    assert obj.cancel_run is True
    assert len(recorder.warnings) == 1
    message = recorder.warnings[0]
    assert "kimeco[automech]" in message
    assert "phydat" in message
    assert "agentic" not in message.lower()


# ---------------------------------------------------------------------------
# Edge cases: requirement hygiene
# ---------------------------------------------------------------------------
def test_automech_extra_has_no_duplicate_canonical_names() -> None:
    names = [canonicalize_name(Requirement(r).name) for r in EXPECTED_AUTOMECH]
    assert len(names) == len(set(names)), f"duplicates in automech: {names}"
    extra = _pyproject()["project"]["optional-dependencies"]["automech"]
    extra_names = [canonicalize_name(Requirement(r).name) for r in extra]
    assert len(extra_names) == len(set(extra_names))


def _all_requirement_strings() -> list[tuple[str, str]]:
    project = _pyproject()["project"]
    out = [("dependencies", r) for r in project["dependencies"]]
    for key, reqs in project["optional-dependencies"].items():
        out.extend((key, r) for r in reqs)
    return out


@pytest.mark.parametrize("group,req", _all_requirement_strings(),
                         ids=lambda x: x)
def test_every_requirement_is_valid_pep508(group: str, req: str) -> None:
    parsed = Requirement(req)  # raises InvalidRequirement on bad syntax
    assert parsed.name
    if group == "automech":
        specs = {s.operator for s in parsed.specifier}
        assert ">=" in specs, f"automech entry {req!r} lacks a >= lower bound"
        assert str(parsed.specifier), f"automech entry {req!r} has no specifier"


def test_requirements_txt_is_subset_of_dependencies_and_test_extra() -> None:
    project = _pyproject()["project"]
    allowed = {canonicalize_name(Requirement(r).name)
               for r in project["dependencies"]
               + project["optional-dependencies"]["test"]}
    lines = [ln.strip() for ln in REQUIREMENTS_TXT.read_text().splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    names = {canonicalize_name(Requirement(ln).name) for ln in lines}
    assert names <= allowed, (
        f"requirements.txt lists packages outside dependencies+test: "
        f"{names - allowed}")


def test_installed_metadata_extras_and_python_floor() -> None:
    """The installed distribution (editable or wheel) must advertise the
    same extras and python floor as pyproject. Strict in CI (fresh install);
    locally a stale egg-info only skips."""
    from importlib import metadata

    try:
        dist = metadata.distribution("kimeco")
    except metadata.PackageNotFoundError:
        if _is_ci():
            raise
        pytest.skip("kimeco is not installed in this interpreter")

    extras = set(dist.metadata.get_all("Provides-Extra") or [])
    requires_python = dist.metadata.get("Requires-Python")
    ok = extras == EXPECTED_EXTRAS and requires_python == EXPECTED_PYTHON_FLOOR
    if not ok and not _is_ci():
        pytest.skip(
            "stale egg-info: installed metadata reports extras "
            f"{extras} / Requires-Python {requires_python!r}; re-run "
            "'pip install -e .' to refresh")
    assert extras == EXPECTED_EXTRAS
    assert requires_python == EXPECTED_PYTHON_FLOOR
