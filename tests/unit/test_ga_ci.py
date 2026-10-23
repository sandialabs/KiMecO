"""CI-safe tests for ``GeneticAlgorithm`` methods invoked unbound on
``SimpleNamespace`` doubles (no GA/DB/MESS machinery):

* ``actualize_conv``: parameter-class aware convergence, dispatched via
  ``get_parameter_type``: ADDITIVE (we, be, pow) absolute change vs
  ``settings['conv_<ptype>']``; MULTIPLICATIVE (if, freq, bfc, sfc, mrc)
  log-space change |ln(old/new)| vs ``settings['param_conv']``; PERCENT (hrs,
  sigma, epsilon, fact) relative change; zero guards never raise.
* ``get_stats``: arithmetic mean / population std for ADDITIVE and PERCENT,
  geometric mean / std (``geometric_mean_and_std``) for MULTIPLICATIVE.
* ``write_ga_rates_output`` over the full KIN history.
* ``run_sensitivity``: new parameters only, active_p update, GOAT reset.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.goat import GOATs
from kimeco.optimizers.GeneticAlgo.ga import GeneticAlgorithm


# ===========================================================================
# actualize_conv
# ===========================================================================
IF_P = "R__if"      # multiplicative
HRS_P = "W__hrs0"   # percent
WE_P = "W__we"      # additive
MANGLED = "_GeneticAlgorithm__converged"


def _fake_ga(*, means, old_means, stds, old_stds, settings) -> SimpleNamespace:
    """SimpleNamespace carrying exactly the attributes actualize_conv reads."""
    fake = SimpleNamespace(
        means=means,
        old_means=old_means,
        stds=stds,
        old_stds=old_stds,
        settings=settings,
    )
    setattr(fake, MANGLED, {})
    return fake


def _run(fake: SimpleNamespace) -> dict:
    GeneticAlgorithm.actualize_conv(fake)
    return getattr(fake, MANGLED)


def test_multiplicative_convergence_is_log_space() -> None:
    """MULTIPLICATIVE if: 100 -> 50 with param_conv 0.6 is not converged (|ln 2|
    = 0.693, a relative 0.5 would have converged); small log changes converge."""
    # -- test_multiplicative_uses_log_space_not_relative: 100->50 with
    #    param_conv=0.6: relative change (0.5) would converge, but
    fake = _fake_ga(
        means={IF_P: 50.0},
        old_means={IF_P: 100.0},
        stds={IF_P: 10.0},
        old_stds={IF_P: 10.0},   # std unchanged -> isolates the mean
        settings={"param_conv": 0.6},
    )
    conv = _run(fake)
    # log(2) == 0.693 exceeds 0.6.
    assert abs(np.log(100.0 / 50.0)) > 0.6
    assert conv[IF_P] is False

    # -- test_multiplicative_converges_for_small_log_change: 100->95:
    #    |ln(100/95)| ~ 0.051 < 0.6 (both mean and std) -> converged.
    fake = _fake_ga(
        means={IF_P: 95.0},
        old_means={IF_P: 100.0},
        stds={IF_P: 95.0},
        old_stds={IF_P: 100.0},
        settings={"param_conv": 0.6},
    )
    conv = _run(fake)
    assert abs(np.log(100.0 / 95.0)) < 0.6
    assert conv[IF_P] is True

    # -- test_companion_mult_log_space: MULTIPLICATIVE if: 100->50 with
    #    param_conv 0.6. The log change
    fake = _conv_fake(
        means={IF_P: 50.0},
        old_means={IF_P: 100.0},
        stds={IF_P: 10.0},
        old_stds={IF_P: 10.0},
        settings={"param_conv": 0.6},
    )
    conv = _run_conv(fake)
    assert abs(np.log(100.0 / 50.0)) > 0.6
    assert conv[IF_P] is False

    # -- test_companion_mult_small: MULTIPLICATIVE if: 4.0->4.2 -> |ln(4/4.2)|
    #    = 0.0488 < 0.6 -> True.
    fake = _conv_fake(
        means={IF_P: 4.2},
        old_means={IF_P: 4.0},
        stds={IF_P: 4.2},
        old_stds={IF_P: 4.0},
        settings={"param_conv": 0.6},
    )
    conv = _run_conv(fake)
    assert abs(np.log(4.0 / 4.2)) < 0.6
    assert conv[IF_P] is True


def test_percent_convergence_is_relative_with_zero_guards() -> None:
    """PERCENT hrs keeps the relative rule (regression: not log-space); old_mean
    == 0 gives not-converged without an exception for percent and multiplicative
    parameters."""
    # -- test_percent_keeps_relative_change: Regression: 100->50 with
    #    param_conv=0.6 stays RELATIVE (0.5 < 0.6) ->
    fake = _fake_ga(
        means={HRS_P: 50.0},
        old_means={HRS_P: 100.0},
        stds={HRS_P: 50.0},
        old_stds={HRS_P: 100.0},
        settings={"param_conv": 0.6},
    )
    conv = _run(fake)
    assert abs(100.0 - 50.0) / 100.0 < 0.6   # relative rule converges
    assert conv[HRS_P] is True

    # -- test_companion_percent_relative: PERCENT hrs: 100->50 with param_conv
    #    0.6 stays RELATIVE
    fake = _conv_fake(
        means={HRS_P: 50.0},
        old_means={HRS_P: 100.0},
        stds={HRS_P: 50.0},
        old_stds={HRS_P: 100.0},
        settings={"param_conv": 0.6},
    )
    conv = _run_conv(fake)
    assert abs(100.0 - 50.0) / 100.0 < 0.6
    assert conv[HRS_P] is True

    # -- test_percent_zero_guard_no_exception: old_mean == 0 for a percent
    #    param -> not converged, no divide-by-zero.
    fake = _fake_ga(
        means={HRS_P: 50.0},
        old_means={HRS_P: 0.0},
        stds={HRS_P: 10.0},
        old_stds={HRS_P: 10.0},
        settings={"param_conv": 0.6},
    )
    conv = _run(fake)   # must not raise
    assert conv[HRS_P] is False

    # -- test_multiplicative_zero_guard_no_exception: old_mean == 0 for a
    #    multiplicative param -> not converged, no divide.
    fake = _fake_ga(
        means={IF_P: 50.0},
        old_means={IF_P: 0.0},
        stds={IF_P: 10.0},
        old_stds={IF_P: 10.0},
        settings={"param_conv": 0.6},
    )
    conv = _run(fake)   # must not raise
    assert conv[IF_P] is False


def test_additive_convergence_is_absolute() -> None:
    """ADDITIVE we: an absolute change within conv_we converges even at a large
    relative change; beyond it, not converged."""
    # -- test_additive_uses_absolute_change_vs_conv_ptype: we: absolute diff
    #    within conv_we converges even at large relative %.
    fake = _fake_ga(
        means={WE_P: 1.4},
        old_means={WE_P: 1.0},   # absolute diff 0.4 < 1.0 (but 40% relative)
        stds={WE_P: 1.2},
        old_stds={WE_P: 1.0},    # absolute diff 0.2 < 1.0
        settings={"conv_we": 1.0},
    )
    conv = _run(fake)
    assert conv[WE_P] is True

    # -- test_additive_not_converged_when_absolute_change_exceeds_threshold:
    #    we: an absolute mean move beyond conv_we is not converged.
    fake = _fake_ga(
        means={WE_P: 103.0},
        old_means={WE_P: 100.0},   # absolute diff 3.0 > 1.0
        stds={WE_P: 1.0},
        old_stds={WE_P: 1.0},
        settings={"conv_we": 1.0},
    )
    conv = _run(fake)
    assert conv[WE_P] is False

    # -- test_companion_additive_converges: ADDITIVE we: absolute Δmean 0.4 and
    #    Δstd 0.2 both < conv_we 0.5 -> True.
    fake = _conv_fake(
        means={WE_P: 5.4},
        old_means={WE_P: 5.0},
        stds={WE_P: 3.2},
        old_stds={WE_P: 3.0},
        settings={"conv_we": 0.5},
    )
    conv = _run_conv(fake)
    assert conv[WE_P] is True

    # -- test_companion_additive_not_converged: ADDITIVE we: absolute Δmean 3.0
    #    > conv_we 1.0 -> False.
    fake = _conv_fake(
        means={WE_P: 103.0},
        old_means={WE_P: 100.0},
        stds={WE_P: 1.0},
        old_stds={WE_P: 1.0},
        settings={"conv_we": 1.0},
    )
    conv = _run_conv(fake)
    assert conv[WE_P] is False


# ===========================================================================
# get_stats (and companion actualize_conv cases)
# ===========================================================================
def _model(params: dict[str, float]) -> SimpleNamespace:
    """One fake model exposing ``mdl.sop.parameters_names``."""
    return SimpleNamespace(sop=SimpleNamespace(parameters_names=params))


def _stats_fake(active_p: list[str]) -> SimpleNamespace:
    """SimpleNamespace carrying exactly what get_stats reads/calls."""
    fake = SimpleNamespace(settings={"active_p": list(active_p)})
    # @staticmethod -> raw function; self.geometric_mean_and_std(vals) resolves.
    fake.geometric_mean_and_std = GeneticAlgorithm.geometric_mean_and_std
    return fake


def test_get_stats_per_parameter_type() -> None:
    """get_stats: arithmetic mean/std for additive and percent, geometric for
    multiplicative; all-equal multiplicative values give a unit geometric std."""
    # -- test_get_stats_mean_std_per_parameter_type: Feed the same [2.0, 8.0]
    #    sample to one key of each parameter class in a
    fake = _stats_fake([WE_P, IF_P, HRS_P])
    models = [
        _model({WE_P: 2.0, IF_P: 2.0, HRS_P: 2.0}),
        _model({WE_P: 8.0, IF_P: 8.0, HRS_P: 8.0}),
    ]

    means, stds = GeneticAlgorithm.get_stats(fake, models)

    # ADDITIVE -- arithmetic mean / population std.
    assert means[WE_P] == pytest.approx(5.0)
    assert stds[WE_P] == pytest.approx(3.0)

    # PERCENT -- arithmetic (regression: NOT geometric / log-space).
    assert means[HRS_P] == pytest.approx(5.0)
    assert stds[HRS_P] == pytest.approx(3.0)

    # MULTIPLICATIVE -- geometric mean / geometric std.
    assert means[IF_P] == pytest.approx(4.0)
    assert stds[IF_P] == pytest.approx(2.0)

    # -- test_get_stats_multiplicative_all_equal_gives_unit_gstd: Constant
    #    multiplicative sample -> geometric mean is the value and the
    fake = _stats_fake([IF_P])
    models = [_model({IF_P: 5.0}) for _ in range(3)]

    means, stds = GeneticAlgorithm.get_stats(fake, models)

    assert means[IF_P] == pytest.approx(5.0)
    assert stds[IF_P] == pytest.approx(1.0)


def _conv_fake(*, means, old_means, stds, old_stds, settings) -> SimpleNamespace:
    fake = SimpleNamespace(
        means=means,
        old_means=old_means,
        stds=stds,
        old_stds=old_stds,
        settings=settings,
    )
    setattr(fake, MANGLED, {})
    return fake


def _run_conv(fake: SimpleNamespace) -> dict:
    GeneticAlgorithm.actualize_conv(fake)
    return getattr(fake, MANGLED)


# ===========================================================================
# write_ga_rates_output
# ===========================================================================
class DummyLogger:
    def info(self, msg: str) -> None:
        _ = msg

    def warning(self, msg: str) -> None:
        _ = msg


class DummySOP:
    def __init__(self) -> None:
        self.pes_ids = [0]

    def species_names_in_pes(self, pes_id: int) -> list[str]:
        assert pes_id == 0
        return ["A", "B"]

    def reaction_iterator(self):
        return iter([(0, "A", "B"), (0, "B", "A")])


class DummyKinDB:
    def __init__(self) -> None:
        self.last_query: dict[str, Any] = {}

    def get_rates_for_models(
        self,
        table_to_kin_ids: dict[str, list[int]],
        pres: list[float] | None = None,
        temp: list[float] | None = None,
        pes_ids: list[int] | None = None,
    ):
        self.last_query = {
            "table_to_kin_ids": table_to_kin_ids,
            "pres": pres,
            "temp": temp,
            "pes_ids": pes_ids,
        }
        rows = []
        for p in pres or []:
            for t in temp or []:
                rows.append(("G0000", 1, p, t, 0, "A", "B", 1.0))
                rows.append(("G0001", 3, p, t, 0, "A", "B", 9.0))
                rows.append(("G0000", 1, p, t, 0, "B", "A", 0.0))
                rows.append(("G0001", 3, p, t, 0, "B", "A", 16.0))
        return rows


class DummyGA(GeneticAlgorithm):
    def create_next_gen(self, gen):
        return {}, []


def test_geometric_mean_and_std_ignores_non_positive() -> None:
    assert DummyGA.geometric_mean_and_std([0.0, -2.0]) is None

    gm, gsd = DummyGA.geometric_mean_and_std([1.0, 9.0]) or (None, None)
    assert gm == pytest.approx(3.0)
    assert gsd == pytest.approx(3.0)


def test_write_ga_rates_output_uses_full_history_filter_and_order(
    tmp_path: Path,
) -> None:
    ga = cast(Any, object.__new__(DummyGA))
    ga.loc = str(tmp_path)
    ga.klog = DummyLogger()
    ga.settings = {
        "postprocess": False,
        "rc_pres": [1.0, 10.0],
        "rc_temp": [300.0, 500.0],
        "pres_unit": "Torr",
        "max_score": 4.0,
    }
    ga._eligible_models_for_rate_output = lambda: (
        [("G0000", 1, 2.0), ("G0001", 3, 1.0)],
        3,
    )
    ga.goats = SimpleNamespace(prefix="G")
    ga.f_mdl = SimpleNamespace(sop=DummySOP())
    ga.kin_db = DummyKinDB()

    out_file = ga.write_ga_rates_output()
    assert out_file.endswith("GA_rates.out")

    # Excluded model (0,2) must not be queried.
    assert ga.kin_db.last_query["table_to_kin_ids"] == {
        "G0000": [1],
        "G0001": [3],
    }

    content = Path(out_file).read_text(encoding="utf-8")

    # Pressure outer loop, temperature inner loop ordering.
    order = [
        "P = 1 Torr | T = 300 K",
        "P = 1 Torr | T = 500 K",
        "P = 10 Torr | T = 300 K",
        "P = 10 Torr | T = 500 K",
    ]
    indices = [content.index(token) for token in order]
    assert indices == sorted(indices)

    lines = content.splitlines()
    first_block_idx = lines.index("P = 1 Torr | T = 300 K")
    header = lines[first_block_idx + 1]
    row_a = lines[first_block_idx + 2]
    row_b = lines[first_block_idx + 3]

    # Column boundaries are fixed-width across rows.
    col2 = header.index("A", 1)
    col3 = header.index("B", col2 + 1)
    assert row_a.startswith("A")
    assert row_b.startswith("B")
    assert row_a[col2:col2 + 1] == "N"
    assert row_a[col3:col3 + 1] == "3"
    assert row_b[col2:col2 + 1] == "1"
    assert row_b[col3:col3 + 1] == "N"

    # First column width follows max-length + 2 rule.
    first_col_width = col2
    assert first_col_width == max(len("from"), len("A"), len("B")) + 2

    assert "3.00e+00 (3.00)" in content
    assert "1.60e+01 (1.00)" in content


# ===========================================================================
# run_sensitivity
# ===========================================================================
class _KlogSpy:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, msg: str) -> None:
        self.messages.append(msg)


class _SfSpy:
    def __init__(self) -> None:
        self.set_active_p_calls: list[list[str]] = []

    def set_active_p(self, active_p: list[str]) -> None:
        self.set_active_p_calls.append(list(active_p))


class _GoatsSpy:
    def __init__(self) -> None:
        self.reset_calls: int = 0

    def reset(self) -> None:
        self.reset_calls += 1


def _fake_self(active_p: list[str], sa_selection: list[str]):
    """Build a fake GA self that uses the SA_restart branch (no Linear)."""
    gen_id = 3
    return SimpleNamespace(
        new_gen_has_been_created=True,
        settings={
            "active_p": active_p,
            "SA_restart": {str(gen_id): sa_selection},
        },
        sf=_SfSpy(),
        goats=_GoatsSpy(),
        klog=_KlogSpy(),
        # Only touched on the Linear branch, kept for attribute symmetry.
        goat=[],
        input_tpls=[["dummy"]],
        pert=SimpleNamespace(),
    ), gen_id


def test_run_sensitivity_appends_new_params_and_resets_goats(tmp_path) -> None:
    """run_sensitivity appends only new parameters, sets active_p and resets the
    GOATs; GOATs.reset clears every seen model."""
    _tmp_root = tmp_path
    # -- test_run_sensitivity_appends_only_new_params
    fs, gen_id = _fake_self(
        active_p=["A__we"],
        sa_selection=["A__we", "B__we"],
    )

    GeneticAlgorithm.run_sensitivity(cast(Any, fs), gen_id=gen_id)

    # Only the genuinely-new B__we is appended; A__we is not duplicated.
    assert fs.settings["active_p"] == ["A__we", "B__we"]

    # -- test_run_sensitivity_new_param_sets_active_p_and_resets_goats
    fs, gen_id = _fake_self(
        active_p=["A__we"],
        sa_selection=["A__we", "B__we"],
    )

    GeneticAlgorithm.run_sensitivity(cast(Any, fs), gen_id=gen_id)

    # set_active_p called once with the extended list.
    assert fs.sf.set_active_p_calls == [["A__we", "B__we"]]
    # goats.reset() called exactly once.
    assert fs.goats.reset_calls == 1

    # -- test_goats_reset_clears_all_seen
    tmp_path = _tmp_root / 'test_goats_reset_clears_all_seen'
    tmp_path.mkdir(parents=True)
    goats = GOATs(
        sop_db=cast(Any, SimpleNamespace()),
        kin_db=cast(Any, SimpleNamespace()),
        sim_db=cast(Any, SimpleNamespace()),
        sf=cast(Any, SimpleNamespace()),
        wdir=str(tmp_path),
        overwrite=False,
    )
    goats.all_seen = {(0, 1): object(), (0, 2): object()}
    assert goats.all_seen

    goats.reset()

    assert goats.all_seen == {}


def test_run_sensitivity_no_new_param_is_noop() -> None:
    fs, gen_id = _fake_self(
        active_p=["A__we"],
        sa_selection=["A__we"],
    )

    GeneticAlgorithm.run_sensitivity(cast(Any, fs), gen_id=gen_id)

    # No new parameter -> no set_active_p, no reset, active_p unchanged.
    assert fs.sf.set_active_p_calls == []
    assert fs.goats.reset_calls == 0
    assert fs.settings["active_p"] == ["A__we"]




# ===========================================================================
# get_gen_one / get_next_gen / run / _eligible_models_for_rate_output
# ===========================================================================
import random  # noqa: E402

import kimeco.optimizers.GeneticAlgo.ga as ga_mod  # noqa: E402
from kimeco.enums import ModelStatus, RestartType  # noqa: E402
from kimeco.model import Model  # noqa: E402
from kimeco.optimizers.GeneticAlgo.exponential import Exponential  # noqa: E402

SEED = 1234


class _Klog:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _rec(self, level: str):
        def _log(msg: Any, *_a: Any, **_k: Any) -> None:
            self.records.append((level, str(msg)))
        return _log

    def __getattr__(self, level: str):
        if level in ('debug', 'info', 'warning', 'error'):
            return self._rec(level)
        raise AttributeError(level)

    def msgs(self, level: str) -> list[str]:
        return [m for lv, m in self.records if lv == level]


class _GaDB:
    def __init__(self, exists: bool = True, ids: list[int] | None = None,
                 rows: list[tuple] | None = None) -> None:
        self.exists = exists
        self.ids = ids or []
        self.rows = rows or []
        self.wiped: list[str] = []

    def table_exists(self, name: str) -> bool:
        return self.exists

    def wipe_table(self, name: str) -> None:
        self.wiped.append(name)

    def get_column(self, table: str, column_name: str) -> list[int]:
        return list(self.ids)

    def get_table(self, table: str) -> list[tuple]:
        return list(self.rows)


class _TotalGen:
    value = 1

    @classmethod
    def total(cls) -> int:
        return cls.value


def _ga_self(monkeypatch, settings: dict[str, Any], total: int = 1,
             ids: list[int] | None = None, rows: list[tuple] | None = None,
             finished: bool = True) -> Any:
    ga = object.__new__(DummyGA)
    ga.klog = _Klog()
    ga.settings = settings
    ga.new_gen_has_been_created = False
    scored: list[Any] = []

    def _fscore(mdl: Any) -> None:
        scored.append(mdl)
        mdl.score = 0.5

    ga.sf = SimpleNamespace(fscore=_fscore, scored=scored)
    perturbed: list[Any] = []

    def _perturb(sop: Any) -> Any:
        new = SimpleNamespace(pres=[1.0], temp=[300.0], perturbed=True)
        perturbed.append(new)
        return new

    ga.pert = SimpleNamespace(perturb=_perturb, done=perturbed)
    ga.f_mdl = SimpleNamespace(sop=SimpleNamespace(pres=[1.0], temp=[300.0]))
    ga.sop_db = _GaDB(ids=ids, rows=rows)
    ga.kin_db = _GaDB(exists=False)
    ga.sim_db = _GaDB()
    ga.is_generation_finished = lambda gen_id: finished
    monkeypatch.setattr(ga_mod.SOP, 'from_db_row', staticmethod(
        lambda sop_tpl, row: SimpleNamespace(pres=[1.0], temp=[300.0], row=list(row))))
    _TotalGen.value = total
    monkeypatch.setattr(ga_mod, 'Generation', _TotalGen)
    return ga


def test_get_gen_one_restart_from_db(monkeypatch) -> None:
    rows = [(1, 0.1), (2, 0.2)]
    # (a) complete generation in DB, default restart
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.DEFAULT},
                  ids=[1, 2], rows=rows)
    prev, nxt = ga.get_gen_one()
    assert nxt[0] is ga.f_mdl
    assert [(m.id, m.gen, m.status) for m in nxt[1:]] == [
        (1, 1, ModelStatus.DONE), (2, 1, ModelStatus.DONE)]
    assert [m.sop.row for m in nxt[1:]] == [[0.1], [0.2]]
    assert ga.sf.scored == nxt[1:]
    assert prev == {0: ga.f_mdl, 1: ga.f_mdl, 2: ga.f_mdl}
    assert ga.pert.done == []

    # (b) rescore restart: RESCORE status, no fscore
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.RESCORE},
                  ids=[1, 2], rows=rows)
    _, nxt = ga.get_gen_one()
    assert [m.status for m in nxt[1:]] == [ModelStatus.RESCORE] * 2
    assert ga.sf.scored == []

    # (c) partial generation: tables wiped, generation recreated
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.DEFAULT},
                  ids=[1], rows=rows[:1])
    _, nxt = ga.get_gen_one()
    assert ga.sop_db.wiped == ['G0001'] and ga.sim_db.wiped == ['G0001']
    assert ga.kin_db.wiped == []  # table_exists False: skipped
    assert [(m.id, m.gen) for m in nxt[1:]] == [(1, 1), (2, 1)]
    assert [m.sop for m in nxt[1:]] == ga.pert.done
    assert not ga.new_gen_has_been_created


def test_get_gen_one_creates_new_generation(monkeypatch) -> None:
    # (d) generation absent from DB
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.DEFAULT},
                  total=4, finished=False)
    prev, nxt = ga.get_gen_one()
    assert ga.new_gen_has_been_created
    assert ga.sop_db.wiped == ['G0004'] and ga.sim_db.wiped == ['G0004']
    assert ga.kin_db.wiped == []
    assert [(m.id, m.gen, m.status) for m in nxt[1:]] == [
        (1, 4, ModelStatus.SOP), (2, 4, ModelStatus.SOP)]
    assert len(ga.pert.done) == 2 and len(prev) == 3

    # (e) rescore without DB generation
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.RESCORE},
                  finished=False)
    with pytest.raises(TypeError, match='Rescoring only'):
        ga.get_gen_one()


def test_get_next_gen_restart_mix_and_create(monkeypatch) -> None:
    rows = [(0, 0.1), (2, 0.3)]
    prev_m1 = SimpleNamespace(id=1)
    gen = SimpleNamespace(id=1, models=[SimpleNamespace(id=0), prev_m1,
                                        SimpleNamespace(id=2)])
    # (a) finished, default: DB models 0 and 2, model 1 reused
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.DEFAULT},
                  total=2, ids=[0, 2], rows=rows)
    prev, nxt = ga.get_next_gen(gen=cast(Any, gen))
    assert prev == {}
    assert nxt[1] is prev_m1
    assert [(nxt[i].id, nxt[i].gen, nxt[i].status) for i in (0, 2)] == [
        (0, 2, ModelStatus.DONE), (2, 2, ModelStatus.DONE)]
    assert [nxt[i].sop.row for i in (0, 2)] == [[0.1], [0.3]]
    assert ga.sf.scored == [nxt[0], nxt[2]]

    # (b) rescore: RESCORE statuses, still scored
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.RESCORE},
                  total=2, ids=[0, 2], rows=rows)
    _, nxt = ga.get_next_gen(gen=cast(Any, gen))
    assert [nxt[i].status for i in (0, 2)] == [ModelStatus.RESCORE] * 2
    assert len(ga.sf.scored) == 2

    # (c) model 1 neither in DB nor in the previous generation
    gen_missing = SimpleNamespace(id=1, models=[SimpleNamespace(id=0)])
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.DEFAULT},
                  total=2, ids=[0, 2], rows=rows)
    with pytest.raises(TypeError, match='Model 1 not found'):
        ga.get_next_gen(gen=cast(Any, gen_missing))

    # (d) not finished: wipe and delegate to create_next_gen
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.DEFAULT},
                  total=2, finished=False)
    seen: list[Any] = []
    sentinel = ({0: 'p'}, ['n'])
    ga.create_next_gen = lambda gen: seen.append(gen) or sentinel
    assert ga.get_next_gen(gen=cast(Any, gen)) == sentinel
    assert seen == [gen] and ga.new_gen_has_been_created
    assert ga.sop_db.wiped == ['G0002'] and ga.kin_db.wiped == []

    # (e) rescore, not finished
    ga = _ga_self(monkeypatch, {'n_mdl': 3, 'restart': RestartType.RESCORE},
                  total=2, finished=False)
    with pytest.raises(TypeError, match='Rescoring only'):
        ga.get_next_gen(gen=cast(Any, gen))


class _FakeGeneration:
    n = 0
    built: list['_FakeGeneration'] = []

    @classmethod
    def total(cls) -> int:
        return cls.n

    def __init__(self, models: list[Any], **kw: Any) -> None:
        self.id = _FakeGeneration.n
        _FakeGeneration.n += 1
        self.models = models
        self.kw = kw
        _FakeGeneration.built.append(self)

    def run(self) -> None:
        return None


def _run_ga(monkeypatch, score: float, settings: dict[str, Any],
            rates_ok: bool) -> tuple[Any, dict[str, list]]:
    _FakeGeneration.n = 0
    _FakeGeneration.built = []
    monkeypatch.setattr(ga_mod, 'Generation', _FakeGeneration)
    ga = object.__new__(DummyGA)
    ga.klog = _Klog()
    ga.settings = settings
    ga.input_tpls = []
    ga.sop_db = ga.kin_db = ga.sim_db = ga.pert = None
    setattr(ga, '_GeneticAlgorithm__converged', {})
    calls: dict[str, list] = {'next': [], 'sa': [], 'stats': []}
    f_mdl = SimpleNamespace(score=score)
    m1, m2 = SimpleNamespace(score=score), SimpleNamespace(score=score)
    ga.gen_0 = _FakeGeneration(models=[f_mdl])
    ga.update_goat = lambda new_mdls: setattr(ga, 'goat', list(new_mdls))
    ga.get_stats = lambda models: ({}, {})
    ga.actualize_conv = lambda: None
    ga.print_stats = lambda: calls['stats'].append(True)
    ga.get_gen_one = lambda: ({0: 'prev1'}, [m1])

    def _next(gen: Any) -> Any:
        calls['next'].append(gen.id)
        return {0: 'prev2'}, [m2]

    ga.get_next_gen = _next
    ga.run_sensitivity = lambda gen_id: calls['sa'].append(gen_id)

    def _rates() -> str:
        if not rates_ok:
            raise RuntimeError('boom')
        return 'GA_rates.out'

    ga.write_ga_rates_output = _rates
    ga._best_model_subset = lambda goat: goat[:1]
    ga.sf = SimpleNamespace(
        breakdown_width=lambda models: 12,
        format_score_breakdown=lambda models, label, width: label)
    ga.run()
    return ga, calls


def test_run_loop_triggers_sensitivity_and_reports(monkeypatch) -> None:
    settings = {'max_gen': 3, 'max_score': 4.0, 'score_conv': 2.0,
                'SA_freq': 1, 'SA_start': 1, 'SA_end': 1}
    ga, calls = _run_ga(monkeypatch, 10.0, settings, rates_ok=True)
    gens = _FakeGeneration.built[1:]
    assert [g.id for g in gens] == [1, 2]
    assert gens[0].kw['previous_el'] == {0: 'prev1'}
    assert gens[1].kw['previous_el'] == {0: 'prev2'}
    assert calls == {'next': [1], 'sa': [1], 'stats': [True]}
    info = ga.klog.msgs('info')
    assert any('Reached 3 (max_gen)' in m for m in info)
    assert 'Convergence rate statistics written to GA_rates.out' in info
    assert info[-4:] == ['Termination at generation 2', 'GENERATION - AVERAGE',
                         'GOAT - BEST MODEL', 'GOAT - AVERAGE']


def test_run_converges_early_and_logs_rate_output_failure(monkeypatch) -> None:
    settings = {'max_gen': 5, 'max_score': 4.0, 'score_conv': 2.0,
                'SA_freq': 1, 'SA_start': 1, 'SA_end': 1}
    ga, calls = _run_ga(monkeypatch, 1.0, settings, rates_ok=False)
    assert [g.id for g in _FakeGeneration.built] == [0, 1]
    assert calls == {'next': [], 'sa': [], 'stats': []}
    assert any('Failed to write GA convergence rate statistics: boom' in m
               for m in ga.klog.msgs('warning'))
    info = ga.klog.msgs('info')
    assert not any('max_gen' in m for m in info)
    assert 'Termination at generation 1' in info


def test_eligible_models_for_rate_output_filters_and_sorts(monkeypatch) -> None:
    tables = {'G0002': [(2, 0.0)], 'G0000': [(0, 0.0)], 'SA0001': [(0, 0.0)],
              'NMSG0000': [(0, 0.0)], 'G0001': [(3, 0.0), (1, 0.0)]}
    read: list[str] = []
    sop_db = SimpleNamespace(
        tables={k: None for k in tables},
        get_table=lambda table: read.append(table) or tables[table])
    scores = {(0, 0): 1.0, (1, 3): 2.0, (1, 1): float('inf'), (2, 2): 5.0}
    built: list[Any] = []

    def _fscore(mdl: Any) -> None:
        built.append(mdl)
        mdl.score = scores[(mdl.gen, mdl.id)]

    ga = object.__new__(DummyGA)
    ga.settings = {'max_score': 4}
    ga.sop_db = sop_db
    ga.sf = SimpleNamespace(fscore=_fscore)
    ga.f_mdl = SimpleNamespace(sop='tpl')
    monkeypatch.setattr(ga_mod.SOP, 'from_db_row', staticmethod(
        lambda sop_tpl, row: SimpleNamespace(pres=[1.0], temp=[300.0], row=row)))

    assert ga._eligible_models_for_rate_output() == (
        [('G0000', 0, 1.0), ('G0001', 3, 2.0)], 4)
    assert read == ['G0000', 'G0001', 'G0002']
    assert all(isinstance(m, Model) and m.status == ModelStatus.DONE for m in built)
    assert [(m.gen, m.id) for m in built] == [(0, 0), (1, 3), (1, 1), (2, 2)]

    # no generation table at all
    read.clear()
    ga.sop_db = SimpleNamespace(tables={'SA0001': None},
                                get_table=lambda table: read.append(table) or [])
    assert ga._eligible_models_for_rate_output() == ([], 0)
    assert read == []


def test_exponential_create_next_gen_keeps_best_and_fills_every_slot() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    for label, gen_id, scores in (('a', 1, [1, 2, 3, 4, 5, 6]),
                                  ('b', 4, [8, 7, 6, 5, 4, 3, 2, 1])):
        exp = object.__new__(Exponential)
        exp.klog = _Klog()
        n_calls: list[Any] = []
        exp.pert = SimpleNamespace(perturb=lambda sop: n_calls.append(sop) or SimpleNamespace(
            pres=[1.0], temp=[300.0], parent=sop))
        models = []
        for i, s in enumerate(scores):
            m = Model(sop=cast(Any, SimpleNamespace(pres=[1.0], temp=[300.0], idx=i)),
                      id=i, gen=gen_id)
            m.score = float(s)
            models.append(m)
        n = len(models)
        gen = SimpleNamespace(id=gen_id, models=models)
        prev, nxt = exp.create_next_gen(gen=cast(Any, gen))
        best = int(np.argmin(scores))
        assert len(nxt) == n, label
        assert set(prev) == set(range(n)), label
        assert nxt[best] is models[best], label
        kept = [i for i in range(n) if nxt[i] is models[i]]
        new = [i for i in range(n) if nxt[i] is not models[i]]
        for i in kept:
            assert prev[i] is models[i], label
        for i in new:
            assert nxt[i].id == i and nxt[i].gen == gen_id + 1, label
            assert prev[i] in [models[k] for k in kept], label
            assert nxt[i].sop.parent.idx == prev[i].sop.idx, label
        assert len(n_calls) == len(new) == n - len(kept) > 0, label
        assert f'{len(new)} new models created.' in exp.klog.msgs('info'), label
