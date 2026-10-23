"""CI-safe arity lock for ``load_config_to_gui`` (Defect A).

The load callback must return exactly as many values as it declares Outputs on
every branch (early no-op, exception fan-out, success). A stale
``perturbation-pert-dropdown`` Output was removed; these tests pin the arity so a
future edit that adds/drops an Output without fixing all return tuples fails
loudly instead of raising Dash's opaque runtime mismatch.
"""

import ast
import json
from types import SimpleNamespace

from dash import no_update

from kimeco.gui.input_sections import save_load_write_section as slw

MODULE_PATH = slw.__file__


def _declared_output_count() -> int:
    """Count ``Output(...)`` args on the ``load_config_to_gui`` decorator."""
    src = open(MODULE_PATH, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "load_config_to_gui":
            dec = node.decorator_list[0]
            return sum(
                1
                for a in dec.args
                if isinstance(a, ast.Call)
                and getattr(a.func, "id", "") == "Output"
            )
    raise AssertionError("load_config_to_gui not found")


DECLARED = _declared_output_count()


def _set_ctx(monkeypatch, triggered_id):
    monkeypatch.setattr(
        slw, "callback_context",
        SimpleNamespace(triggered_id=triggered_id),
    )


def test_declared_output_count_is_69():
    assert DECLARED == 69


def test_every_return_branch_matches_declared_arity(monkeypatch, tmp_path) -> None:
    """The early return (not clicked) is an all-no_update tuple of full arity; a
    load failure fans out to the same arity (message + no_update); a valid load
    returns the full arity with q_name last; all branches share one length."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_early_return_tuple_matches_declared: Not-clicked, non-autoload
    #    trigger -> all-no_update tuple of full arity.
    with _mp_root.context() as monkeypatch:
        _set_ctx(monkeypatch, "load-config-button")
        result = slw.load_config_to_gui(0, None, "cfg.json")
        assert len(result) == DECLARED
        assert all(item is no_update for item in result)

    # -- test_exception_return_tuple_matches_declared: A load failure fans out
    #    to the same arity (2 real + rest no_update).
    with _mp_root.context() as monkeypatch:
        _set_ctx(monkeypatch, "load-config-button")

        def _boom(_path):
            raise FileNotFoundError("missing")

        monkeypatch.setattr(slw, "_resolve_load_path", _boom)
        result = slw.load_config_to_gui(1, None, "does-not-exist.json")
        assert len(result) == DECLARED
        assert isinstance(result[0], str)
        assert "Failed to load config" in result[0]
        assert all(item is no_update for item in result[2:])

    # -- test_success_return_tuple_matches_declared: A valid load returns a
    #    full-arity tuple; q_name is the preserved last.
    tmp_path = _tmp_root / 'test_success_return_tuple_matches_declared'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"q_name": "day-long-cpu"}), encoding="utf-8")

        _set_ctx(monkeypatch, "load-config-button")
        monkeypatch.setattr(slw, "_resolve_load_path", lambda _p: str(cfg))

        result = slw.load_config_to_gui(1, None, str(cfg))
        assert len(result) == DECLARED
        # First output is the status string, last output is q_name value.
        assert isinstance(result[0], str)
        assert result[-1] == "day-long-cpu"

    # -- test_all_branches_share_one_arity: Every branch returns the identical
    #    length (no drift between them).
    tmp_path = _tmp_root / 'test_all_branches_share_one_arity'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        _set_ctx(monkeypatch, "load-config-button")
        early = slw.load_config_to_gui(0, None, "cfg.json")

        monkeypatch.setattr(
            slw, "_resolve_load_path",
            lambda _p: (_ for _ in ()).throw(FileNotFoundError()),
        )
        exc = slw.load_config_to_gui(1, None, "nope.json")

        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({}), encoding="utf-8")
        monkeypatch.setattr(slw, "_resolve_load_path", lambda _p: str(cfg))
        ok = slw.load_config_to_gui(1, None, str(cfg))

        assert len(early) == len(exc) == len(ok) == DECLARED


def test_autoload_trigger_runs_not_early_return(monkeypatch, tmp_path):
    """Autoload path triggers a real load even with n_clicks falsy."""
    cfg = tmp_path / "auto.json"
    cfg.write_text(json.dumps({"q_name": "auto-q"}), encoding="utf-8")
    _set_ctx(monkeypatch, "autoload-config-path-store")
    monkeypatch.setattr(slw, "_resolve_load_path", lambda _p: str(cfg))

    result = slw.load_config_to_gui(0, str(cfg), None)
    assert len(result) == DECLARED
    assert result[-1] == "auto-q"


def test_no_phantom_pert_dropdown_in_source():
    src = open(MODULE_PATH, encoding="utf-8").read()
    assert "perturbation-pert-dropdown" not in src
