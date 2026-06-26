"""Fixture-free regression guards for the kmoui (KimecoApp) wiring.

These tests lock the runtime contract between the GUI consumer
(`kimeco.gui.kimecoapp`) and the scoring-aware GOATs factory
(`kimeco.goat.GOATs.from_file`). They reproduce the *shape* of the bug that
was fixed -- a GUI consumer calling a changed runtime contract -- without
requiring a completed-run fixture (input JSON + workdir DBs + goats.txt),
which does not exist in the repo.

Only the standard library (`inspect`, `ast`) is used for the checks; the
project modules are imported solely to introspect their real signatures and
source so the guards stay in lock-step with the shipping code.
"""

from __future__ import annotations

import ast
import inspect

from kimeco.goat import GOATs
from kimeco.gui import kimecoapp
from kimeco.gui.kimecoapp import KimecoApp


def test_main_sets_scoring_function_before_initializing_databases() -> None:
    """`kmoui` `main()` must set the scoring function before DB init.

    `initialize_databases` builds GOATs via `GOATs.from_file(sf=self.sf)`, so
    `self.sf` must already exist. Reordering these calls would crash at
    startup; this guard fails fast on that mistake.
    """
    source = inspect.getsource(kimecoapp.main)
    tree = ast.parse(source)

    targets = {"set_scoring_function", "initialize_databases"}
    matched: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in targets
        ):
            matched.append((node.lineno, node.col_offset, node.func.attr))

    call_order = [attr for _, _, attr in sorted(matched)]

    assert "set_scoring_function" in call_order, (
        "kmoui main() must call set_scoring_function(): it primes self.sf "
        "used by initialize_databases() -> GOATs.from_file(sf=self.sf)."
    )
    assert "initialize_databases" in call_order, (
        "kmoui main() must call initialize_databases() to build the GOATs/DB "
        "context the GUI sections consume."
    )
    assert call_order.index("set_scoring_function") < call_order.index(
        "initialize_databases"
    ), (
        "kmoui main() must call set_scoring_function() BEFORE "
        "initialize_databases(): the latter constructs GOATs via "
        "GOATs.from_file(sf=self.sf), so the scoring function must be set "
        "first. This is the exact ordering contract that the fix restored."
    )


def test_initialize_databases_passes_sf_to_goats_from_file() -> None:
    """`initialize_databases` must pass `sf=self.sf` into `GOATs.from_file`.

    This is the precise call site that regressed. A `GOATs.from_file(...)` call
    that omits `sf=self.sf` would raise at runtime because `sf` is required.
    """
    source = inspect.getsource(KimecoApp.initialize_databases)

    assert "GOATs.from_file(" in source, (
        "KimecoApp.initialize_databases must construct GOATs via "
        "GOATs.from_file(...): the GUI sections request Model objects from it."
    )
    assert "sf=self.sf" in source, (
        "KimecoApp.initialize_databases must pass 'sf=self.sf' into "
        "GOATs.from_file(...): GOATs.from_file requires the scoring function, "
        "so omitting it crashes kmoui at startup. This guards the exact "
        "regression that was fixed."
    )
