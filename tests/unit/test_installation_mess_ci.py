"""CI-safe tests for the MESS binary installation contract.

KiMecO runs MESS by invoking the bare ``mess`` command (``subprocess.run(
["mess", ...])`` in the emitted automech driver and ``mess {filename}.inp``
in the SLURM templates), so the binary must resolve *from PATH* and, per
README / MANUAL / wiki, ``which mess`` must print a path **inside the active
environment** (``.../envs/kimeco/bin/mess``) after
``conda install -c auto-mech mess-static -y``.

Contract exercised here
-----------------------
* ``which mess`` (the documented check) prints exactly one path, located in
  ``<sys.prefix>/bin`` -- the environment of the interpreter running kimeco;
  ``shutil.which`` agrees with it.
* ``<sys.prefix>/bin/mess`` is a regular, executable, non-trivial file.
* Bare ``mess`` with no argument is a safe health check: exit status 0,
  ``usage: mess ...`` on stdout, no files written to the working directory.
  ``mess --help`` is **not** a health check (MESS treats ``--help`` as an
  input file name and fails), which is why no test uses it.
* kimeco itself invokes the bare ``mess`` command (no absolute path, no
  ``$CONDA_PREFIX/bin/`` prefix) from the driver and the job templates, so
  the PATH contract above is exactly what the code relies on.

Skip-vs-fail policy (``KIMECO_REQUIRE_MESS``)
---------------------------------------------
The real-binary cases need MESS on PATH. When ``mess`` is **missing** they
*skip* unless the ``KIMECO_REQUIRE_MESS`` environment variable is truthy
(``1`` / ``true`` / ``yes``, case insensitive), in which case they *fail*;
``0`` / ``false`` / ``no`` / empty / unset mean "not required" and any other
value is a configuration error (``ValueError``). When ``mess`` resolves
**outside** ``<sys.prefix>/bin`` the cases always *fail* -- required or not
-- because that is precisely the mis-installation the docs warn about. The
``test-mess-binary`` job in ``.github/workflows/tests.yml`` installs
``mess-static`` with micromamba and sets ``KIMECO_REQUIRE_MESS=1`` so CI
proves the documented route works; a developer environment without MESS
only skips. No test ever runs a real MESS input.

The policy itself is exercised end-to-end against fake environments built
under ``tmp_path`` (fake ``bin/mess`` shell script, symlinks, several PATH
entries), so those cases run everywhere, including environments without
MESS. Only the standard library and ``pytest`` are used.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping

import pytest

REPO = Path(__file__).resolve().parents[2]
# The runtime driver is emitted from a module-level template string; the
# ``subprocess.run(["mess", ...])`` call lives *inside* that string.
AUTOMECH_KIN_EMITTER = REPO / "kimeco" / "writers" / "automech_kin.py"
AUTOMECH_KIN_TEMPLATE_NAME = "automech_kin_tpl"
TEMPLATE_FILES = {
    REPO / "kimeco" / "templates" / "kin_arr_tpl.py": "kin_arr_tpl",
    REPO / "kimeco" / "templates" / "messjob.py": "messtpl",
}

REQUIRE_MESS_ENV = "KIMECO_REQUIRE_MESS"
_TRUE_VALUES = frozenset({"1", "true", "yes"})
_FALSE_VALUES = frozenset({"", "0", "false", "no"})

MESS_COMMAND = "mess"
USAGE_RE = re.compile(r"^usage: mess\b")
# The static MESS binary is tens of MB; anything below 1 MB is a stub/script.
MIN_MESS_SIZE_BYTES = 1 << 20
MESS_TIMEOUT_S = 60

STATUS_INSIDE = "inside"
STATUS_OUTSIDE = "outside"
STATUS_MISSING = "missing"


# ---------------------------------------------------------------------------
# Helpers (pure functions, exercised directly by the fake-env cases)
# ---------------------------------------------------------------------------
def mess_required(env: Mapping[str, str] | None = None) -> bool:
    """Parse ``KIMECO_REQUIRE_MESS``: truthy -> strict, falsy/unset -> skip
    mode, anything else -> ``ValueError`` (a typo must not silently skip)."""
    env = os.environ if env is None else env
    raw = env.get(REQUIRE_MESS_ENV)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{REQUIRE_MESS_ENV}={raw!r} is not understood; use one of "
        f"{sorted(_TRUE_VALUES)} to require MESS or {sorted(_FALSE_VALUES - {''})} "
        "/ empty / unset to allow skipping")


def locate_mess(env: Mapping[str, str] | None = None) -> Path | None:
    """First ``mess`` executable on ``env['PATH']`` (what ``which mess``
    prints), or ``None`` when there is none."""
    env = os.environ if env is None else env
    found = shutil.which(MESS_COMMAND, path=env.get("PATH", ""))
    return Path(found) if found else None


def classify_mess(prefix: Path,
                  env: Mapping[str, str] | None = None
                  ) -> tuple[str, Path | None]:
    """Classify the resolved ``mess`` relative to ``<prefix>/bin``.

    A binary (or symlink) *located* in ``<prefix>/bin`` is ``inside`` --
    the directory the docs tell users to look at / copy into. A ``mess``
    found elsewhere on PATH is ``outside`` even if it is a symlink pointing
    into the environment, because ``which mess`` would print the outside
    path and kimeco would run whatever PATH resolves first.
    """
    found = locate_mess(env)
    if found is None:
        return STATUS_MISSING, None
    expected_dir = (Path(prefix) / "bin").resolve()
    if found.parent.resolve() == expected_dir:
        return STATUS_INSIDE, found
    return STATUS_OUTSIDE, found


def check_mess_binary(prefix: Path,
                      required: bool,
                      env: Mapping[str, str] | None = None) -> Path:
    """Apply the skip-vs-fail policy and return the ``mess`` path.

    * ``inside``  -> return the path;
    * ``outside`` -> ``pytest.fail`` (always, required or not);
    * ``missing`` -> ``pytest.fail`` when *required*, else ``pytest.skip``.
    """
    status, found = classify_mess(prefix, env)
    if status == STATUS_INSIDE:
        assert found is not None
        return found
    if status == STATUS_OUTSIDE:
        pytest.fail(
            f"'mess' resolves to {found}, outside the active environment "
            f"({Path(prefix) / 'bin'}); the docs require "
            "'conda install -c auto-mech mess-static -y' in the activated "
            "environment so that 'which mess' prints a path inside it")
    message = (f"'mess' is not on PATH (expected {Path(prefix) / 'bin' / 'mess'}); "
               "install it with 'conda install -c auto-mech mess-static -y'")
    if required:
        pytest.fail(f"{REQUIRE_MESS_ENV} is set but {message}")
    pytest.skip(message)


def conda_prefix_mismatch(prefix: Path,
                          env: Mapping[str, str] | None = None) -> bool:
    """True when ``CONDA_PREFIX`` is set but is not the interpreter prefix.

    The interpreter running kimeco (``sys.prefix``) is authoritative for the
    classification; a differing ``CONDA_PREFIX`` means the shell activated a
    different environment than the one pytest runs in.
    """
    env = os.environ if env is None else env
    conda_prefix = env.get("CONDA_PREFIX")
    if not conda_prefix:
        return False
    return Path(conda_prefix).resolve() != Path(prefix).resolve()


def run_bare_mess(mess: Path | str, cwd: Path,
                  env: Mapping[str, str] | None = None
                  ) -> subprocess.CompletedProcess[str]:
    """Run ``mess`` with no argument (the only safe invocation)."""
    return subprocess.run([str(mess)], cwd=str(cwd), env=None if env is None
                          else dict(env), capture_output=True, text=True,
                          timeout=MESS_TIMEOUT_S, check=False)


def _which_available() -> bool:
    return shutil.which("which") is not None


def _make_fake_mess(path: Path) -> Path:
    """Create a tiny executable that mimics bare ``mess`` (usage, rc 0)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\necho "usage: mess input_file"\nexit 0\n',
                    encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _fake_env(tmp_path: Path, *dirs: Path) -> dict[str, str]:
    """Environment whose PATH is exactly ``dirs`` (no leak from the host)."""
    return {"PATH": os.pathsep.join(str(d) for d in dirs),
            "HOME": str(tmp_path)}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def active_prefix() -> Path:
    return Path(sys.prefix)


def real_mess_path(active_prefix: Path) -> Path:
    """The real ``mess`` inside the active environment, policy applied.

    Called from the test body (not a fixture) so a violation shows up as a
    FAILED test rather than a setup ERROR.
    """
    return check_mess_binary(active_prefix, mess_required(), os.environ)


# ---------------------------------------------------------------------------
# Standard cases: the documented `which mess` check on the real environment
# ---------------------------------------------------------------------------
def test_which_mess_resolves_inside_active_env(active_prefix: Path) -> None:
    """User-requested case: ``which mess`` (the check documented in README /
    MANUAL / wiki) prints one line that lives under ``<sys.prefix>/bin`` and
    that file exists."""
    mess_path = real_mess_path(active_prefix)
    if not _which_available():
        pytest.skip("the 'which' command is not available on this platform")
    proc = subprocess.run(["which", MESS_COMMAND], capture_output=True,
                          text=True, check=False)
    assert proc.returncode == 0, f"'which mess' failed: {proc.stderr.strip()}"
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 1, f"'which mess' must print exactly one line: {lines}"
    resolved = Path(lines[0])
    assert resolved.parent.resolve() == (active_prefix / "bin").resolve(), (
        f"'which mess' printed {resolved}, not under {active_prefix / 'bin'}")
    assert (active_prefix / "bin" / MESS_COMMAND).exists()
    assert resolved.resolve() == mess_path.resolve()


def test_shutil_which_agrees_with_which_command(active_prefix: Path) -> None:
    mess_path = real_mess_path(active_prefix)
    if not _which_available():
        pytest.skip("the 'which' command is not available on this platform")
    proc = subprocess.run(["which", MESS_COMMAND], capture_output=True,
                          text=True, check=False)
    assert proc.returncode == 0
    assert Path(proc.stdout.strip()).resolve() == mess_path.resolve()
    assert Path(shutil.which(MESS_COMMAND)).resolve() == mess_path.resolve()


def test_which_a_first_match_is_the_active_env(active_prefix: Path) -> None:
    """Even when several ``mess`` binaries are on PATH (e.g. another conda
    env leaking in), the *first* match -- the one kimeco runs -- must be the
    active environment's."""
    mess_path = real_mess_path(active_prefix)
    if not _which_available():
        pytest.skip("the 'which' command is not available on this platform")
    proc = subprocess.run(["which", "-a", MESS_COMMAND], capture_output=True,
                          text=True, check=False)
    assert proc.returncode == 0
    matches = [Path(ln) for ln in proc.stdout.strip().splitlines()]
    assert matches, "'which -a mess' printed nothing"
    assert matches[0].parent.resolve() == (active_prefix / "bin").resolve(), (
        f"first PATH match is {matches[0]}; all matches: {matches}")


def test_mess_binary_is_a_regular_executable_file(active_prefix: Path) -> None:
    mess_path = real_mess_path(active_prefix)
    assert mess_path.is_file(), f"{mess_path} is not a regular file"
    assert not mess_path.is_dir()
    assert os.access(mess_path, os.X_OK), f"{mess_path} is not executable"
    size = mess_path.stat().st_size
    assert size > MIN_MESS_SIZE_BYTES, (
        f"{mess_path} is only {size} bytes; the static MESS binary is tens "
        "of MB -- this looks like a stub or a wrapper script")


def test_mess_no_args_prints_usage(active_prefix: Path,
                                   tmp_path: Path) -> None:
    """Bare ``mess`` (no input file) is the health check: exit 0, usage on
    stdout, and nothing written to the working directory. Invoked as the
    bare command (PATH lookup), exactly like kimeco does."""
    real_mess_path(active_prefix)  # policy gate: inside / outside / missing
    before = sorted(p.name for p in tmp_path.iterdir())
    proc = run_bare_mess(MESS_COMMAND, cwd=tmp_path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert proc.returncode == 0, (
        f"bare 'mess' exited {proc.returncode}: stdout={proc.stdout!r} "
        f"stderr={proc.stderr!r}")
    assert USAGE_RE.search(proc.stdout), (
        f"bare 'mess' must print 'usage: mess ...' on stdout; got "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
    assert before == after, f"bare 'mess' wrote files: {set(after) - set(before)}"


def test_mess_help_flag_is_not_a_health_check(active_prefix: Path,
                                              tmp_path: Path) -> None:
    """``mess --help`` is treated as an input file name and fails; guards
    against someone 'simplifying' the health check to ``--help``."""
    real_mess_path(active_prefix)  # policy gate: inside / outside / missing
    proc = subprocess.run([MESS_COMMAND, "--help"], cwd=str(tmp_path),
                          capture_output=True, text=True,
                          timeout=MESS_TIMEOUT_S, check=False)
    assert proc.returncode != 0, (
        "'mess --help' unexpectedly succeeded; if MESS gained a real --help, "
        "revisit the bare-invocation health check")
    assert not list(tmp_path.iterdir()), "'mess --help' wrote files"


def test_conda_prefix_matches_interpreter_prefix(active_prefix: Path) -> None:
    """When a conda env is activated, it must be the one pytest runs in --
    otherwise 'inside the active environment' is ambiguous."""
    if not os.environ.get("CONDA_PREFIX"):
        pytest.skip("CONDA_PREFIX is not set (no activated conda env)")
    assert not conda_prefix_mismatch(active_prefix, os.environ), (
        f"CONDA_PREFIX={os.environ['CONDA_PREFIX']} but the interpreter "
        f"prefix is {active_prefix}")


# ---------------------------------------------------------------------------
# Standard case: kimeco invokes the bare `mess` command from PATH
# ---------------------------------------------------------------------------
def _subprocess_run_argv_literals(source: str) -> list[list[object]]:
    """First positional argument of every ``subprocess.run([...])`` call in
    ``source`` whose argv is a list literal (elements literal-evaluated when
    possible, otherwise the AST node is kept)."""
    tree = ast.parse(source)
    argvs: list[list[object]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and node.args
                and isinstance(node.args[0], ast.List)):
            continue
        argv: list[object] = []
        for elt in node.args[0].elts:
            try:
                argv.append(ast.literal_eval(elt))
            except ValueError:
                argv.append(elt)
        argvs.append(argv)
    return argvs


def _module_string_constant(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name
                        for t in node.targets)):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError(f"{path.name}: no module-level string {name!r}")


def test_kimeco_invokes_bare_mess_from_path() -> None:
    """The emitted automech driver runs ``subprocess.run(["mess", <input>])``
    and the SLURM templates emit ``mess <file>.inp``: a bare command, no
    absolute path, no ``$CONDA_PREFIX/bin`` prefix -- hence the PATH
    contract tested above. The driver template string is extracted with
    ``ast`` (never imported) and parsed as Python itself."""
    driver_src = _module_string_constant(AUTOMECH_KIN_EMITTER,
                                         AUTOMECH_KIN_TEMPLATE_NAME)
    argvs = _subprocess_run_argv_literals(driver_src)
    mess_calls = [a for a in argvs if a and a[0] == MESS_COMMAND]
    assert mess_calls, (
        f"{AUTOMECH_KIN_EMITTER.relative_to(REPO)}: no "
        f"subprocess.run(['mess', ...]) call in {AUTOMECH_KIN_TEMPLATE_NAME}; "
        f"found {argvs}")
    assert all(len(a) == 2 for a in mess_calls), mess_calls
    assert "/mess" not in driver_src and "CONDA_PREFIX" not in driver_src
    for argv in argvs:
        first = argv[0]
        if isinstance(first, str):
            assert "/" not in first or first == MESS_COMMAND, (
                f"driver runs {first!r} instead of the bare 'mess' command")

    for path, name in TEMPLATE_FILES.items():
        template = _module_string_constant(path, name)
        mess_lines = [ln.strip() for ln in template.splitlines()
                      if re.match(r"\s*mess\b", ln)]
        assert mess_lines, (
            f"{path.relative_to(REPO)}: template {name!r} does not invoke mess")
        for line in mess_lines:
            assert re.match(r"mess \{filename\}", line), line
        assert "/mess" not in template and "CONDA_PREFIX" not in template, (
            f"{path.relative_to(REPO)}: template must invoke bare 'mess'")


# ---------------------------------------------------------------------------
# Edge cases: KIMECO_REQUIRE_MESS parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", " Yes ", "YES"])
def test_require_mess_truthy_values(value: str) -> None:
    assert mess_required({REQUIRE_MESS_ENV: value}) is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "  ", "False", "NO"])
def test_require_mess_falsy_values(value: str) -> None:
    assert mess_required({REQUIRE_MESS_ENV: value}) is False


def test_require_mess_unset_means_not_required() -> None:
    assert mess_required({}) is False
    assert mess_required({"KIMECO_REQUIRE_EXTRAS": "automech"}) is False


@pytest.mark.parametrize("value", ["2", "maybe", "on", "off", "y", "n", "None"])
def test_require_mess_rejects_unknown_values(value: str) -> None:
    with pytest.raises(ValueError, match=REQUIRE_MESS_ENV):
        mess_required({REQUIRE_MESS_ENV: value})


# ---------------------------------------------------------------------------
# Edge cases: skip-vs-fail policy against fake environments
# ---------------------------------------------------------------------------
def test_missing_mess_skips_when_not_required(tmp_path: Path) -> None:
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    env = _fake_env(tmp_path, prefix / "bin")
    assert classify_mess(prefix, env) == (STATUS_MISSING, None)
    with pytest.raises(pytest.skip.Exception, match="mess-static"):
        check_mess_binary(prefix, required=False, env=env)


def test_missing_mess_fails_when_required(tmp_path: Path) -> None:
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    env = _fake_env(tmp_path, prefix / "bin")
    with pytest.raises(pytest.fail.Exception, match=REQUIRE_MESS_ENV):
        check_mess_binary(prefix, required=True, env=env)


def test_missing_bin_directory_is_missing_not_error(tmp_path: Path) -> None:
    """A prefix without a bin/ directory at all (e.g. a broken env) is
    reported as missing rather than raising from the path arithmetic."""
    prefix = tmp_path / "env"
    prefix.mkdir()
    env = _fake_env(tmp_path, prefix / "bin")
    assert classify_mess(prefix, env)[0] == STATUS_MISSING


@pytest.mark.parametrize("required", [False, True], ids=["optional", "required"])
def test_outside_env_fails_even_when_not_required(tmp_path: Path,
                                                  required: bool) -> None:
    """A ``mess`` found elsewhere on PATH is the mis-installation the docs
    warn about: it fails regardless of KIMECO_REQUIRE_MESS."""
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    other = _make_fake_mess(tmp_path / "other" / "bin" / "mess")
    env = _fake_env(tmp_path, other.parent, prefix / "bin")
    status, found = classify_mess(prefix, env)
    assert status == STATUS_OUTSIDE
    assert found == other
    with pytest.raises(pytest.fail.Exception, match="outside the active"):
        check_mess_binary(prefix, required=required, env=env)


@pytest.mark.parametrize("required", [False, True], ids=["optional", "required"])
def test_inside_fake_env_passes_end_to_end(tmp_path: Path,
                                           required: bool) -> None:
    """Full pipeline on a fake env: locate -> classify inside -> policy
    returns the path -> bare invocation prints usage with rc 0 and writes
    nothing."""
    prefix = tmp_path / "env"
    fake = _make_fake_mess(prefix / "bin" / "mess")
    env = _fake_env(tmp_path, prefix / "bin")
    assert locate_mess(env) == fake
    assert classify_mess(prefix, env) == (STATUS_INSIDE, fake)
    assert check_mess_binary(prefix, required=required, env=env) == fake

    workdir = tmp_path / "work"
    workdir.mkdir()
    try:
        proc = run_bare_mess(fake, cwd=workdir, env=env)
    except PermissionError:  # pragma: no cover - noexec tmp mount
        pytest.skip("cannot execute scripts from tmp_path on this host")
    assert proc.returncode == 0
    assert USAGE_RE.search(proc.stdout)
    assert not list(workdir.iterdir())


def test_non_executable_file_in_bin_is_missing(tmp_path: Path) -> None:
    """A ``bin/mess`` without the executable bit is not found by
    ``which``/``shutil.which`` -- i.e. 'missing', not 'inside'."""
    prefix = tmp_path / "env"
    fake = _make_fake_mess(prefix / "bin" / "mess")
    fake.chmod(stat.S_IRUSR | stat.S_IWUSR)
    if os.access(fake, os.X_OK):  # pragma: no cover - root / odd FS
        pytest.skip("filesystem ignores the executable bit")
    env = _fake_env(tmp_path, prefix / "bin")
    assert classify_mess(prefix, env)[0] == STATUS_MISSING


def test_symlink_inside_bin_counts_as_inside(tmp_path: Path) -> None:
    """The docs' fallback ('copy the binaries into $CONDA_PREFIX/bin') also
    holds for a symlink placed there: ``which mess`` prints the env path."""
    prefix = tmp_path / "env"
    (prefix / "bin").mkdir(parents=True)
    real = _make_fake_mess(tmp_path / "build" / "mess")
    link = prefix / "bin" / "mess"
    link.symlink_to(real)
    env = _fake_env(tmp_path, prefix / "bin")
    status, found = classify_mess(prefix, env)
    assert status == STATUS_INSIDE
    assert found == link
    assert found.resolve() == real.resolve()


def test_symlink_outside_pointing_into_env_is_outside(tmp_path: Path) -> None:
    """A symlink elsewhere on PATH that points into the env is still
    'outside': ``which mess`` prints the outside path (what kimeco runs)."""
    prefix = tmp_path / "env"
    real = _make_fake_mess(prefix / "bin" / "mess")
    other = tmp_path / "other"
    other.mkdir()
    (other / "mess").symlink_to(real)
    env = _fake_env(tmp_path, other, prefix / "bin")
    status, found = classify_mess(prefix, env)
    assert status == STATUS_OUTSIDE
    assert found == other / "mess"


def test_symlinked_prefix_is_still_inside(tmp_path: Path) -> None:
    """``sys.prefix`` given through a symlinked directory (e.g. ~/.conda ->
    /data/...) resolves to the same bin/ directory."""
    real_prefix = tmp_path / "real_env"
    fake = _make_fake_mess(real_prefix / "bin" / "mess")
    linked_prefix = tmp_path / "linked_env"
    linked_prefix.symlink_to(real_prefix, target_is_directory=True)
    env = _fake_env(tmp_path, linked_prefix / "bin")
    assert classify_mess(linked_prefix, env)[0] == STATUS_INSIDE
    assert classify_mess(real_prefix, env)[0] == STATUS_INSIDE
    assert locate_mess(env).resolve() == fake.resolve()


def test_first_path_match_wins_over_later_env_bin(tmp_path: Path) -> None:
    """``which -a`` semantics: PATH order decides. env/bin first -> inside;
    another env's bin first -> outside, even though the env binary exists."""
    prefix = tmp_path / "env"
    mine = _make_fake_mess(prefix / "bin" / "mess")
    other = _make_fake_mess(tmp_path / "other_env" / "bin" / "mess")

    env_first = _fake_env(tmp_path, prefix / "bin", other.parent)
    assert classify_mess(prefix, env_first) == (STATUS_INSIDE, mine)

    other_first = _fake_env(tmp_path, other.parent, prefix / "bin")
    assert classify_mess(prefix, other_first) == (STATUS_OUTSIDE, other)


def test_empty_path_is_missing(tmp_path: Path) -> None:
    prefix = tmp_path / "env"
    _make_fake_mess(prefix / "bin" / "mess")
    assert classify_mess(prefix, {"PATH": ""})[0] == STATUS_MISSING
    assert classify_mess(prefix, {})[0] == STATUS_MISSING


def test_policy_uses_interpreter_prefix_not_conda_prefix(tmp_path: Path) -> None:
    """CONDA_PREFIX mismatch policy: the classification is made against the
    interpreter prefix; a differing CONDA_PREFIX is reported as a mismatch
    but does not move the goalposts."""
    prefix = tmp_path / "env"
    mine = _make_fake_mess(prefix / "bin" / "mess")
    other_prefix = tmp_path / "other_env"
    (other_prefix / "bin").mkdir(parents=True)
    env = {**_fake_env(tmp_path, prefix / "bin"),
           "CONDA_PREFIX": str(other_prefix)}
    assert conda_prefix_mismatch(prefix, env) is True
    assert classify_mess(prefix, env) == (STATUS_INSIDE, mine)
    assert check_mess_binary(prefix, required=True, env=env) == mine

    env_ok = {**env, "CONDA_PREFIX": str(prefix)}
    assert conda_prefix_mismatch(prefix, env_ok) is False
    assert conda_prefix_mismatch(prefix, {"PATH": ""}) is False
    assert conda_prefix_mismatch(prefix, {"CONDA_PREFIX": ""}) is False
