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
