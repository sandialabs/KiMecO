from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from kimeco._kimeco import KiMecO
from kimeco.model import Model
from kimeco.enums import RestartType


class _KlogSpy:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: str) -> None:
        self.messages.append(msg)


class _SfSpy:
    def __init__(self) -> None:
        self.set_active_p_calls: list[list[str]] = []

    def set_active_p(self, active_p: list[str]) -> None:
        # Store a copy so later in-place mutations of settings['active_p']
        # do not retroactively change what we recorded.
        self.set_active_p_calls.append(list(active_p))


class _PerturbatorStub:
    """Stand-in for the real Perturbator: counts constructions only."""

    instances: int = 0

    def __init__(self, **kwargs: Any) -> None:
        type(self).instances += 1
        self.kwargs = kwargs

    def print_pert_parameters(self) -> None:  # pragma: no cover - unused here
        pass


class _LinearStub:
    """Stand-in for the sensitivity.Linear analysis.

    Records whether it was constructed/run and returns a fixed selection.
    """

    instances: int = 0
    reset_calls: int = 0
    save_calls: int = 0
    selected: list[str] = ["A__we", "B__we"]
    models_from_db: bool = True

    def __init__(self, **kwargs: Any) -> None:
        type(self).instances += 1
        self.kwargs = kwargs
        self.models = list(kwargs.get("models", []))
        self.models_from_db = type(self).models_from_db
        self.selected = list(type(self).selected)

    @staticmethod
    def reset() -> None:
        _LinearStub.reset_calls += 1

    def run(self) -> None:
        pass

    def save_initial_model(self, **kwargs: Any) -> None:
        type(self).save_calls += 1


def _fake_self(first_sensi: bool, active_p: list[str], restart: RestartType):
    init_sop = SimpleNamespace(pres=[1.0], temp=[300.0])
    return SimpleNamespace(
        init_SOP=cast(Any, init_sop),
        first_sensi=first_sensi,
        settings={"active_p": active_p, "restart": restart},
        klog=_KlogSpy(),
        input_tpls=[["dummy"]],
        sf=_SfSpy(),
        pert=SimpleNamespace(),
        sop_db=SimpleNamespace(),
        kin_db=SimpleNamespace(),
        sim_db=SimpleNamespace(),
    )


def test_user_supplied_active_p_skips_linear_sa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _PerturbatorStub.instances = 0
    _LinearStub.instances = 0
    monkeypatch.setattr("kimeco._kimeco.Perturbator", _PerturbatorStub)
    monkeypatch.setattr("kimeco._kimeco.Linear", _LinearStub)

    user_active_p = ["A__we", "B__we"]
    fs = _fake_self(
        first_sensi=False,
        active_p=user_active_p,
        restart=RestartType.DEFAULT,
    )

    KiMecO.set_important_parameters(cast(Any, fs))

    # Linear SA is never constructed when the user supplies active_p.
    assert _LinearStub.instances == 0
    # active_p is preserved unchanged.
    assert fs.settings["active_p"] == ["A__we", "B__we"]
    # f_mdl is a real Model with id 0.
    assert isinstance(fs.f_mdl, Model)
    assert fs.f_mdl.id == 0
    # set_active_p is called exactly once with the user's active_p.
    assert fs.sf.set_active_p_calls == [["A__we", "B__we"]]
    # The perturbator is rebuilt once at the end.
    assert _PerturbatorStub.instances == 1


def test_empty_active_p_runs_linear_sa_and_uses_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _PerturbatorStub.instances = 0
    _LinearStub.instances = 0
    _LinearStub.reset_calls = 0
    _LinearStub.save_calls = 0
    _LinearStub.selected = ["A__we", "B__we"]
    _LinearStub.models_from_db = True  # skip the DB save_initial_model branch
    monkeypatch.setattr("kimeco._kimeco.Perturbator", _PerturbatorStub)
    monkeypatch.setattr("kimeco._kimeco.Linear", _LinearStub)

    fs = _fake_self(
        first_sensi=True,
        active_p=[],
        restart=RestartType.DEFAULT,
    )

    KiMecO.set_important_parameters(cast(Any, fs))

    # Linear SA is constructed and run once.
    assert _LinearStub.instances == 1
    assert _LinearStub.reset_calls == 1
    # active_p becomes the SA selection.
    assert fs.settings["active_p"] == ["A__we", "B__we"]
    # models_from_db True + non-RESCORE restart -> save_initial_model skipped.
    assert _LinearStub.save_calls == 0
    # set_active_p is still called after the branch with the selection.
    assert fs.sf.set_active_p_calls == [["A__we", "B__we"]]


# ===========================================================================
# get_ensemble
# ===========================================================================
from kimeco.database.sop_db import SOP_DB  # noqa: E402
from tests.unit.test_goat_ci import _build_sop, _row_values  # noqa: E402


class _EnsLog:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *a: Any, **k: Any) -> None:
        self.warnings.append(msg)


def _ens_self(tmp_path, name: str, layout: dict[str, dict[int, float]]):
    """KiMecO with a re-opened SOP_DB holding ``layout`` ({table: {id: fact}})."""
    sop = _build_sop()
    db = SOP_DB(sop=sop, name=name, path=str(tmp_path))
    for table, rows in layout.items():
        db.create_new_table(name=table)
        for row_id, fact in rows.items():
            db.prepare_batch_upsert(table=table, id=row_id, values=_row_values(
                sop, {'fact': fact, 'pw': 2.0, 's0': 0.1, 's1': 0.2}))
    db.batch_upsert()
    kmo = object.__new__(KiMecO)
    kmo.sop_db = SOP_DB(sop=sop, name=name, path=str(tmp_path))
    kmo.init_SOP = sop
    scored: list[Model] = []

    def _fscore(mdl: Model) -> None:
        scored.append(mdl)
        mdl.score = 1.0

    kmo.sf = SimpleNamespace(fscore=_fscore)
    kmo.klog = _EnsLog()
    return kmo, scored


def test_get_ensemble_g0001_uses_initial_model_from_g0000(tmp_path) -> None:
    kmo, scored = _ens_self(tmp_path, 'ENS_OK', {
        'G0000': {0: 1.5, 1: 9.0},
        'G0001': {1: 1.1, 2: 1.2, 3: 1.3}})
    models = kmo.get_ensemble(' G0001 ')
    assert [m.id for m in models] == [0, 1, 2, 3]
    assert [m.gen for m in models] == [0, 1, 1, 1]
    assert [m['__fact'] for m in models] == pytest.approx([1.5, 1.1, 1.2, 1.3])
    assert scored == [models[0]]
    assert kmo.klog.warnings == []
    with pytest.raises(NotImplementedError):
        kmo.get_ensemble('G0002')


def test_get_ensemble_g0001_guard_misses_return_empty(tmp_path) -> None:
    layouts = {
        'ENS_NO_G1': {'G0000': {0: 1.5}},
        'ENS_EMPTY_G1': {'G0000': {0: 1.5}, 'G0001': {}},
        'ENS_NO_G0': {'G0001': {1: 1.1, 2: 1.2}},
        'ENS_NO_ROW0': {'G0000': {5: 1.5}, 'G0001': {1: 1.1, 2: 1.2}},
    }
    for name, layout in layouts.items():
        kmo, scored = _ens_self(tmp_path, name, layout)
        assert kmo.get_ensemble('G0001') == [], name
        assert kmo.klog.warnings == ["Ensemble 'G0001' not found or empty."], name
        assert scored == [], name


def test_get_ensemble_goat_tokens_and_unknown_names() -> None:
    calls: list[int] = []
    goats = SimpleNamespace(get_goat_for_gen=lambda gen: calls.append(gen) or [f'm{gen}'])
    kmo = object.__new__(KiMecO)
    kmo.klog = _EnsLog()
    kmo.optimizer = SimpleNamespace(goats=goats)
    assert kmo.get_ensemble('GT-1') == ['m-1']
    assert kmo.get_ensemble('GT0003') == ['m3']
    assert calls == [-1, 3] and kmo.klog.warnings == []

    kmo.optimizer = SimpleNamespace()
    assert kmo.get_ensemble('GT-1') == []
    assert kmo.klog.warnings == ["No GOATs object for ensemble 'GT-1'.",
                                 "Ensemble 'GT-1' not found or empty."]

    kmo.klog = _EnsLog()
    assert kmo.get_ensemble(' X ') == []
    assert kmo.klog.warnings == ["Ensemble 'X' not found or empty."]
