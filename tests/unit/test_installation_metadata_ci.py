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
MESS_RECIPE_INDEX = 2
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
# Standard cases: fresh-environment automech recipe in the docs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.name)
def test_docs_fresh_env_recipe_in_one_fenced_block(doc: Path) -> None:
    """Each installation document carries the complete fresh-env automech
    sequence (create env, activate, mess-static from auto-mech, git+
    pre-install of autoio/autochem, editable install with [automech],
    verification import) as ONE fenced block, in that order."""
    blocks = _fresh_env_recipe_blocks(doc)
    assert len(blocks) == 1, (
        f"{doc.relative_to(REPO)}: expected exactly one fenced block with "
        f"the fresh-env recipe, found {len(blocks)}")


def test_manual_and_wiki_fresh_env_recipe_identical() -> None:
    """MANUAL and wiki are maintained in lock-step: the fresh-env fenced
    block and the sentence introducing it must be line-identical."""
    assert (_recipe_with_lead_sentence(MANUAL)
            == _recipe_with_lead_sentence(WIKI_INSTALL))


@pytest.mark.parametrize("doc", (MANUAL, WIKI_INSTALL), ids=lambda p: p.name)
def test_docs_mention_combined_automech_test_extra(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    assert "pip install -e .[automech,test]" in text, (
        f"{doc.relative_to(REPO)} must document 'pip install -e "
        ".[automech,test]' for developers")


@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.name)
def test_docs_preinstall_autoio_autochem_from_auto_mech(doc: Path) -> None:
    """autoio/autochem are not on PyPI: the automech instructions must
    pre-install them from GitHub (git+.../Auto-Mech/) and/or the auto-mech
    conda channel, and the fresh-env block must use the git+ form."""
    code = _fenced_code_blocks(doc)
    pins = _git_pins(code)
    conda_channel = re.search(r"conda install .*autoio .*autochem .*-c auto-mech",
                              code) is not None
    assert (pins["autoio"] and pins["autochem"]) or conda_channel, (
        f"{doc.relative_to(REPO)}: no git+…Auto-Mech/ or -c auto-mech "
        "pre-install of autoio/autochem")
    recipe = _fresh_env_recipe_blocks(doc)[0]
    recipe_pins = _git_pins(recipe)
    assert recipe_pins["autoio"] and recipe_pins["autochem"]


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


@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.name)
def test_docs_document_mess_static_install_and_which_check(doc: Path) -> None:
    """Every installation document shows the exact mess-static install line
    as a fenced command, a fenced block whose body is exactly ``which mess``,
    and says the path must be inside the active environment."""
    blocks = [b.strip("\n") for b in _fenced_block_list(doc)]
    fenced_lines = [ln.rstrip() for b in blocks for ln in b.splitlines()]
    assert fenced_lines.count(MESS_STATIC_INSTALL) >= 1, (
        f"{doc.relative_to(REPO)}: fenced code lacks {MESS_STATIC_INSTALL!r}")
    assert MESS_STATIC_INSTALL in blocks, (
        f"{doc.relative_to(REPO)}: no fenced block consisting only of "
        f"{MESS_STATIC_INSTALL!r} (the standalone MESS step)")
    assert blocks.count(WHICH_MESS) == 1, (
        f"{doc.relative_to(REPO)}: expected exactly one fenced block whose "
        f"body is exactly {WHICH_MESS!r}; got {blocks.count(WHICH_MESS)}")
    text = doc.read_text(encoding="utf-8")
    assert "inside the active environment" in text, (
        f"{doc.relative_to(REPO)}: must state that `which mess` prints a "
        "path inside the active environment")
    which_idx = text.index("```bash\n" + WHICH_MESS + "\n```")
    assert "inside the active environment" in text[which_idx:], (
        f"{doc.relative_to(REPO)}: the 'inside the active environment' "
        "sentence must follow the `which mess` block")
    # No competing MESS install command (pip / other channel) in fenced code.
    for line in fenced_lines:
        if "mess-static" in line:
            assert line == MESS_STATIC_INSTALL, line


def test_manual_and_wiki_mess_section_identical() -> None:
    """MANUAL and wiki are maintained in lock-step: the MESS section body is
    identical (the heading level differs: ### in MANUAL, ## in the wiki)."""
    manual_level, manual_body = _markdown_section(MANUAL, MESS_SECTION_TITLE)
    wiki_level, wiki_body = _markdown_section(WIKI_INSTALL, MESS_SECTION_TITLE)
    assert manual_level == 3 and wiki_level == 2, (manual_level, wiki_level)
    assert manual_body == wiki_body
    for needle in (MESS_STATIC_INSTALL, WHICH_MESS, "$CONDA_PREFIX/bin",
                   "inside the active environment"):
        assert needle in manual_body, f"MESS section lacks {needle!r}"


@pytest.mark.parametrize("doc", (MANUAL, WIKI_INSTALL), ids=lambda p: p.name)
def test_manual_wiki_recipe_lead_mentions_steps_2_and_5(doc: Path) -> None:
    """The fresh-env recipe now includes the MESS step, so its lead sentence
    must say it replaces steps 2 (install) AND 5 (MESS), and name MESS."""
    lead = _recipe_with_lead_sentence(doc).splitlines()[0]
    assert "replaces steps 2 and 5" in lead, lead
    assert "install MESS" in lead, lead
    assert "steps 2 and 6" not in lead and "step 2 above" not in lead, lead


@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda p: p.name)
def test_docs_which_mess_follow_up_after_recipe(doc: Path) -> None:
    """The prose after the fresh-env recipe tells the user to run
    ``which mess`` and expects it inside the environment."""
    text = doc.read_text(encoding="utf-8")
    recipe = _fresh_env_recipe_blocks(doc)[0]
    after = text[text.index(recipe) + len(recipe):]
    assert re.search(r"Run `which mess` afterwards", after), (
        f"{doc.relative_to(REPO)}: no `which mess` follow-up after the recipe")


def test_mess_regex_is_recipe_index_2_and_lacks_autoio_tokens() -> None:
    """Guard the recipe table itself: 6 lines, MESS at index 2 between
    ``conda activate`` and the git+ pre-install, and the MESS regex matches
    only the exact mess-static line (never the autoio/autochem conda form
    that :func:`test_docs_preinstall_autoio_autochem_from_auto_mech`
    recognises)."""
    assert len(FRESH_ENV_RECIPE_RES) == 6
    mess_re = FRESH_ENV_RECIPE_RES[MESS_RECIPE_INDEX]
    assert re.fullmatch(mess_re, MESS_STATIC_INSTALL)
    assert re.fullmatch(FRESH_ENV_RECIPE_RES[1], "conda activate kimeco")
    assert FRESH_ENV_RECIPE_RES[MESS_RECIPE_INDEX + 1] == GIT_PREINSTALL_RE
    for other in ("conda install autoio autochem -c auto-mech",
                  "conda install -c auto-mech mess-static",
                  "conda install -c auto-mech mess -y",
                  "pip install mess-static",
                  MESS_STATIC_INSTALL + " --force"):
        assert not re.fullmatch(mess_re, other), other
    assert "autoio" not in mess_re and "autochem" not in mess_re
    # The mess-static line must not be mistaken for the autoio/autochem
    # conda pre-install form used elsewhere in this module.
    assert re.search(r"conda install .*autoio .*autochem .*-c auto-mech",
                     MESS_STATIC_INSTALL) is None
    for pattern in FRESH_ENV_RECIPE_RES:
        if pattern is not mess_re:
            assert not re.fullmatch(pattern, MESS_STATIC_INSTALL), pattern


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


def test_tests_yml_base_job_still_installs_test_extra_only() -> None:
    """The first job keeps proving the base install without automech."""
    tests_yml = TESTS_YML.read_text(encoding="utf-8")
    assert re.search(r"pip install -e \.\[test\]\s*$", tests_yml, flags=re.M)


def test_tests_yml_every_python_matrix_is_311_and_312() -> None:
    tests_yml = TESTS_YML.read_text(encoding="utf-8")
    matrices = re.findall(r"python-version:\s*\[([^\]]*)\]", tests_yml)
    assert len(matrices) >= 2, "tests.yml: expected a matrix per job"
    for raw in matrices:
        matrix = [v.strip().strip('"\'') for v in raw.split(",")]
        assert matrix == ["3.11", "3.12"], matrix


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
