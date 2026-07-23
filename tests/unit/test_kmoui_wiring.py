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
