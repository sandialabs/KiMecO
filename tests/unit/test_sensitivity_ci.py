"""CI-safe tests for the sensitivity analysis and Nelder-Mead step helpers:
``Linear.average`` (geometric mean for multiplicative parameters, arithmetic
otherwise; ``SOP.from_db_row`` patched so no real SOP/DB is built) and
``calculate_dstep`` of ``Linear`` (SA) and ``NelderMead`` (log-space steps
for multiplicative parameters, linear otherwise), built with ``__new__`` and
a directly instantiated ``Perturbator``.
"""

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import kimeco.sensitivity.linear as linear_mod
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.enums import Ptype
from kimeco.optimizers.NelderMead.nelder_mead import NelderMead
from kimeco.sensitivity.linear import Linear


# ===========================================================================
# Linear.average
# ===========================================================================
# Fully-qualified parameter names (dbs == '__'); the suffix drives dispatch.
# Verified against the real get_parameter_type:
#   R__if  -> Ptype.IF  (MULTIPLICATIVE)
#   W__we  -> Ptype.WE  (ADDITIVE, non-multiplicative)
#   W__hrs0 -> Ptype.HRS (PERCENT, non-multiplicative)
IF_P = "R__if"      # multiplicative -> geometric mean
WE_P = "W__we"      # additive       -> arithmetic mean
HRS_P = "W__hrs0"   # percent        -> arithmetic mean


def _sop(params: dict[str, float]) -> SimpleNamespace:
    """One fake SOP exposing ``sop.parameters_names``."""
    return SimpleNamespace(parameters_names=dict(params))


def _fake_from_db_row(sop_tpl, row):
    """Stand-in for SOP.from_db_row: rebuild parameters_names from the template
    key order + the averaged ``row`` values, as a SimpleNamespace."""
    keys = list(sop_tpl.parameters_names.keys())
    return SimpleNamespace(parameters_names=dict(zip(keys, row)))


@pytest.fixture()
def sa() -> Linear:
    """Bare Linear -- ``average`` touches no instance attributes."""
    return Linear.__new__(Linear)


@pytest.fixture
def patch_from_db_row(monkeypatch):
    """Route SOP.from_db_row through the SimpleNamespace rebuilder for every
    test so ``average`` never constructs a real SOP."""
    monkeypatch.setattr(linear_mod.SOP, "from_db_row",
                        staticmethod(_fake_from_db_row))


@pytest.mark.usefixtures("patch_from_db_row")
def test_average_multiplicative_geometric_mean(sa) -> None:
    """Multiplicative parameters average geometrically (numerical check, a known
    two-SOP value, all-equal values unchanged)."""
    # -- test_average_multiplicative_geometric_mean_numerical: if [1, 4, 16] ->
    #    geometric mean exp((ln1+ln4+ln16)/3) = 4.0, which is
    sops = [_sop({IF_P: 1.0}), _sop({IF_P: 4.0}), _sop({IF_P: 16.0})]
    out = sa.average(sops)
    assert out.parameters_names[IF_P] == pytest.approx(4.0)
    assert out.parameters_names[IF_P] != pytest.approx(7.0)

    # -- test_average_two_sop_geometric_known_value: if [2, 8] -> sqrt(2*8) =
    #    4.0 (arithmetic mean would be 5.0).
    sops = [_sop({IF_P: 2.0}), _sop({IF_P: 8.0})]
    out = sa.average(sops)
    assert out.parameters_names[IF_P] == pytest.approx(4.0)
    assert out.parameters_names[IF_P] != pytest.approx(5.0)

    # -- test_average_multiplicative_all_equal_returns_value: A constant
    #    multiplicative sample -> geometric mean is the value itself.
    sops = [_sop({IF_P: 5.0}) for _ in range(3)]
    out = sa.average(sops)
    assert out.parameters_names[IF_P] == pytest.approx(5.0)


@pytest.mark.usefixtures("patch_from_db_row")
def test_average_arithmetic_dispatch_and_single_sop(sa, monkeypatch) -> None:
    """Additive and percent parameters average arithmetically, dispatched
    through get_parameter_type; a single SOP comes back unchanged."""
    _mp_root = monkeypatch
    # -- test_average_non_multiplicative_uses_arithmetic_mean: Mixed template:
    #    additive we and percent hrs use the arithmetic mean while
    sops = [
        _sop({WE_P: 3.0, HRS_P: 10.0, IF_P: 1.0}),
        _sop({WE_P: 6.0, HRS_P: 20.0, IF_P: 4.0}),
        _sop({WE_P: 9.0, HRS_P: 30.0, IF_P: 16.0}),
    ]
    out = sa.average(sops)
    assert out.parameters_names[WE_P] == pytest.approx(6.0)    # arithmetic
    assert out.parameters_names[HRS_P] == pytest.approx(20.0)  # arithmetic
    assert out.parameters_names[IF_P] == pytest.approx(4.0)    # geometric

    # -- test_average_dispatch_uses_get_parameter_type: average routes class
    #    selection through get_parameter_type: force a
    with _mp_root.context() as monkeypatch:
        monkeypatch.setattr(linear_mod, "get_parameter_type", lambda p: Ptype.WE)
        sops = [_sop({IF_P: 1.0}), _sop({IF_P: 4.0}), _sop({IF_P: 16.0})]
        out = sa.average(sops)
        assert out.parameters_names[IF_P] == pytest.approx(7.0)
        assert out.parameters_names[IF_P] != pytest.approx(4.0)

    # -- test_average_single_sop_returns_values_unchanged: count == 1 -> every
    #    class collapses to the single sample value.
    sops = [_sop({WE_P: 12.0, HRS_P: 33.0, IF_P: 7.0})]
    out = sa.average(sops)
    assert out.parameters_names[WE_P] == pytest.approx(12.0)
    assert out.parameters_names[HRS_P] == pytest.approx(33.0)
    assert out.parameters_names[IF_P] == pytest.approx(7.0)


@pytest.mark.usefixtures("patch_from_db_row")
def test_average_nonpositive_or_empty_raises(sa) -> None:
    """A non-positive multiplicative sample or an empty SOP list raises
    ValueError."""
    # -- test_average_multiplicative_nonpositive_raises: Geometric mean is
    #    undefined for zero/negative multiplicative values ->
    with pytest.raises(ValueError):
        sa.average([_sop({IF_P: 4.0}), _sop({IF_P: 0.0})])
    with pytest.raises(ValueError):
        sa.average([_sop({IF_P: 4.0}), _sop({IF_P: -2.0})])

    # -- test_average_empty_sop_list_raises: average([]) indexes sop_list[0]
    #    before any per-parameter guard runs, so
    with pytest.raises(IndexError):
        sa.average([])


# ===========================================================================
# SA / NM derivative steps
# ===========================================================================
# IF_P, WE_P and HRS_P are defined above; MRC_P is multiplicative too.
MRC_P = "R__mrc0"


def _make_pert(uncertainties: dict[str, float],
               values: dict[str, float],
               std_overrides: dict[str, Any] | None = None) -> Perturbator:
    """Build a real Perturbator with a fake i_sop exposing the given params."""
    settings: dict[str, Any] = {"active_p": [], "max_std": 3}
    if std_overrides:
        settings.update(std_overrides)
    klog = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    pert = Perturbator(settings, SimpleNamespace(), klog)
    pert.i_sop = SimpleNamespace(
        uncertainties=dict(uncertainties),
        parameters_names=dict(values),
    )
    return pert


def _make_sa(pert: Perturbator, lin_fact: float) -> Linear:
    """Bare Linear carrying only what ``calculate_dstep`` touches."""
    sa = Linear.__new__(Linear)
    sa.pert = pert
    sa.lin_fact = lin_fact
    return sa


def _make_nm(pert: Perturbator, nm_dstep: float) -> NelderMead:
    """Bare NelderMead carrying only what ``calculate_dstep`` touches."""
    nm = NelderMead.__new__(NelderMead)
    nm.pert = pert
    nm.settings = {"nm_dstep": nm_dstep}
    return nm


def test_sa_multiplicative_step_is_exact_and_log_symmetric() -> None:
    """SA multiplicative step: the worked example is exact, magnitudes scale
    with a non-unit value, the two sides are log-symmetric and the uncertainty
    is not applied twice."""
    # -- test_sa_multiplicative_worked_example_exact: uc=1.1, sensi_d=0.1,
    #    value=1.0, 'if' -> up/down == [1.1**0.1, 1/1.1**0.1].
    pert = _make_pert({IF_P: 1.1}, {IF_P: 1.0})
    sa = _make_sa(pert, lin_fact=0.1)
    up = sa.calculate_dstep(uc=1.1, param=IF_P, side=1, value=1.0)
    down = sa.calculate_dstep(uc=1.1, param=IF_P, side=-1, value=1.0)
    assert up == pytest.approx(1.1 ** 0.1)
    assert down == pytest.approx(1 / 1.1 ** 0.1)

    # -- test_sa_multiplicative_magnitudes_for_nonunit_value: Non-unit value
    #    scales by the same factor on each side.
    value = 800.0
    pert = _make_pert({IF_P: 1.2}, {IF_P: value})
    sa = _make_sa(pert, lin_fact=0.1)
    factor = 1.2 ** 0.1
    up = sa.calculate_dstep(uc=1.2, param=IF_P, side=1, value=value)
    down = sa.calculate_dstep(uc=1.2, param=IF_P, side=-1, value=value)
    assert up == pytest.approx(value * factor)
    assert down == pytest.approx(value / factor)

    # -- test_sa_multiplicative_log_symmetry: up/value == value/down == f and
    #    up*down == value**2 (geometric).
    value = 500.0
    pert = _make_pert({MRC_P: 1.3}, {MRC_P: value})
    sa = _make_sa(pert, lin_fact=0.2)
    f = 1.3 ** 0.2
    up = sa.calculate_dstep(uc=1.3, param=MRC_P, side=1, value=value)
    down = sa.calculate_dstep(uc=1.3, param=MRC_P, side=-1, value=value)
    assert up / value == pytest.approx(f)
    assert value / down == pytest.approx(f)
    assert up * down == pytest.approx(value ** 2)

    # -- test_sa_multiplicative_no_double_scaling: Exactly [1/f, f]*value with
    #    f = uc**lin_fact, nothing extra.
    value = 3.0
    uc, lin = 1.5, 0.1
    pert = _make_pert({IF_P: uc}, {IF_P: value})
    sa = _make_sa(pert, lin_fact=lin)
    f = uc ** lin
    assert sa.calculate_dstep(uc=uc, param=IF_P, side=1,
                              value=value) == pytest.approx(value * f)
    assert sa.calculate_dstep(uc=uc, param=IF_P, side=-1,
                              value=value) == pytest.approx(value / f)


def test_sa_multiplicative_edges() -> None:
    """SA multiplicative edges: uncertainty 1 is the identity, a large
    uncertainty stays finite, positive and symmetric, and the step is not the
    old linear log-sigma one."""
    # -- test_sa_multiplicative_uc_one_is_identity: uc==1 -> factor 1 -> up ==
    #    down == value (no perturbation).
    value = 42.0
    pert = _make_pert({IF_P: 1.0}, {IF_P: value})
    sa = _make_sa(pert, lin_fact=0.1)
    up = sa.calculate_dstep(uc=1.0, param=IF_P, side=1, value=value)
    down = sa.calculate_dstep(uc=1.0, param=IF_P, side=-1, value=value)
    assert up == pytest.approx(value)
    assert down == pytest.approx(value)

    # -- test_sa_multiplicative_large_uc_finite_positive_symmetric: A very
    #    large uc stays finite, strictly positive, still log-symmetric.
    value = 2.0
    uc, lin = 1000.0, 0.1
    pert = _make_pert({IF_P: uc}, {IF_P: value})
    sa = _make_sa(pert, lin_fact=lin)
    up = sa.calculate_dstep(uc=uc, param=IF_P, side=1, value=value)
    down = sa.calculate_dstep(uc=uc, param=IF_P, side=-1, value=value)
    assert np.isfinite(up) and np.isfinite(down)
    assert up > 0.0 and down > 0.0
    assert up * down == pytest.approx(value ** 2)

    # -- test_sa_multiplicative_regression_not_linear_logsigma: Regression:
    #    multiplicative up is value*uc**lin, NOT value + ln(uc)*lin.
    value = 1.0
    uc, lin = 2.0, 0.5
    pert = _make_pert({IF_P: uc}, {IF_P: value},
                      std_overrides={"max_std": 3})
    sa = _make_sa(pert, lin_fact=lin)
    up = sa.calculate_dstep(uc=uc, param=IF_P, side=1, value=value)
    f = uc ** lin
    assert up == pytest.approx(value * f)
    assert up == pytest.approx(1.41421356)
    # The (buggy) linear-in-log-sigma value must differ.
    scale = pert.get_scale(ptype=Ptype.IF.value, param=IF_P)
    buggy = value + scale * lin
    assert buggy == pytest.approx(1.34657359)
    assert abs(up - buggy) > 1e-4


def test_sa_additive_and_percent_steps() -> None:
    """SA additive and percent steps are linear and symmetric; the additive
    magnitude is scale * lin_fact."""
    # -- test_sa_additive_linear_symmetry_and_step: we: up-value == value-down
    #    == get_scale*lin_fact; scale == uncertainty.
    value, unc, lin = 100.0, 2.0, 0.1
    pert = _make_pert({WE_P: unc}, {WE_P: value})
    sa = _make_sa(pert, lin_fact=lin)
    scale = pert.get_scale(ptype=Ptype.WE.value, param=WE_P)
    assert scale == pytest.approx(unc)          # additive scale == uncertainty
    step = scale * lin
    up = sa.calculate_dstep(uc=unc, param=WE_P, side=1, value=value)
    down = sa.calculate_dstep(uc=unc, param=WE_P, side=-1, value=value)
    assert up == pytest.approx(value + step)
    assert down == pytest.approx(value - step)
    assert (up - value) == pytest.approx(value - down)

    # -- test_sa_additive_magnitude_is_scale_times_linfact: The step magnitude
    #    equals get_scale * lin_fact exactly.
    value, unc, lin = 100.0, 1.5, 0.2
    pert = _make_pert({WE_P: unc}, {WE_P: value})
    sa = _make_sa(pert, lin_fact=lin)
    scale = pert.get_scale(ptype=Ptype.WE.value, param=WE_P)
    up = sa.calculate_dstep(uc=unc, param=WE_P, side=1, value=value)
    assert (up - value) == pytest.approx(scale * lin)

    # -- test_sa_percent_linear_symmetry: hrs: percent scale ==
    #    uncertainty*value; up-value == value-down.
    value, unc, lin = 800.0, 0.1, 0.1
    pert = _make_pert({HRS_P: unc}, {HRS_P: value})
    sa = _make_sa(pert, lin_fact=lin)
    scale = pert.get_scale(ptype=Ptype.HRS.value, param=HRS_P)
    assert scale == pytest.approx(unc * value)   # percent scale == unc*value
    step = scale * lin
    up = sa.calculate_dstep(uc=unc, param=HRS_P, side=1, value=value)
    down = sa.calculate_dstep(uc=unc, param=HRS_P, side=-1, value=value)
    assert up == pytest.approx(value + step)
    assert down == pytest.approx(value - step)
    assert (up - value) == pytest.approx(value - down)


def test_sa_dispatch_and_missing_perturbator(monkeypatch) -> None:
    """The SA step dispatches through get_parameter_type and raises without a
    perturbator."""
    _mp_root = monkeypatch
    # -- test_sa_dispatch_uses_get_parameter_type: calculate_dstep routes
    #    through get_parameter_type: force ADDITIVE on an
    with _mp_root.context() as monkeypatch:
        value, unc, lin = 4.0, 1.5, 0.1
        pert = _make_pert({IF_P: unc}, {IF_P: value})
        sa = _make_sa(pert, lin_fact=lin)
        # Patch the symbol the module actually calls.
        monkeypatch.setattr(linear_mod, "get_parameter_type", lambda p: Ptype.WE)
        out = sa.calculate_dstep(uc=unc, param=IF_P, side=1, value=value)
        scale = pert.get_scale(ptype=Ptype.WE.value, param=IF_P)
        assert out == pytest.approx(value + scale * lin)   # linear, not value*f

    # -- test_sa_raises_without_perturbator: A None perturbator makes
    #    calculate_dstep raise for the linear branch.
    sa = Linear.__new__(Linear)
    sa.pert = None
    sa.lin_fact = 0.1
    with pytest.raises(RuntimeError):
        sa.calculate_dstep(uc=1.0, param=WE_P, side=1, value=1.0)


def test_nm_dstep_and_side_symmetry() -> None:
    """NM multiplicative steps use nm_dstep (not sensi_d) and are side-
    symmetric; additive and percent NM steps are symmetric with nm_dstep."""
    # -- test_nm_multiplicative_uses_nm_dstep_not_sensi_d: NM factor uses
    #    nm_dstep; side=+1 -> value*f.
    value, uc, step = 2.0, 1.2, 0.05
    pert = _make_pert({IF_P: uc}, {IF_P: value})
    nm = _make_nm(pert, nm_dstep=step)
    f = uc ** step
    assert nm.calculate_dstep(uc=uc, param=IF_P, side=1,
                              value=value) == pytest.approx(value * f)

    # -- test_nm_multiplicative_side_symmetry: side=-1 -> value/f, side=+1 ->
    #    value*f, up*down == value**2.
    value, uc, step = 7.0, 1.4, 0.1
    pert = _make_pert({MRC_P: uc}, {MRC_P: value})
    nm = _make_nm(pert, nm_dstep=step)
    f = uc ** step
    up = nm.calculate_dstep(uc=uc, param=MRC_P, side=1, value=value)
    down = nm.calculate_dstep(uc=uc, param=MRC_P, side=-1, value=value)
    assert up == pytest.approx(value * f)
    assert down == pytest.approx(value / f)
    assert up * down == pytest.approx(value ** 2)

    # -- test_nm_additive_percent_symmetric_with_nm_dstep: NM linear branch:
    #    value +/- get_scale*nm_dstep for we and hrs.
    step = 0.1
    # additive
    pert_a = _make_pert({WE_P: 2.0}, {WE_P: 100.0})
    nm_a = _make_nm(pert_a, nm_dstep=step)
    scale_a = pert_a.get_scale(ptype=Ptype.WE.value, param=WE_P)
    up_a = nm_a.calculate_dstep(uc=2.0, param=WE_P, side=1, value=100.0)
    down_a = nm_a.calculate_dstep(uc=2.0, param=WE_P, side=-1, value=100.0)
    assert up_a == pytest.approx(100.0 + scale_a * step)
    assert down_a == pytest.approx(100.0 - scale_a * step)
    # percent
    pert_p = _make_pert({HRS_P: 0.1}, {HRS_P: 800.0})
    nm_p = _make_nm(pert_p, nm_dstep=step)
    scale_p = pert_p.get_scale(ptype=Ptype.HRS.value, param=HRS_P)
    up_p = nm_p.calculate_dstep(uc=0.1, param=HRS_P, side=1, value=800.0)
    assert up_p == pytest.approx(800.0 + scale_p * step)
    assert (up_p - 800.0) == pytest.approx(scale_p * step)


def test_nm_initial_simplex_multiplicative_vertex_roundtrips() -> None:
    """get_initial_simplex integration: the perturbed multiplicative vertex,
    back-transformed through get_absolute, equals value*f (== calculate_dstep).
    """
    value, uc, step = 2.0, 1.1, 0.1
    pert = _make_pert(
        {IF_P: uc}, {IF_P: value},
        std_overrides={"max_std": 3, f"std_{Ptype.IF.value}": uc})
    nm = _make_nm(pert, nm_dstep=step)
    sop = SimpleNamespace(
        uncertainties={IF_P: uc},
        parameters_names={IF_P: value},
    )
    nm.f_mdl = SimpleNamespace(sop=sop)
    nm.last_vertice = sop
    nm.current_dimensions = [IF_P]

    simplex = nm.get_initial_simplex()
    assert simplex.shape == (2, 1)
    # Row 0 is the (normalized) initial vertex -> 0 in log space.
    assert simplex[0][0] == pytest.approx(0.0)
    # Row 1 is the perturbed vertex; back-transform must equal value*f.
    f = uc ** step
    recovered = nm.get_absolute(param=IF_P, value=simplex[1][0])
    assert recovered == pytest.approx(value * f)



# ===========================================================================
# NelderMead / NelderMeadInstance objective_function, get_options; Linear.run
# ===========================================================================
import kimeco.optimizers.NelderMead.nelder_mead as nm_mod  # noqa: E402
from kimeco.core import CoreRun  # noqa: E402
from kimeco.enums import ModelStatus  # noqa: E402
from kimeco.optimizers.NelderMead.nm_swarm_instance import (  # noqa: E402
    NelderMeadInstance)

_NM_KEYS = ('W__we', 'B__be', 'exp_000__score')


def _nm_from_db_row(sop_tpl, row):
    keys = list(sop_tpl.parameters_names.keys())
    return SimpleNamespace(parameters_names=dict(zip(keys, row)),
                           pres=[1.0], temp=[300.0])


class _NMLog:
    def __init__(self) -> None:
        self.debugs: list[str] = []

    def debug(self, msg, *a, **k) -> None:
        self.debugs.append(str(msg))

    def info(self, msg, *a, **k) -> None:
        return None

    error = warning = info


def _nm_vertex() -> SimpleNamespace:
    return SimpleNamespace(parameters_names=dict(zip(_NM_KEYS, (1.0, 2.0, 0.0))))


class _NMGen:
    built: list['_NMGen'] = []

    @classmethod
    def total(cls) -> int:
        return 7

    def __init__(self, models, **kw) -> None:
        self.models = models
        self.kw = kw
        _NMGen.built.append(self)

    def run(self) -> None:
        self.models[0].score = 42.0


def _bare_nm(monkeypatch, finished: bool, sop_row) -> tuple[Any, dict[str, list]]:
    monkeypatch.setattr(nm_mod.SOP, 'from_db_row', staticmethod(_nm_from_db_row))
    monkeypatch.setattr(nm_mod, 'Generation', _NMGen)
    nm = NelderMead.__new__(NelderMead)
    rec: dict[str, list] = {'rows': [], 'fscore': [], 'iters': [], 'stats': []}
    nm.current_dimensions = ['W__we']
    nm.last_vertice = _nm_vertex()
    nm.get_absolute = lambda param, value: 100.0 + value
    nm.prefix = 'NM'
    nm.f_mdl = SimpleNamespace(sop=_nm_vertex())
    nm.settings, nm.input_tpls = {}, []
    nm.kin_db = nm.sim_db = nm.pert = None
    nm.klog = _NMLog()
    nm.sf = SimpleNamespace(fscore=lambda mdl: rec['fscore'].append(mdl))
    nm.is_generation_finished = lambda gen_id: finished

    def _get_sop_row(table, id):
        rec['rows'].append((table, id))
        if isinstance(sop_row, Exception):
            raise sop_row
        return sop_row

    nm.sop_db = SimpleNamespace(get_sop_row=_get_sop_row)
    nm.print_stats = lambda params: rec['stats'].append(list(params))
    nm.update_iterations = lambda last_vertice: rec['iters'].append(last_vertice)
    return nm, rec


def test_nm_objective_function_reuses_db_vertex_or_runs_new(monkeypatch) -> None:
    scenarios = (
        ('not finished', False, [0, 0.0, 0.0, 0.0], False),
        ('same row', True, [0, 101.0, 2.0, 9.0], True),
        ('row differs', True, [0, 55.0, 2.0, 0.0], False),
        ('row missing', True, KeyError('no row'), False),
    )
    for label, finished, sop_row, reused in scenarios:
        _NMGen.built = []
        nm, rec = _bare_nm(monkeypatch, finished, sop_row)
        assert nm.objective_function(np.array([1.0])) == 42.0, label
        (gen,) = _NMGen.built
        vertex = gen.models[0]
        assert (vertex.id, vertex.gen) == (0, 7), label
        assert gen.kw['prefix'] == 'NM', label
        assert gen.kw['previous_el'] == {0: nm.f_mdl}, label
        assert rec['iters'] == [vertex] and rec['stats'] == [[101.0]], label
        assert rec['rows'] == ([('NM0007', 0)] if finished else []), label
        if reused:
            assert vertex.status == ModelStatus.DONE, label
            assert vertex.sop.parameters_names['exp_000__score'] == 9.0, label
            assert rec['fscore'] == [vertex], label
        else:
            assert vertex.status == ModelStatus.SOP, label
            assert vertex.sop is nm.last_vertice, label
            assert vertex.sop.parameters_names['W__we'] == 101.0, label
            assert rec['fscore'] == [], label
        assert (any('no row' in m for m in nm.klog.debugs)
                == (label == 'row missing')), label


def test_nm_instance_objective_function_counts_calls_per_instance(
        monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(nm_mod.SOP, 'from_db_row', staticmethod(_nm_from_db_row))
    inst = NelderMeadInstance.__new__(NelderMeadInstance)
    inst.nm_id, inst.gen_prefix, inst.gen_counter = 2, 'NMSG', 0
    inst.current_dimensions = ['W__we']
    inst.last_vertice = _nm_vertex()
    inst.get_absolute = lambda param, value: 100.0 + value
    inst.f_mdl = SimpleNamespace(sop=_nm_vertex())
    inst.klog = _NMLog()
    finished = iter([False, True, True, True])
    rows = iter([[2, 101.0, 2.0, 9.0], [2, 55.0, 2.0, 0.0], KeyError('gone')])
    rec: dict[str, list] = {'fin': [], 'rows': [], 'fscore': [], 'run': [], 'iters': []}

    def _is_finished(**kw):
        rec['fin'].append(kw)
        return next(finished)

    def _get_sop_row(table, id):
        rec['rows'].append((table, id))
        row = next(rows)
        if isinstance(row, Exception):
            raise row
        return row

    def _run(mdl):
        mdl.score = 10.0 + mdl.gen
        rec['run'].append(mdl)
        return mdl

    inst.dbqs = SimpleNamespace(is_vertice_finished=_is_finished)
    inst.sop_db = SimpleNamespace(get_sop_row=_get_sop_row)
    inst.sf = SimpleNamespace(fscore=lambda mdl: rec['fscore'].append(mdl))
    inst.shared_core = SimpleNamespace(run=_run)
    inst.update_iterations = lambda last_vertice: rec['iters'].append(last_vertice)

    scores = [inst.objective_function(np.array([1.0])) for _ in range(4)]
    assert scores == [10.0, 11.0, 12.0, 13.0]
    assert inst.gen_counter == 4
    assert rec['fin'] == [{'gen_id': k, 'mdl_id': 2, 'prefix': 'NMSG'} for k in range(4)]
    assert rec['rows'] == [('NMSG0001', 2), ('NMSG0002', 2), ('NMSG0003', 2)]
    assert [(m.id, m.gen) for m in rec['run']] == [(2, 0), (2, 1), (2, 2), (2, 3)]
    assert [m.status for m in rec['run']] == [
        ModelStatus.SOP, ModelStatus.DONE, ModelStatus.SOP, ModelStatus.SOP]
    assert rec['fscore'] == [rec['run'][1]]
    assert rec['iters'] == rec['run']
    assert any('gone' in m for m in inst.klog.debugs)


def test_nm_instance_get_options_reads_nm_maxiter() -> None:
    sentinel = object()
    inst = NelderMeadInstance.__new__(NelderMeadInstance)
    inst.klog = _NMLog()
    inst.get_initial_simplex = lambda: sentinel
    # Only the real key 'nm_maxiter' exists (no 'nm__maxiter').
    inst.settings = {'nm_fatol': 1e-3, 'nm_xatol': 2e-3, 'nm_maxiter': 7,
                     'nm_maxfev': 0, 'nm_adaptive': True}
    opts = inst.get_options()
    assert opts['maxiter'] == 7
    assert 'maxfev' not in opts
    assert opts['adaptive'] is True
    assert opts['initial_simplex'] is sentinel
    assert (opts['fatol'], opts['xatol']) == (1e-3, 2e-3)

    inst.settings = {'nm_fatol': 1e-3, 'nm_xatol': 2e-3, 'nm_maxiter': 0,
                     'nm_maxfev': 9, 'nm_adaptive': False}
    opts = inst.get_options()
    assert 'maxiter' not in opts and 'adaptive' not in opts
    assert opts['maxfev'] == 9


def test_linear_run_ranks_selects_and_writes_report(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(CoreRun, 'run', lambda self: None)
    monkeypatch.chdir(tmp_path)
    sa = Linear.__new__(Linear)
    sa.sop_tpl = SimpleNamespace(parameters_names={'p0': 1, 'p1': 1, 'p2': 1, 'p3': 1})
    sa.to_test = [True, False, True, True]
    exp_scores = [10.0, 12.0, 10.5, 16.0, 7.0, 11.5, 10.0]
    sa.models = [SimpleNamespace(experiment_score=s) for s in exp_scores]
    sa.settings = {'cumul_sensi': 0.7}
    sa.selected = []
    sa.name = 'SA0001'
    sa.run()
    assert sa.ps == ['p3', 'p0', 'p2']
    assert sa.rs == pytest.approx([6.0, 3.0, 1.5])
    assert sa.selected == ['p3', 'p0']
    lines = (tmp_path / 'SA0001.out').read_text().splitlines()
    assert lines[0].startswith('Parameters names:')
    assert len(lines) == 4
    assert lines[1].split()[:3] == ['p3', '0.57', '0.57']
    assert lines[3].split()[:2] == ['p2', '1.00']
