"""CI-safe tests for ``GOATs`` reads from a real SOP_DB on ``tmp_path``
(two generations, multi-origin tokens): ``get_goat_for_gen`` (models with
ids, generation and scores), ``get_p_for_gen`` and ``batch_select_cols``
(parameter columns in token order), and ``param_values`` (legacy parity,
never calling ``fscore`` nor rebuilding SOPs).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.database.sop_db import SOP_DB
from kimeco.goat import GOATs
from kimeco.model import Model
from kimeco.parameters import SOP
from kimeco.scoring_f.scoring import Scoring
from kimeco.well import Well


# ===========================================================================
# get_goat_for_gen
# ===========================================================================
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


def _gg_make_goats(tmp_path: Path,
                db: SOP_DB,
                generations: list[list[tuple[int, int]]],
                sf: Any) -> GOATs:
    goats = GOATs(
        sop_db=db,
        kin_db=cast(Any, SimpleNamespace()),
        sim_db=cast(Any, SimpleNamespace()),
        sf=cast(Any, sf),
        wdir=str(tmp_path),
        overwrite=False,
    )
    goats.generations = generations
    goats.prefix = 'G'
    return goats


def _gg_expected(tokens: list[tuple[int, int]], key: str) -> np.ndarray:
    return np.array([ROWS[f'G{g:04d}'][m][key] for (g, m) in tokens])


def _install_fscore_spy(monkeypatch: pytest.MonkeyPatch) -> list[Model]:
    """Replace Scoring.fscore with a spy that deterministically scores."""
    seen: list[Model] = []

    def _spy(self: Scoring, mdl: Model) -> None:
        mdl.score = 1000 + mdl.id
        seen.append(mdl)

    monkeypatch.setattr(Scoring, 'fscore', _spy)
    return seen


def _scoring(sop: SOP) -> Scoring:
    return Scoring(settings={"fix_theory_divider": False}, initial_SOP=sop)


def test_get_goat_for_gen_returns_models_with_ids_gen_and_scores(tmp_path, monkeypatch) -> None:
    """Models come back with their ids, generation and fscore scores, matching
    the golden multi-origin selection."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_get_goat_for_gen_returns_models_with_ids_gen_and_scores
    tmp_path = _tmp_root / 'test_get_goat_for_gen_returns_models_with_ids_gen_and_scores'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        sop = _build_sop()
        db = _make_db(tmp_path, sop)
        seen = _install_fscore_spy(monkeypatch)
        goats = _gg_make_goats(tmp_path, db, [GEN1], _scoring(sop))

        models = goats.get_goat_for_gen(0)

        assert isinstance(models, list)
        assert all(isinstance(mdl, Model) for mdl in models)
        assert [(mdl.gen, mdl.id) for mdl in models] == GEN1
        assert [mdl.score for mdl in models] == [1000 + m for (_, m) in GEN1]
        # fscore called exactly once per returned model.
        assert len(seen) == len(GEN1)

    # -- test_get_goat_for_gen_golden_parity_multi_origin
    tmp_path = _tmp_root / 'test_get_goat_for_gen_golden_parity_multi_origin'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        sop = _build_sop()
        db = _make_db(tmp_path, sop)
        _install_fscore_spy(monkeypatch)
        goats = _gg_make_goats(tmp_path, db, [GEN1], _scoring(sop))

        models = goats.get_goat_for_gen(0)

        reconstructed = np.array(
            [mdl.sop.parameters_names['__fact'] for mdl in models])
        assert np.array_equal(reconstructed, _gg_expected(GEN1, 'fact'))


def test_get_goat_for_gen_minus_one_returns_last_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    _install_fscore_spy(monkeypatch)
    goats = _gg_make_goats(tmp_path, db, [GEN0, GEN1], _scoring(sop))

    last = goats.get_goat_for_gen(-1)
    explicit = goats.get_goat_for_gen(1)

    assert [(m.gen, m.id) for m in last] == [(m.gen, m.id) for m in explicit]
    assert [(m.gen, m.id) for m in last] == GEN1


def test_get_goat_for_gen_errors(tmp_path, monkeypatch) -> None:
    """An out-of-range generation raises IndexError; a missing id raises
    ValueError with the exact message."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_get_goat_for_gen_out_of_range_raises_indexerror
    tmp_path = _tmp_root / 'test_get_goat_for_gen_out_of_range_raises_indexerror'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        sop = _build_sop()
        db = _make_db(tmp_path, sop)
        _install_fscore_spy(monkeypatch)
        goats = _gg_make_goats(tmp_path, db, [GEN0], _scoring(sop))

        with pytest.raises(IndexError, match='Generation number out of range'):
            goats.get_goat_for_gen(5)

    # -- test_get_goat_for_gen_missing_id_raises_valueerror_exact_message
    tmp_path = _tmp_root / 'test_get_goat_for_gen_missing_id_raises_valueerror_exact_message'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        sop = _build_sop()
        db = _make_db(tmp_path, sop)
        _install_fscore_spy(monkeypatch)
        # Token references id 99 that does not exist in G0000.
        goats = _gg_make_goats(tmp_path, db, [[(0, 99)]], _scoring(sop))

        expected = (
            'Expected exactly one row for id 99 in table G0000, found 0'
        )
        with pytest.raises(ValueError) as exc:
            goats.get_goat_for_gen(0)
        assert str(exc.value) == expected


# ===========================================================================
# get_p_for_gen and batch_select_cols
# ===========================================================================
def _gp_make_goats(tmp_path: Path,
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


def _gp_expected(tokens: list[tuple[int, int]], key: str) -> list[float]:
    return [ROWS[f'G{g:04d}'][m][key] for (g, m) in tokens]


def test_get_p_for_gen_shape_values_and_token_order(tmp_path) -> None:
    """get_p_for_gen returns the expected shape and values in token order, for
    one or several parameters, multi-origin tokens included, matching the golden
    I/O."""
    _tmp_root = tmp_path
    # -- test_get_p_for_gen_shape_values_and_token_order
    tmp_path = _tmp_root / 'test_get_p_for_gen_shape_values_and_token_order'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _gp_make_goats(tmp_path, db, [GEN1])

    params = ['__fact', '__pow']
    result = goats.get_p_for_gen(params, 0)

    assert result.shape == (len(GEN1), len(params))
    assert np.array_equal(result[:, 0], np.array(_gp_expected(GEN1, 'fact')))
    assert np.array_equal(result[:, 1], np.array(_gp_expected(GEN1, 'pw')))

    # -- test_get_p_for_gen_single_param
    tmp_path = _tmp_root / 'test_get_p_for_gen_single_param'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _gp_make_goats(tmp_path, db, [GEN0])

    result = goats.get_p_for_gen(['__fact'], 0)

    assert result.shape == (len(GEN0), 1)
    assert np.array_equal(result[:, 0], np.array(_gp_expected(GEN0, 'fact')))

    # -- test_get_p_for_gen_multi_origin_token_order
    tmp_path = _tmp_root / 'test_get_p_for_gen_multi_origin_token_order'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _gp_make_goats(tmp_path, db, [GEN1])

    result = goats.get_p_for_gen(['exp_000__score'], 0)

    assert np.array_equal(result[:, 0], np.array(_gp_expected(GEN1, 's0')))

    # -- test_get_p_for_gen_io_parity_golden
    tmp_path = _tmp_root / 'test_get_p_for_gen_io_parity_golden'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _gp_make_goats(tmp_path, db, [GEN1])

    params = ['__fact', '__pow', 'exp_000__score']
    result = goats.get_p_for_gen(params, 0)

    golden = np.array([
        [ROWS[f'G{g:04d}'][m]['fact'],
         ROWS[f'G{g:04d}'][m]['pw'],
         ROWS[f'G{g:04d}'][m]['s0']]
        for (g, m) in GEN1
    ])
    assert np.array_equal(result, golden)


def test_batch_select_cols_is_id_keyed_and_clears_select(
    tmp_path: Path,
) -> None:
    sop = _build_sop()
    db = _make_db(tmp_path, sop)

    db.prepare_batch_select(table='G0000', row_id=0)
    db.prepare_batch_select(table='G0000', row_id=1)
    db.prepare_batch_select(table='G0001', row_id=5)

    raw = db.batch_select_cols(cols=['__fact', 'exp_000__score'])

    assert set(raw.keys()) == {'G0000', 'G0001'}
    assert set(raw['G0000'].keys()) == {0, 1}
    assert set(raw['G0001'].keys()) == {5}
    # Each tuple carries only the requested columns in request order; the id
    # is carried as the dict key, not inside the tuple.
    assert raw['G0000'][0] == (1.1, 0.5)
    assert raw['G0000'][1] == (1.2, 0.7)
    assert raw['G0001'][5] == (1.5, 0.9)
    assert all(len(vals) == 2 for table in raw.values()
               for vals in table.values())
    # _select is cleared after execution.
    assert db._select == {}


# ===========================================================================
# param_values
# ===========================================================================
class _SpyScoring:
    """Minimal stand-in for Scoring that counts fscore invocations."""

    def __init__(self) -> None:
        self.calls = 0

    def fscore(self, mdl: Any) -> None:
        self.calls += 1
        mdl.score = 1000 + mdl.id


def _pv_make_goats(tmp_path: Path,
                db: SOP_DB,
                generations: list[list[tuple[int, int]]],
                sf: Any) -> GOATs:
    goats = GOATs(
        sop_db=db,
        kin_db=cast(Any, SimpleNamespace()),
        sim_db=cast(Any, SimpleNamespace()),
        sf=cast(Any, sf),
        wdir=str(tmp_path),
        overwrite=False,
    )
    goats.generations = generations
    goats.prefix = 'G'
    return goats


def _pv_expected(tokens: list[tuple[int, int]], key: str) -> np.ndarray:
    return np.array([
        ROWS[f'G{g:04d}'][m][key] for (g, m) in tokens
    ])


def test_param_values_match_legacy(tmp_path) -> None:
    """param_values matches the legacy result for one or several columns, multi-
    origin token order and the score column; gen -1 is the last generation; the
    result is a float ndarray of the expected length."""
    _tmp_root = tmp_path
    # -- test_param_values_match_legacy_single_and_multiple_cols
    tmp_path = _tmp_root / 'test_param_values_match_legacy_single_and_multiple_cols'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    sf = _SpyScoring()
    goats = _pv_make_goats(tmp_path, db, [GEN0], sf)

    single = goats.get_goat_param_values(0, ['__fact'])
    legacy = goats.get_goat_for_gen(0)
    assert np.array_equal(
        single['__fact'],
        np.array([mdl.sop.parameters_names['__fact'] for mdl in legacy]),
    )

    multi = goats.get_goat_param_values(0, ['__fact', '__pow'])
    legacy = goats.get_goat_for_gen(0)
    for col in ('__fact', '__pow'):
        assert np.array_equal(
            multi[col],
            np.array([mdl.sop.parameters_names[col] for mdl in legacy]),
        )

    # -- test_param_values_multi_origin_preserves_token_order
    tmp_path = _tmp_root / 'test_param_values_multi_origin_preserves_token_order'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _pv_make_goats(tmp_path, db, [GEN1], _SpyScoring())

    values = goats.get_goat_param_values(0, ['__fact', '__pow'])

    assert np.array_equal(values['__fact'], _pv_expected(GEN1, 'fact'))
    assert np.array_equal(values['__pow'], _pv_expected(GEN1, 'pw'))

    # -- test_param_values_score_column_parity
    tmp_path = _tmp_root / 'test_param_values_score_column_parity'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _pv_make_goats(tmp_path, db, [GEN1], _SpyScoring())

    values = goats.get_goat_param_values(0, ['exp_000__score'])
    legacy = goats.get_goat_for_gen(0)

    assert np.array_equal(values['exp_000__score'], _pv_expected(GEN1, 's0'))
    assert np.array_equal(
        values['exp_000__score'],
        np.array(
            [mdl.sop.parameters_names['exp_000__score'] for mdl in legacy]),
    )

    # -- test_param_values_gen_minus_one_returns_last_generation
    tmp_path = _tmp_root / 'test_param_values_gen_minus_one_returns_last_generation'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _pv_make_goats(tmp_path, db, [GEN0, GEN1], _SpyScoring())

    last = goats.get_goat_param_values(-1, ['__fact'])
    explicit = goats.get_goat_param_values(1, ['__fact'])

    assert np.array_equal(last['__fact'], explicit['__fact'])
    assert np.array_equal(last['__fact'], _pv_expected(GEN1, 'fact'))

    # -- test_param_values_returns_float_ndarray_with_expected_length
    tmp_path = _tmp_root / 'test_param_values_returns_float_ndarray_with_expected_length'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    goats = _pv_make_goats(tmp_path, db, [GEN1], _SpyScoring())

    values = goats.get_goat_param_values(0, ['__fact'])

    arr = values['__fact']
    assert isinstance(arr, np.ndarray)
    assert np.issubdtype(arr.dtype, np.floating)
    assert len(arr) == len(GEN1)


def test_param_values_never_calls_fscore_nor_rebuilds_sops(tmp_path, monkeypatch) -> None:
    """param_values never calls fscore and bypasses SOP reconstruction."""
    _tmp_root = tmp_path
    _mp_root = monkeypatch
    # -- test_param_values_never_calls_fscore
    tmp_path = _tmp_root / 'test_param_values_never_calls_fscore'
    tmp_path.mkdir(parents=True)
    sop = _build_sop()
    db = _make_db(tmp_path, sop)
    sf = _SpyScoring()
    goats = _pv_make_goats(tmp_path, db, [GEN1], sf)

    goats.get_goat_param_values(0, ['__fact', '__pow'])

    assert sf.calls == 0

    # -- test_param_values_bypasses_sop_reconstruction
    tmp_path = _tmp_root / 'test_param_values_bypasses_sop_reconstruction'
    tmp_path.mkdir(parents=True)
    with _mp_root.context() as monkeypatch:
        sop = _build_sop()
        db = _make_db(tmp_path, sop)
        goats = _pv_make_goats(tmp_path, db, [GEN1], _SpyScoring())

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError('from_db_row must not be called')

        monkeypatch.setattr(SOP, 'from_db_row', staticmethod(_boom))

        values = goats.get_goat_param_values(0, ['__fact'])

        assert np.array_equal(values['__fact'], _pv_expected(GEN1, 'fact'))




# ===========================================================================
# update_with_generation / get_rate_coefficients
# ===========================================================================
def _plain_goats(tmp_path: Path, **kw: Any) -> GOATs:
    return GOATs(sop_db=cast(Any, SimpleNamespace()),
                 kin_db=cast(Any, kw.get('kin_db', SimpleNamespace())),
                 sim_db=cast(Any, SimpleNamespace()),
                 sf=cast(Any, SimpleNamespace()),
                 wdir=str(tmp_path), overwrite=True)


def test_update_with_generation_keeps_best_and_rewrites_files(tmp_path) -> None:
    goats = _plain_goats(tmp_path)

    def _mdls(gen: int, scores: dict[int, float]) -> list[Any]:
        return [SimpleNamespace(gen=gen, id=i, score=s) for i, s in scores.items()]

    # (a) generation 0: the two best of three
    chosen = goats.update_with_generation(_mdls(0, {0: 5.0, 1: 3.0, 2: 9.0}), 2)
    assert [(m.gen, m.id) for m in chosen] == [(0, 1), (0, 0)]
    assert goats.generations == [[(0, 1), (0, 0)]]

    # (b) generation 2 (generation 1 skipped): pool spans both, padding
    chosen = goats.update_with_generation(_mdls(2, {0: 1.0, 1: 4.0}), 2)
    assert [(m.gen, m.id) for m in chosen] == [(2, 0), (0, 1)]
    assert goats.generations == [[(0, 1), (0, 0)], [], [(2, 0), (0, 1)]]

    assert (tmp_path / 'goats.txt').read_text() == '0_1 0_0\n\n2_0 0_1\n'
    lines = (tmp_path / 'score_info.txt').read_text().splitlines()
    tpl = goats.score_line_tpl
    assert lines == [
        tpl.format(iter='ITER', best_score='BEST SCORE',
                   score_avrg='GOAT AVERAGE').rstrip('\n'),
        tpl.format(iter='0000', best_score='3.000', score_avrg='4.000').rstrip('\n'),
        tpl.format(iter='0002', best_score='1.000', score_avrg='2.000').rstrip('\n'),
    ]

    # (c) no model
    with pytest.raises(ValueError, match='No models provided'):
        goats.update_with_generation([], 2)


class _KinSpy:
    def __init__(self, raw: dict) -> None:
        self.raw = raw
        self.calls: list[dict[str, Any]] = []

    def prepare_batch_select(self, **kw: Any) -> None:
        self.calls.append(kw)

    def batch_select(self) -> dict:
        return self.raw


def test_get_rate_coefficients_batches_and_sums_per_pes(tmp_path) -> None:
    raw = {
        'G0000': {0: {(1.0, 300.0, 0, 'A', 'B'): 1.0,
                      (1.0, 300.0, 1, 'A', 'B'): 2.0,
                      (1.0, 500.0, 0, 'A', 'B'): 9.0}},
        'G0001': {5: {(1.0, 300.0, 0, 'A', 'B'): 4.0}},
    }
    pairs = [('A', 'B'), (None, 'B'), ('B', 'A')]
    conds = [(1.0, 300.0), (1.0, 500.0)]

    # Scenario 1: every PES summed
    kin = _KinSpy(raw)
    goats = _plain_goats(tmp_path, kin_db=kin)
    goats.generations = [[(0, 0), (1, 5)], [(0, 0)]]
    out = goats.get_rate_coefficients(conds, [0, 1], cast(Any, pairs))
    assert len(kin.calls) == 3 * 2 * 2
    assert all('pes_id' not in c for c in kin.calls)
    assert {c['table'] for c in kin.calls} == {'G0000', 'G0001'}
    assert set(out) == {0, 1}
    assert set(out[0][(1.0, 300.0)]) == {('A', 'B'), ('B', 'A')}
    assert out[0][(1.0, 300.0)][('A', 'B')] == {(0, 0): 3.0, (1, 5): 4.0}
    assert out[0][(1.0, 300.0)][('B', 'A')] == {(0, 0): None, (1, 5): None}
    assert out[0][(1.0, 500.0)][('A', 'B')] == {(0, 0): 9.0, (1, 5): None}
    assert out[1][(1.0, 300.0)][('A', 'B')] == {(0, 0): 3.0}

    # Scenario 2: PES filter
    kin = _KinSpy(raw)
    goats.kin_db = cast(Any, kin)
    out = goats.get_rate_coefficients(conds, [0, 1], cast(Any, pairs), pes_ids=[1])
    assert len(kin.calls) == 12
    assert all(c['pes_id'] == 1 for c in kin.calls)
    assert out[0][(1.0, 300.0)][('A', 'B')] == {(0, 0): 2.0, (1, 5): None}
    assert out[0][(1.0, 500.0)][('A', 'B')] == {(0, 0): None, (1, 5): None}
