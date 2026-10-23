from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

import kimeco.gui.sopsection as sopsection_mod
from kimeco.gui.sopsection import SOPSection
from kimeco.parameters import SOP
from kimeco.well import Well
from kimeco.bimolecular import Bimolecular
from kimeco.barrier import Barrier
from kimeco.database.sop_db import SOP_DB
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Ptype
from kimeco.goat import GOATs


ROWS: dict[str, dict[int, dict[str, float]]] = {
    'G0000': {
        0: {'fact': 1.1, 'pw': 2.1, 's0': 0.5, 's1': 0.6},
        1: {'fact': 1.2, 'pw': 2.2, 's0': 0.7, 's1': 0.8},
        2: {'fact': 1.3, 'pw': 2.3, 's0': 0.11, 's1': 0.12},
    },
    'G0001': {
        5: {'fact': 1.5, 'pw': 2.5, 's0': 0.9, 's1': 0.10},
        6: {'fact': 1.6, 'pw': 2.6, 's0': 0.13, 's1': 0.14},
    },
}

GEN0: list[tuple[int, int]] = [(0, 0), (0, 1), (0, 2)]
GEN1: list[tuple[int, int]] = [(0, 1), (1, 5), (0, 0), (1, 6)]


class FakeHistogram:
    """Records constructor args so the plot path can be inspected."""

    instances: list["FakeHistogram"] = []

    def __init__(self,
                 data: dict[int, Any],
                 settings: dict[str, Any],
                 histfunc: str = "count") -> None:
        self.data = data
        self.settings = settings
        self.vlines: list[dict[str, Any]] = []
        FakeHistogram.instances.append(self)

    def add_vline(self, **kwargs: Any) -> None:
        self.vlines.append(kwargs)

    def layout(self) -> list["FakeHistogram"]:
        return [self]


@pytest.fixture(autouse=True)
def _reset_fake_histogram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeHistogram.instances = []
    monkeypatch.setattr(sopsection_mod, 'Histogram', FakeHistogram)


class FakeApp:
    """Captures Dash callbacks by function name at registration."""

    def __init__(self) -> None:
        self.captured: dict[str, Any] = {}

    def callback(self, *_args: Any, **_kwargs: Any) -> Any:
        def _decorator(fn: Any) -> Any:
            self.captured[fn.__name__] = fn
            return fn
        return _decorator


class SpyGoats:
    def __init__(self, per_gen: dict[int, dict[str, np.ndarray]]) -> None:
        self._per_gen = per_gen
        self.param_calls: list[tuple[int, list[str]]] = []
        self.goat_for_gen_calls = 0
        self.fscore_calls = 0

    def get_goat_param_values(
        self, gen: int, cols: list[str],
    ) -> dict[str, np.ndarray]:
        self.param_calls.append((gen, list(cols)))
        return {col: self._per_gen[gen][col] for col in cols}

    def get_goat_for_gen(self, gen: int) -> Any:
        self.goat_for_gen_calls += 1
        raise AssertionError('get_goat_for_gen must not run on the plot path')

    def fscore(self, mdl: Any) -> None:
        self.fscore_calls += 1
        raise AssertionError('fscore must not run on the plot path')


def _build_sop(n_exp: int = 2) -> SOP:
    sop = SOP(n_exp=n_exp)
    sop.factor = 1.0
    sop.power = 1.0
    sop.pres_unit = 'atm'
    sop.pres = [1.0]
    sop.temp = [300.0]
    sop.add_new_well(name='LEFT', pes_id=0)
    sop.add_new_well(name='RIGHT', pes_id=1)
    sop.add_new_bimol(name='LEFT+H', pes_id=0)
    left_h = cast(Bimolecular, sop.items['LEFT+H'])
    left_h.add_new_frag(name='LEFT_FRAG')
    sop.items['LEFT_FRAG'] = left_h.fragments[-1]
    sop.add_new_barrier(
        name='TS_LEFT_RIGHT', lside='LEFT', rside='RIGHT', pes_id=1)
    for well_name in ('LEFT', 'RIGHT', 'LEFT_FRAG'):
        cast(Well, sop.items[well_name])._freq = np.array([])
    ts = cast(Barrier, sop.items['TS_LEFT_RIGHT'])
    ts._freq = np.array([])
    ts._energy = 0.0
    ts.ifreq = 0.0
    return sop


def _row_values(sop: SOP, spec: dict[str, float]) -> dict[str, Any]:
    values = dict(sop.parameters_names)
    values['__fact'] = spec['fact']
    values['__pow'] = spec['pw']
    values['exp_000__score'] = spec['s0']
    values['exp_001__score'] = spec['s1']
    return values


def _make_db(tmp_path: Path, sop: SOP) -> SOP_DB:
    db = SOP_DB(sop=sop, name='TEST_SOP', path=str(tmp_path))
    for table, rows in ROWS.items():
        db.create_new_table(name=table)
        for row_id, spec in rows.items():
            db.prepare_batch_upsert(
                table=table, id=row_id, values=_row_values(sop, spec))
    db.batch_upsert()
    return db


def _make_real_goats(tmp_path: Path,
                     db: SOP_DB,
                     generations: list[list[tuple[int, int]]]) -> GOATs:
    goats = GOATs(
        sop_db=db,
        kin_db=cast(Any, SimpleNamespace()),
        sim_db=cast(Any, SimpleNamespace()),
        sf=cast(Any, SimpleNamespace()),
        wdir=str(tmp_path),
        overwrite=False,
    )
    goats.generations = generations
    goats.prefix = 'G'
    return goats


def _make_section(columns: list[str], goats: Any) -> SOPSection:
    """Build a SOPSection without running __init__ and inject collaborators."""
    sec = SOPSection.__new__(SOPSection)
    sec.app = cast(Any, FakeApp())
    sec.sop_db = cast(Any, SimpleNamespace(columns=list(columns)))
    # init_vals is 1-indexed against columns (index 0 is reserved for id).
    init_vals = [0.0] + [0.0] * len(columns)
    sec.gapp = cast(Any, SimpleNamespace(goats=goats, init_vals=init_vals))
    # Boundaries and plot options are unchanged by the feature; stub them so
    # the test focuses on the data-fetch/plot wiring.
    sec.get_boundaries = cast(Any, lambda col: [0.0, 0.0])
    sec.get_plot_options = cast(Any, lambda col, ptypes: {
        'title': col, 'tickformat': '.2f', 'unit': ''})
    return sec


def _capture_update_sop_figure(sec: SOPSection) -> Any:
    sec.register_callbacks()
    return cast(Any, sec.app).captured['update_sop_figure']


def test_plot_fetch_path() -> None:
    """update_sop_figure fetches once per generation (single-column path too);
    make_figure hands a generation-keyed dict to the histogram; the plot path
    never calls get_goat_for_gen or fscore."""
    # -- test_update_sop_figure_fetches_once_per_generation
    FakeHistogram.instances = []
    columns = ['__fact', '__pow', 'exp_000__score']
    per_gen = {
        0: {c: np.array([1.0, 2.0]) for c in columns},
        1: {c: np.array([3.0, 4.0]) for c in columns},
    }
    goats = SpyGoats(per_gen)
    sec = _make_section(columns, goats=goats)
    update_sop_figure = _capture_update_sop_figure(sec)

    style, children = update_sop_figure(1, ['fact'], columns, [0, 1])

    assert style == {'display': 'block'}
    # One fetch per generation with the full column list (not per column).
    assert goats.param_calls == [(0, columns), (1, columns)]
    # One figure produced per requested column.
    assert len(FakeHistogram.instances) == len(columns)
    assert len(children) == len(columns)

    # -- test_update_sop_figure_single_column_path
    FakeHistogram.instances = []
    columns = ['__fact', '__pow']
    per_gen = {0: {c: np.array([1.0, 2.0]) for c in columns}}
    goats = SpyGoats(per_gen)
    sec = _make_section(columns, goats=goats)
    update_sop_figure = _capture_update_sop_figure(sec)

    _style, children = update_sop_figure(1, ['fact'], ['__fact'], [0])

    assert goats.param_calls == [(0, ['__fact'])]
    assert len(FakeHistogram.instances) == 1
    assert len(children) == 1

    # -- test_make_figure_passes_gen_keyed_dict_to_histogram
    FakeHistogram.instances = []
    columns = ['__fact', '__pow', 'exp_000__score']
    sec = _make_section(columns, goats=SimpleNamespace())

    per_gen_values = {
        0: {'__fact': np.array([1.1, 1.2])},
        1: {'__fact': np.array([1.5, 1.6])},
    }
    children = sec.make_figure(
        boundaries=[0.0, 0.0],
        plot_settings={'title': '__fact', 'tickformat': '.2f', 'unit': ''},
        col='__fact',
        per_gen_values=per_gen_values,
    )

    assert len(FakeHistogram.instances) == 1
    hist = FakeHistogram.instances[0]
    assert set(hist.data.keys()) == {0, 1}
    assert all(isinstance(k, int) for k in hist.data)
    assert np.array_equal(hist.data[0], np.array([1.1, 1.2]))
    assert np.array_equal(hist.data[1], np.array([1.5, 1.6]))
    # make_figure returns the histogram layout list.
    assert children == [hist]

    # -- test_plot_path_does_not_call_get_goat_for_gen_or_fscore
    FakeHistogram.instances = []
    columns = ['__fact']
    per_gen = {0: {'__fact': np.array([1.0, 2.0])}}
    goats = SpyGoats(per_gen)
    sec = _make_section(columns, goats=goats)
    update_sop_figure = _capture_update_sop_figure(sec)

    update_sop_figure(1, ['fact'], ['__fact'], [0])

    assert goats.goat_for_gen_calls == 0
    assert goats.fscore_calls == 0


def test_histogram_data_shape_and_persisted_scores(tmp_path) -> None:
    """Histogram data keys are ints and values are sequences; score values are
    byte-identical to the persisted scores."""
    _tmp_root = tmp_path
    # -- test_histogram_data_keys_are_int_and_values_are_sequences
    FakeHistogram.instances = []
    columns = ['__fact']
    per_gen = {
        0: {'__fact': np.array([1.0, 2.0, 3.0])},
        2: {'__fact': np.array([4.0, 5.0])},
    }
    goats = SpyGoats(per_gen)
    sec = _make_section(columns, goats=goats)
    update_sop_figure = _capture_update_sop_figure(sec)

    update_sop_figure(1, ['fact'], ['__fact'], [0, 2])

    hist = FakeHistogram.instances[0]
    assert set(hist.data.keys()) == {0, 2}
    assert all(isinstance(k, int) for k in hist.data)
    for values in hist.data.values():
        assert len(values) >= 1

    # -- test_score_values_are_byte_identical_to_persisted_scores
    tmp_path = _tmp_root / 'test_score_values_are_byte_identical_to_persisted_scores'
    tmp_path.mkdir(parents=True)
    FakeHistogram.instances = []
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _make_real_goats(tmp_path, db, [GEN1])

    sec = _make_section(db.columns, goats=goats)
    update_sop_figure = _capture_update_sop_figure(sec)

    col = 'exp_000__score'
    update_sop_figure(1, ['score'], [col], [0])

    expected = np.array([ROWS[f'G{g:04d}'][m]['s0'] for (g, m) in GEN1])
    hist = FakeHistogram.instances[0]
    plotted = hist.data[0]
    assert np.array_equal(plotted, expected)
    assert plotted.tobytes() == expected.tobytes()


# ---------------------------------------------------------------------------
# Regression tests for SOPSection.get_boundaries (the Score-plot crash fix).
#
# Before the fix, get_boundaries delegated *every* column to
# Perturbator.get_boundaries, which raises NotImplementedError('Parameter not
# parametrised.') for Ptype.SCORE ('score') because SCORE is a computed output
# absent from the ADDITIVE/PERCENT/MULTIPLICATIVE classes. Plotting the
# "Score" parameter therefore crashed. The fix returns [init_val, init_val]
# for the score path and never touches the perturbator.
# ---------------------------------------------------------------------------

SCORE_COL = f'exp_000{dbs}score'   # e.g. "exp_000__score"
WE_COL = f'LEFT{dbs}we'            # a perturbed well-energy column


class SpyPert:
    """Fake perturbator recording get_boundaries calls.

    When ``raise_not_impl`` is set it mimics the real Perturbator, which raises
    NotImplementedError for unparametrised (e.g. score) columns. This lets a
    test prove the score path never reaches the perturbator.
    """

    def __init__(self,
                 result: tuple[float, float] = (10.0, 20.0),
                 raise_not_impl: bool = False) -> None:
        self.result = result
        self.raise_not_impl = raise_not_impl
        self.calls: list[dict[str, Any]] = []

    def get_boundaries(self, ptype: str, i_val: float,
                       param: str | None = None) -> tuple[float, float]:
        self.calls.append({'ptype': ptype, 'i_val': i_val, 'param': param})
        if self.raise_not_impl:
            raise NotImplementedError('Parameter not parametrised.')
        return self.result


def _make_boundaries_section(columns: list[str],
                             init_vals: list[float],
                             pert: Any) -> SOPSection:
    """Build a SOPSection using the *real* get_boundaries (not stubbed)."""
    sec = SOPSection.__new__(SOPSection)
    sec.sop_db = cast(Any, SimpleNamespace(columns=list(columns)))
    sec.gapp = cast(Any, SimpleNamespace(init_vals=list(init_vals)))
    sec.pert = cast(Any, pert)
    return sec


def test_get_boundaries() -> None:
    """A score column returns degenerate bounds without asking the perturbator
    (whatever the param); a perturbed column delegates with the full column key
    as param, so a specific std override shows."""
    # -- test_get_boundaries_score_returns_degenerate_and_skips_pert
    FakeHistogram.instances = []
    columns = [WE_COL, SCORE_COL]
    # init_vals is 1-indexed (index 0 is the id column); pick a distinct known
    # score init value so [init_val, init_val] is unambiguous.
    init_vals = [999.0, 111.0, 222.0]
    pert = SpyPert(raise_not_impl=True)
    sec = _make_boundaries_section(columns, init_vals, pert)

    bounds = sec.get_boundaries(SCORE_COL)

    # Degenerate boundary (lb == ub) equal to the score's init value, and the
    # perturbator (which would raise) is never consulted.
    assert bounds == [0.0, 222.0]
    assert pert.calls == []

    # -- test_get_boundaries_perturbed_column_still_delegates
    FakeHistogram.instances = []
    columns = [WE_COL, SCORE_COL]
    init_vals = [999.0, 111.0, 222.0]
    pert = SpyPert(result=(100.0, 122.0))
    sec = _make_boundaries_section(columns, init_vals, pert)

    bounds = sec.get_boundaries(WE_COL)

    # Non-score behaviour is unchanged: delegated to the perturbator with the
    # right ptype/init value, and the tuple is passed through as a list. The
    # full column name is forwarded as ``param`` for per-parameter uncertainty.
    assert pert.calls == [
        {'ptype': Ptype.WE.value, 'i_val': 111.0, 'param': WE_COL}]
    assert bounds == [100.0, 122.0]
    assert isinstance(bounds, list)

    # -- test_get_boundaries_forwards_full_col_key_as_param
    FakeHistogram.instances = []
    columns = [WE_COL, SCORE_COL]
    init_vals = [999.0, 111.0, 222.0]
    pert = SpyPert(result=(100.0, 122.0))
    sec = _make_boundaries_section(columns, init_vals, pert)

    sec.get_boundaries(WE_COL)

    # param must be the FULL column key (e.g. "LEFT__we"), not the split short
    # ptype token ("we"); the perturbator keys i_sop.uncertainties by full name.
    assert len(pert.calls) == 1
    assert pert.calls[0]['param'] == WE_COL
    assert pert.calls[0]['param'] != Ptype.WE.value

    # -- test_get_boundaries_score_path_unaffected_by_param
    FakeHistogram.instances = []
    columns = [WE_COL, SCORE_COL]
    init_vals = [999.0, 111.0, 222.0]
    pert = SpyPert(raise_not_impl=True)
    sec = _make_boundaries_section(columns, init_vals, pert)

    bounds = sec.get_boundaries(SCORE_COL)

    # Score short-circuits before any perturbator call, so param forwarding is
    # irrelevant and the raising perturbator is never consulted.
    assert bounds == [0.0, 222.0]
    assert pert.calls == []

    # -- test_get_boundaries_reflects_specific_std_override
    FakeHistogram.instances = []
    # Real Perturbator so the param-specific uncertainty flows end to end.
    from kimeco.Perturbators.perturbator import Perturbator

    columns = [WE_COL]
    init_vals = [0.0, 100.0]  # WE_COL init value = init_vals[0 + 1] = 100.0.
    settings = {'active_p': [], 'max_std': 3, f'std_{Ptype.WE.value}': 1.0}
    klog = SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        debug=lambda *a, **k: None)
    pert = Perturbator(settings, SimpleNamespace(), klog)
    pert.i_sop = cast(Any, SimpleNamespace(
        uncertainties={WE_COL: 5.0}, parameters_names={WE_COL: 100.0}))

    sec = _make_boundaries_section(columns, init_vals, pert)
    bounds = sec.get_boundaries(WE_COL)

    # Override (5.0) widens the band vs the global std (1.0): 100 +/- 5*3.
    assert bounds == pytest.approx([100.0 - 15.0, 100.0 + 15.0])
    # And it is strictly wider than the global-std band (100 +/- 1*3).
    global_band = pert.get_boundaries(ptype=Ptype.WE.value, i_val=100.0)
    assert (bounds[1] - bounds[0]) > (global_band[1] - global_band[0])


def test_boundary_vlines() -> None:
    """Over a score column no brown boundary vlines are drawn; a non-score
    column draws them, except with degenerate bounds (black only)."""
    # -- test_make_figure_over_score_skips_brown_boundary_vlines
    FakeHistogram.instances = []
    columns = [SCORE_COL]
    init_vals = [0.0, 55.0]
    pert = SpyPert(raise_not_impl=True)
    sec = _make_boundaries_section(columns, init_vals, pert)

    # End-to-end: real get_boundaries feeds real make_figure. Plotting Score
    # must not raise and must skip the brown boundary vlines (lb == ub).
    boundaries = sec.get_boundaries(SCORE_COL)
    children = sec.make_figure(
        boundaries=boundaries,
        plot_settings={'title': SCORE_COL, 'tickformat': '.2f', 'unit': ''},
        col=SCORE_COL,
        per_gen_values={0: {SCORE_COL: np.array([0.5, 0.6])}},
    )

    assert boundaries == [0.0, 55.0]
    assert pert.calls == []
    hist = FakeHistogram.instances[0]
    assert children == [hist]
    colors = [vl.get('line_color') for vl in hist.vlines]
    # Only the black init-value line; no brown boundary lines.
    assert colors == ['black']
    assert 'brown' not in colors

    # -- test_make_figure_non_score_still_draws_brown_boundary_vlines
    FakeHistogram.instances = []
    columns = [WE_COL, SCORE_COL]
    # WE_COL is at columns index 0, so its init value is init_vals[0 + 1].
    init_vals = [999.0, 111.0, 222.0]
    pert = SpyPert(result=(100.0, 122.0))
    sec = _make_boundaries_section(columns, init_vals, pert)

    # Regression guard: the score fix must NOT suppress brown boundary vlines
    # on the normal perturbed path when lb != ub.
    children = sec.make_figure(
        boundaries=[100.0, 122.0],
        plot_settings={'title': WE_COL, 'tickformat': '.2f', 'unit': ''},
        col=WE_COL,
        per_gen_values={0: {WE_COL: np.array([100.5, 121.5])}},
    )

    hist = FakeHistogram.instances[0]
    assert children == [hist]
    colors = [vl.get('line_color') for vl in hist.vlines]
    # Order preserved: black init line first, then the two brown boundaries.
    assert colors == ['black', 'brown', 'brown']
    assert 'brown' in colors

    black_x = [vl['x'] for vl in hist.vlines
               if vl.get('line_color') == 'black']
    brown_x = {vl['x'] for vl in hist.vlines
               if vl.get('line_color') == 'brown'}
    # Black line sits at WE_COL's init value (init_vals[idx + 1] = 111.0).
    assert black_x == [111.0]
    assert brown_x == {100.0, 122.0}

    # -- test_make_figure_non_score_degenerate_bounds_only_black
    FakeHistogram.instances = []
    columns = [WE_COL, SCORE_COL]
    init_vals = [999.0, 111.0, 222.0]
    pert = SpyPert(result=(7.0, 7.0))
    sec = _make_boundaries_section(columns, init_vals, pert)

    # lb == ub on a non-score column: the untouched degenerate-bounds gate
    # still suppresses the brown vlines, leaving only the black init line.
    children = sec.make_figure(
        boundaries=[7.0, 7.0],
        plot_settings={'title': WE_COL, 'tickformat': '.2f', 'unit': ''},
        col=WE_COL,
        per_gen_values={0: {WE_COL: np.array([6.9, 7.1])}},
    )

    hist = FakeHistogram.instances[0]
    assert children == [hist]
    colors = [vl.get('line_color') for vl in hist.vlines]
    assert colors == ['black']
    assert 'brown' not in colors




# ===========================================================================
# get_plot_options (titles, formats, units; barrier sides for 'if')
# ===========================================================================
def _plot_options_section() -> SOPSection:
    w1, w2 = Well('W1', [0]), Well('W2', [0])
    ab = Bimolecular('A+B', [0])
    ab.set_fragments([Well('A', []), Well('B', [])])
    unknown = SimpleNamespace(name='X')
    items = {
        'W1': w1, 'W2': w2, 'A+B': ab,
        'TS_WW': Barrier('TS_WW', w1, w2, 0),
        'TS_WB': Barrier('TS_WB', w1, ab, 0),
        'TS_BW': Barrier('TS_BW', ab, w1, 0),
        'TS_UR': Barrier('TS_UR', cast(Any, unknown), w1, 0),
        'TS_UP': Barrier('TS_UP', w1, cast(Any, unknown), 0),
    }
    gapp = SimpleNamespace(settings={}, app=FakeApp(), sop_db=None, kin_db=None,
                           sim_db=None, init_SOP=SimpleNamespace(items=items),
                           species=[], pert=None)
    return SOPSection(gapp=gapp)


def test_get_plot_options_titles_formats_and_units() -> None:
    sec = _plot_options_section()
    opts = sec.get_plot_options('W1__we', [Ptype.WE.value])
    assert opts == {'title': 'Energy of W1 (kcal mol<sup>-1</sup>)', 'tickformat': '.2f',
                    'unit': ' (kcal mol⁻¹)'}
    assert sec.get_plot_options('__sigma0', [])['title'] == '__sigma0'
    assert sec.get_plot_options('W1__freq01', [])['title'] == (
        'Individual freq perturbation of W1__freq01 for W1')
    opts = sec.get_plot_options('__pow', [])
    assert (opts['title'], opts['unit']) == ('Energy transfer power', '')


def test_get_plot_options_imaginary_frequency_sides() -> None:
    sec = _plot_options_section()
    title = 'Imaginary frequency of {} (cm<sup>-1</sup>)'
    assert sec.get_plot_options('TS_WW__if', [])['title'] == title.format('W1 to W2')
    assert sec.get_plot_options('TS_WB__if', [])['title'] == title.format('W1 to A + B')
    assert sec.get_plot_options('TS_BW__if', [])['title'] == title.format('A + B to W1')
    for col in ('TS_UR__if', 'TS_UP__if'):
        with pytest.raises(NotImplementedError, match='Unknown reactant object'):
            sec.get_plot_options(col, [])
    with pytest.raises(TypeError, match='Expected Barrier'):
        sec.get_plot_options('W1__if', [])
