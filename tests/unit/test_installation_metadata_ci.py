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
* README, MANUAL and wiki all carry the same fresh-environment automech
  recipe (conda env, ``mess-static`` from the auto-mech channel, git+
  pre-install of autoio/autochem, ``[automech]``, verification import),
  MANUAL/wiki mention ``[automech,test]``, and the git+ refs match the ones
  the CI ``test-automech-extra`` job installs;
* README, MANUAL and wiki document the MESS binary route
  (``conda install -c auto-mech mess-static -y`` + a ``which mess`` check
  that must resolve inside the active environment), MANUAL and wiki keep
  their MESS section identical, and the fresh-env lead sentence says the
  recipe replaces the MESS step too;
* ``.github/workflows/tests.yml`` has a job installing ``[automech,test]``
  with ``KIMECO_REQUIRE_EXTRAS`` set, a ``test-mess-binary`` job installing
  ``mess-static`` with ``KIMECO_REQUIRE_MESS`` set, and
  ``hooks/run_tests.sh`` looks for the documented ``kimeco`` / ``kmo`` conda
  envs;
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
RUN_TESTS_SH = REPO / "hooks" / "run_tests.sh"

EXPECTED_EXTRAS = {"test", "automech"}
EXPECTED_PYTHON_FLOOR = ">=3.11"
EXPECTED_AUTOMECH = [
    "autoio>=0.2026.0",
    "autochem>=0.2025.0,<2.0.0",
    "ipython>=8.0",
    "mako>=1.3.10",
    "more-itertools>=10.8.0",
    "networkx>=3.3",
    "pint>=0.25",
    "py3dmol>=2.0",
    "pyparsing>=3.2.5",
    "pyyaml>=6.0.3",
    "qcelemental>=0.29.0",
    "rdkit>=2025.9.1",
    "scipy>=1.12",
    "xarray>=2023.8",
]
FORBIDDEN_TOKENS = ("anthropic", "pydantic", "agentic")

# Fresh-environment automech recipe that README, MANUAL and the wiki must all
# carry in a single fenced block (one regex per line, matched in order).
# The `conda create` line tolerates extra packages (e.g. `pip`) before `-y`.
# Line index 2 is the MESS binary (mess-static from the auto-mech channel).
GIT_PREINSTALL_RE = (
    r'pip install "autoio @ git\+https://github\.com/Auto-Mech/autoio@[^"]+" '
    r'"autochem @ git\+https://github\.com/Auto-Mech/autochem@[^"]+"')
MESS_STATIC_INSTALL = "conda install -c auto-mech mess-static -y"
MESS_STATIC_INSTALL_RE = re.escape(MESS_STATIC_INSTALL)
FRESH_ENV_RECIPE_RES = (
    r"conda create -n kimeco -c conda-forge python=3\.11(?: \S+)* -y",
    r"conda activate kimeco",
    MESS_STATIC_INSTALL_RE,
    GIT_PREINSTALL_RE,
    r"pip install -e \.\[automech\]",
    r'python -c "import mess_io, phydat, kimeco"',
)
REQUIRE_EXTRAS_ENV = "KIMECO_REQUIRE_EXTRAS"
REQUIRE_MESS_ENV = "KIMECO_REQUIRE_MESS"
WHICH_MESS = "which mess"
MESS_SECTION_TITLE = "5) MESS dependency (required)"


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


def _fenced_block_list(path: Path) -> list[str]:
    """Return the body of every fenced code block, in document order."""
    text = path.read_text(encoding="utf-8")
    return re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL)


def _block_matches_recipe(block: str) -> bool:
    lines = [ln.rstrip() for ln in block.strip("\n").splitlines()]
    if len(lines) != len(FRESH_ENV_RECIPE_RES):
        return False
    return all(re.fullmatch(pattern, line)
               for pattern, line in zip(FRESH_ENV_RECIPE_RES, lines))


def _fresh_env_recipe_blocks(path: Path) -> list[str]:
    return [b for b in _fenced_block_list(path) if _block_matches_recipe(b)]


def _recipe_with_lead_sentence(path: Path) -> str:
    """The fresh-env fenced block plus the prose line right before it."""
    text = path.read_text(encoding="utf-8")
    for match in re.finditer(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL):
        if _block_matches_recipe(match.group(1)):
            before = text[:match.start()].rstrip("\n").splitlines()
            lead = before[-1] if before else ""
            return lead + "\n" + match.group(1)
    raise AssertionError(f"{path.name}: fresh-env recipe block not found")


def _collect(failures: list[str], label: str, check, *args) -> None:
    """Run ``check(*args)``; record its AssertionError under ``label`` so a
    loop over cases reports every failing case, not only the first."""
    try:
        check(*args)
    except AssertionError as exc:
        failures.append(f"{label}: {exc}")


def _git_pins(text: str) -> dict[str, set[str]]:
    """Map autoio/autochem -> set of git refs pinned via git+...Auto-Mech/."""
    out: dict[str, set[str]] = {"autoio": set(), "autochem": set()}
    for name, ref in re.findall(
            r"git\+https://github\.com/Auto-Mech/(autoio|autochem)@([^\s\"']+)",
            text):
        out[name].add(ref)
    return out


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
    for label, reqs in (("EXPECTED_AUTOMECH", EXPECTED_AUTOMECH),
                        ("pyproject automech", extras["automech"])):
        names = [canonicalize_name(Requirement(r).name) for r in reqs]
        assert len(names) == len(set(names)), f"duplicates in {label}: {names}"


def test_setup_py_extras_mirror_pyproject() -> None:
    kwargs = _setup_kwargs()
    setup_extras = kwargs["extras_require"]
    pyproject = _pyproject()["project"]
    pyproject_extras = pyproject["optional-dependencies"]
    assert set(setup_extras) == set(pyproject_extras)
    for key in pyproject_extras:
        assert setup_extras[key] == pyproject_extras[key], (
            f"extras_require[{key!r}] in setup.py differs from pyproject")
    assert kwargs["install_requires"] == pyproject["dependencies"], (
        "install_requires in setup.py differs from pyproject dependencies")


# ---------------------------------------------------------------------------
# Standard cases: python floor everywhere
# ---------------------------------------------------------------------------
def test_python_floor_identical_in_pyproject_and_setup_py() -> None:
    """``>=3.11`` in pyproject, setup.py and the conda recipe; classifiers
    list 3.11 and 3.12 but not 3.10; conda builds for 3.11 only."""
    project = _pyproject()["project"]
    assert project["requires-python"] == EXPECTED_PYTHON_FLOOR
    assert _setup_kwargs()["python_requires"] == EXPECTED_PYTHON_FLOOR

    classifiers = project["classifiers"]
    assert "Programming Language :: Python :: 3.11" in classifiers
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Programming Language :: Python :: 3.10" not in classifiers

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
    matrices = re.findall(r"python-version:\s*\[([^\]]*)\]", tests_yml)
    assert len(matrices) >= 2, "tests.yml: expected a matrix per job"
    for raw in matrices:
        matrix = [v.strip().strip('"\'') for v in raw.split(",")]
        assert matrix == ["3.11", "3.12"], matrix

    for path in (GITLAB_CI, KMO_INSTALL_TEST):
        text = path.read_text(encoding="utf-8")
        pins = re.findall(r"python=([0-9.]+)", text)
        assert pins, f"{path.name}: no python=X.Y pin found"
        assert set(pins) == {"3.11"}, f"{path.name}: python pins {pins}"

    for path in (TESTS_YML, GITLAB_CI, KMO_INSTALL_TEST):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"python[-=: \"']*3\.10\b", text), (
            f"{path.name} still pins python 3.10")


def test_no_agentic_dependency_tokens_in_packaging_files() -> None:
    failures = [f"{path.name} still mentions {token!r}"
                for path in (PYPROJECT, SETUP_PY, REQUIREMENTS_TXT, META_YAML,
                             TESTS_YML)
                for token in FORBIDDEN_TOKENS
                if token in path.read_text(encoding="utf-8").lower()]
    assert not failures, "\n".join(failures)
    install_lines = [ln for ln in TESTS_YML.read_text(encoding="utf-8").splitlines()
                     if "pip install" in ln and "-e" in ln]
    assert install_lines, "tests.yml: no editable pip install line"
    assert any("[test]" in ln for ln in install_lines), install_lines
    assert not any("agentic" in ln for ln in install_lines), install_lines


# ---------------------------------------------------------------------------
# Standard cases: documented installation procedure
# ---------------------------------------------------------------------------
def _check_doc_install_procedure(doc: Path, declared: set[str]) -> None:
    code = _fenced_code_blocks(doc)
    for needle in ("python=3.11",
                   "mamba install -c conda-forge --file requirements.txt",
                   "pip install -e .",
                   "[automech]"):
        assert needle in code, (
            f"fenced install code is missing {needle!r}")
    assert "python=3.10" not in code, "still documents python=3.10"
    # Every ``pip install ...[extra]`` references a declared extra.
    referenced = _pip_install_extras(doc.read_text(encoding="utf-8"))
    assert referenced, "no 'pip install ...[extra]' command found"
    unknown = referenced - declared
    assert not unknown, f"references undeclared extras {unknown}"
    assert "automech" in referenced, "does not document the [automech] extra"
    if doc in (MANUAL, WIKI_INSTALL):
        assert "pip install -e .[automech,test]" in doc.read_text(encoding="utf-8"), (
            "must document 'pip install -e .[automech,test]' for developers")


def test_docs_install_procedure_pip_first() -> None:
    """Each installation document describes the supported procedure: a
    python=3.11 conda env, the requirements.txt mamba shortcut, an editable
    pip install with declared extras only, and the ``[automech]`` extra;
    MANUAL and wiki also mention ``[automech,test]``."""
    declared = set(_pyproject()["project"]["optional-dependencies"])
    failures: list[str] = []
    for doc in DOC_FILES:
        _collect(failures, str(doc.relative_to(REPO)),
                 _check_doc_install_procedure, doc, declared)
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Standard cases: fresh-environment automech recipe in the docs
# ---------------------------------------------------------------------------
def _check_fresh_env_recipe(doc: Path) -> None:
    blocks = _fresh_env_recipe_blocks(doc)
    assert len(blocks) == 1, (
        f"expected exactly one fenced block with the fresh-env recipe, "
        f"found {len(blocks)}")
    text = doc.read_text(encoding="utf-8")
    after = text[text.index(blocks[0]) + len(blocks[0]):]
    assert re.search(r"Run `which mess` afterwards", after), (
        "no `which mess` follow-up after the recipe")
    if doc in (MANUAL, WIKI_INSTALL):
        # The recipe includes the MESS step: the lead sentence says it
        # replaces steps 2 (install) AND 5 (MESS), and names MESS.
        lead = _recipe_with_lead_sentence(doc).splitlines()[0]
        assert "replaces steps 2 and 5" in lead, lead
        assert "install MESS" in lead, lead
        assert "steps 2 and 6" not in lead and "step 2 above" not in lead, lead


def test_docs_fresh_env_recipe_in_one_fenced_block() -> None:
    """Each installation document carries the complete fresh-env automech
    sequence (create env, activate, mess-static from auto-mech, git+
    pre-install of autoio/autochem, editable install with [automech],
    verification import) as ONE fenced block, in that order, followed by a
    ``which mess`` hint. MANUAL and wiki keep block and lead sentence
    line-identical."""
    failures: list[str] = []
    for doc in DOC_FILES:
        _collect(failures, str(doc.relative_to(REPO)),
                 _check_fresh_env_recipe, doc)
    assert not failures, "\n".join(failures)
    assert (_recipe_with_lead_sentence(MANUAL)
            == _recipe_with_lead_sentence(WIKI_INSTALL))


def _check_preinstall(doc: Path) -> None:
    code = _fenced_code_blocks(doc)
    pins = _git_pins(code)
    conda_channel = re.search(r"conda install .*autoio .*autochem .*-c auto-mech",
                              code) is not None
    assert (pins["autoio"] and pins["autochem"]) or conda_channel, (
        "no git+…Auto-Mech/ or -c auto-mech pre-install of autoio/autochem")
    recipe_pins = _git_pins(_fresh_env_recipe_blocks(doc)[0])
    assert recipe_pins["autoio"] and recipe_pins["autochem"], (
        "the fresh-env block does not use the git+ form")


def test_docs_preinstall_autoio_autochem_from_auto_mech() -> None:
    """autoio/autochem are not on PyPI: the automech instructions must
    pre-install them from GitHub (git+.../Auto-Mech/) and/or the auto-mech
    conda channel, and the fresh-env block must use the git+ form."""
    failures: list[str] = []
    for doc in DOC_FILES:
        _collect(failures, str(doc.relative_to(REPO)), _check_preinstall, doc)
    assert not failures, "\n".join(failures)


def test_docs_and_ci_pin_same_autoio_autochem_refs() -> None:
    """Every git+ pin of autoio/autochem (docs and tests.yml) uses the same
    ref, so CI exercises exactly what the docs tell users to install."""
    refs = {"autoio": set(), "autochem": set()}
    for path in (*DOC_FILES, TESTS_YML):
        for name, found in _git_pins(path.read_text(encoding="utf-8")).items():
            refs[name] |= found
    for name, found in refs.items():
        assert len(found) == 1, f"{name} pinned to several refs: {found}"


# ---------------------------------------------------------------------------
# Standard cases: MESS binary route documented (mess-static + which mess)
# ---------------------------------------------------------------------------
def _markdown_section(path: Path, title: str) -> tuple[int, str]:
    """Return (heading level, body) of the ``#..# <title>`` section, where
    the body runs until the next heading of the same or a higher level."""
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^(#+) {re.escape(title)}\s*$", text, flags=re.M)
    assert match, f"{path.name}: section {title!r} not found"
    level = len(match.group(1))
    rest = text[match.end():]
    nxt = re.search(rf"^#{{1,{level}}} ", rest, flags=re.M)
    body = rest[:nxt.start()] if nxt else rest
    return level, body.strip("\n")


def _check_mess_static_doc(doc: Path) -> None:
    blocks = [b.strip("\n") for b in _fenced_block_list(doc)]
    fenced_lines = [ln.rstrip() for b in blocks for ln in b.splitlines()]
    assert fenced_lines.count(MESS_STATIC_INSTALL) >= 1, (
        f"fenced code lacks {MESS_STATIC_INSTALL!r}")
    assert MESS_STATIC_INSTALL in blocks, (
        f"no fenced block consisting only of {MESS_STATIC_INSTALL!r} "
        "(the standalone MESS step)")
    assert blocks.count(WHICH_MESS) == 1, (
        f"expected exactly one fenced block whose body is exactly "
        f"{WHICH_MESS!r}; got {blocks.count(WHICH_MESS)}")
    text = doc.read_text(encoding="utf-8")
    assert "inside the active environment" in text, (
        "must state that `which mess` prints a path inside the active "
        "environment")
    which_idx = text.index("```bash\n" + WHICH_MESS + "\n```")
    assert "inside the active environment" in text[which_idx:], (
        "the 'inside the active environment' sentence must follow the "
        "`which mess` block")
    # No competing MESS install command (pip / other channel) in fenced code.
    for line in fenced_lines:
        if "mess-static" in line:
            assert line == MESS_STATIC_INSTALL, line


def test_docs_document_mess_static_install_and_which_check() -> None:
    """Every installation document shows the exact mess-static install line
    as a fenced command, a fenced block whose body is exactly ``which mess``,
    and says the path must be inside the active environment. MANUAL and wiki
    keep their MESS section body identical (### in MANUAL, ## in the wiki)."""
    failures: list[str] = []
    for doc in DOC_FILES:
        _collect(failures, str(doc.relative_to(REPO)), _check_mess_static_doc, doc)
    assert not failures, "\n".join(failures)
    manual_level, manual_body = _markdown_section(MANUAL, MESS_SECTION_TITLE)
    wiki_level, wiki_body = _markdown_section(WIKI_INSTALL, MESS_SECTION_TITLE)
    assert manual_level == 3 and wiki_level == 2, (manual_level, wiki_level)
    assert manual_body == wiki_body
    for needle in (MESS_STATIC_INSTALL, WHICH_MESS, "$CONDA_PREFIX/bin",
                   "inside the active environment"):
        assert needle in manual_body, f"MESS section lacks {needle!r}"


def test_tests_yml_has_mess_binary_job() -> None:
    """CI proves the documented MESS route: a ``test-mess-binary`` job
    creates a micromamba env from conda-forge + auto-mech with mess-static,
    installs ``[automech,test]``, checks ``which mess`` is the env binary
    and runs tests/unit with KIMECO_REQUIRE_MESS=1 (skips become failures)."""
    tests_yml = TESTS_YML.read_text(encoding="utf-8")
    job = re.search(r"^  test-mess-binary:\s*$(.*?)(?=^  \S|\Z)", tests_yml,
                    flags=re.M | re.S)
    assert job, "tests.yml: missing 'test-mess-binary' job"
    body = job.group(1)
    assert re.search(rf"{REQUIRE_MESS_ENV}:\s*[\"']?1[\"']?\s*$", body, flags=re.M), (
        f"test-mess-binary must set {REQUIRE_MESS_ENV}=1")
    assert re.search(rf"{REQUIRE_EXTRAS_ENV}:\s*automech,test\s*$", body,
                     flags=re.M), body
    assert "mamba-org/setup-micromamba@v2" in body
    assert re.search(r"^\s+shell: bash -el \{0\}\s*$", body, flags=re.M), (
        "micromamba activation needs a login shell (bash -el {0})")
    assert re.search(r"python=\$\{\{ matrix\.python-version \}\}", body)
    assert "mess-static" in body and "- auto-mech" in body and "- conda-forge" in body
    assert "cache-environment: true" in body
    assert "pip install -e .[automech,test]" in body
    assert re.search(r"^\s+which mess\s*$", body, flags=re.M), (
        "the job must run the documented `which mess` check")
    assert 'test "$(which mess)" = "${CONDA_PREFIX}/bin/mess"' in body
    assert re.search(r"pytest tests/unit/ -v", body)
    # Ordering: env creation -> pip installs -> which mess -> pytest.
    idx = [body.index(x) for x in ("setup-micromamba", "git+https://github.com/Auto-Mech/autoio@",
                                   "pip install -e .[automech,test]", "which mess",
                                   "pytest tests/unit/")]
    assert idx == sorted(idx), "test-mess-binary steps are out of order"
    # Same autoio/autochem refs as the automech job (checked globally too).
    pins = _git_pins(body)
    assert pins["autoio"] and pins["autochem"]
    # This job installs MESS but must never run a real MESS input.
    assert not re.search(r"^\s+run:.*\bmess\s+\S+\.inp", body, flags=re.M)
    header = tests_yml[:tests_yml.index("jobs:")]
    assert "test-mess-binary" in header and "never" in header, (
        "header comment must explain the MESS job never runs a MESS input")

    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(tests_yml)
    mess_job = parsed["jobs"]["test-mess-binary"]
    assert mess_job["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    assert str(mess_job["env"][REQUIRE_MESS_ENV]) == "1"
    assert mess_job["env"][REQUIRE_EXTRAS_ENV] == "automech,test"
    assert mess_job["defaults"]["run"]["shell"] == "bash -el {0}"
    steps = mess_job["steps"]
    mm = next(s for s in steps if s.get("uses", "").startswith("mamba-org/setup-micromamba@v2"))
    assert mm["with"]["environment-name"] == "kimeco"
    assert mm["with"]["cache-environment"] is True
    create_args = mm["with"]["create-args"].split()
    assert "pip" in create_args and "mess-static" in create_args
    assert set(parsed["jobs"]) == {"test", "test-automech-extra", "test-mess-binary"}


# ---------------------------------------------------------------------------
# Standard cases: CI proves the automech extra installs
# ---------------------------------------------------------------------------
def test_tests_yml_has_automech_extra_job() -> None:
    tests_yml = TESTS_YML.read_text(encoding="utf-8")
    assert re.search(r"^  test-automech-extra:\s*$", tests_yml, flags=re.M), (
        "tests.yml: missing 'test-automech-extra' job")
    install_lines = [ln.strip() for ln in tests_yml.splitlines()
                     if "pip install" in ln and "-e" in ln]
    assert any(re.search(r"pip install -e \.\[automech,test\]", ln)
               for ln in install_lines), install_lines
    # KIMECO_REQUIRE_EXTRAS turns automech skips into failures in that job.
    match = re.search(rf"{REQUIRE_EXTRAS_ENV}:\s*([^\n#]+)", tests_yml)
    assert match, f"tests.yml does not set {REQUIRE_EXTRAS_ENV}"
    required = {x.strip().lower() for x in match.group(1).strip().strip('"\'').split(",")}
    assert required == {"automech", "test"}, required
    # autoio/autochem are pre-installed from GitHub before the extra.
    pins = _git_pins(tests_yml)
    assert pins["autoio"] and pins["autochem"], (
        "tests.yml: automech job must pre-install autoio/autochem via git+")
    git_idx = tests_yml.index("git+https://github.com/Auto-Mech/autoio@")
    extra_idx = tests_yml.index("pip install -e .[automech,test]")
    assert git_idx < extra_idx, "git+ pre-install must precede the extra"
    # The first job keeps proving the base install without automech.
    assert re.search(r"pip install -e \.\[test\]\s*$", tests_yml, flags=re.M), (
        "tests.yml: the base job no longer installs '.[test]' alone")


# ---------------------------------------------------------------------------
# Standard case: the git hook looks for the documented env names
# ---------------------------------------------------------------------------
def test_run_tests_hook_candidates_include_kimeco_and_kmo() -> None:
    text = RUN_TESTS_SH.read_text(encoding="utf-8")
    match = re.search(r"^CANDIDATES=\((.*)\)\s*$", text, flags=re.M)
    assert match, "hooks/run_tests.sh: CANDIDATES=(...) not found"
    tokens = match.group(1).split()
    assert "kimeco" in tokens, tokens
    assert "kmo" in tokens, tokens
    assert "game" not in tokens, tokens
    # KIMECO_HOOK_ENV (when set) must be tried before the defaults.
    assert tokens[0].startswith("${KIMECO_HOOK_ENV"), tokens


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
def test_every_requirement_is_valid_pep508() -> None:
    project = _pyproject()["project"]
    cases = [("dependencies", r) for r in project["dependencies"]]
    for key, reqs in project["optional-dependencies"].items():
        cases.extend((key, r) for r in reqs)
    failures: list[str] = []
    for group, req in cases:
        try:
            parsed = Requirement(req)
        except Exception as exc:  # InvalidRequirement
            failures.append(f"{group}: {req!r} is not PEP 508: {exc}")
            continue
        if not parsed.name:
            failures.append(f"{group}: {req!r} has no name")
        if group == "automech":
            if ">=" not in {s.operator for s in parsed.specifier}:
                failures.append(f"automech entry {req!r} lacks a >= lower bound")
    assert not failures, "\n".join(failures)


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
