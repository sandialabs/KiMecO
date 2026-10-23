from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any, cast

import kimeco.postprocessing.postprocess as pp_mod
from kimeco._kimeco import KiMecO
from kimeco.postprocessing.postprocess import PostProcess


class _SpyLog:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.warnings: list[str] = []

    def info(self, msg: str) -> None:
        self.infos.append(str(msg))

    def warning(self, msg: str) -> None:
        self.warnings.append(str(msg))

    def debug(self, msg: str) -> None:
        return None

    def error(self, msg: str) -> None:
        return None


class _FakeSopDB:
    def __init__(self, tables: dict[str, list]) -> None:
        self._tables = tables
        self.tables = list(tables.keys())

    def get_table(self, token: str) -> list:
        return self._tables[token]


def _install_extrapolate_spy(monkeypatch) -> dict[str, Any]:
    recorded: dict[str, Any] = {'init': 0, 'ran': 0}

    class _Spy:
        def __init__(self, **kwargs) -> None:
            recorded['init'] += 1
            recorded['kwargs'] = kwargs

        def run(self) -> None:
            recorded['ran'] += 1

    monkeypatch.setattr(pp_mod, 'Extrapolate', _Spy)
    return recorded


class _FakeSOP:
    """Minimal hashable SOP stand-in (SimpleNamespace is unhashable)."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


def _patch_from_db_row(monkeypatch):
    """Share one lightweight SOP so Model dedup can collapse duplicates."""
    shared = _FakeSOP(pres=[1.0], temp=[300.0])
    monkeypatch.setattr(
        pp_mod.SOP, 'from_db_row',
        classmethod(lambda cls, sop_tpl, row: shared))
    return shared


def _pp(**attrs) -> PostProcess:
    pp = PostProcess.__new__(PostProcess)
    pp.klog = cast(Any, _SpyLog())
    pp.init_SOP = cast(Any, object())
    pp.input_tpls = [['tpl']]
    pp.sf = cast(Any, object())
    pp.pert = cast(Any, object())
    pp.kin_db = cast(Any, object())
    pp.sim_db = cast(Any, object())
    for key, value in attrs.items():
        setattr(pp, key, value)
    return pp


def _base_settings(**over) -> dict[str, Any]:
    settings: dict[str, Any] = {
        'pres_unit': 'bar',
        'pp_experiments': [
            SimpleNamespace(P=101325.0, exp_type='TP', T=300.0,
                            species=['A'], X={'A': 1.0}),
        ],
        'n_run_exp': 3,
        'n_exp': 1,
        'pp_ensembles': ['G0000'],
    }
    settings.update(over)
    return settings


# ---------------------------------------------------------------------------
# get_generation
# ---------------------------------------------------------------------------
def test_get_generation_uses_stored_row_id(monkeypatch) -> None:
    _patch_from_db_row(monkeypatch)
    pp = _pp(sop_db=_FakeSopDB({'G0003': [(5, 1.0), (9, 2.0)]}))

    models = pp.get_generation('G0003')

    # Ids come from the stored rows, not from enumerate().
    assert [m.id for m in models] == [5, 9]
    assert all(m.gen == 3 for m in models)
    assert all(m.origin_prefix == 'G' for m in models)


# ---------------------------------------------------------------------------
# set_postprocessing
# ---------------------------------------------------------------------------
def test_set_postprocessing_runs_extrapolate_once_with_primary_dbs(monkeypatch) -> None:
    """set_postprocessing runs Extrapolate once with the primary databases and
    deduplicates models across ensembles."""
    _mp_root = monkeypatch
    # -- test_set_postprocessing_runs_extrapolate_once_with_primary_dbs
    with _mp_root.context() as monkeypatch:
        _patch_from_db_row(monkeypatch)
        recorded = _install_extrapolate_spy(monkeypatch)
        pp = _pp(
            sop_db=_FakeSopDB({'G0000': [(5, 1.0), (9, 2.0)]}),
            settings=_base_settings(),
        )

        pp.set_postprocessing()

        assert recorded['init'] == 1
        assert recorded['ran'] == 1
        kwargs = recorded['kwargs']
        # Primary run databases, not any PP_DB_* clones.
        assert kwargs['sop_db'] is pp.sop_db
        assert kwargs['kin_db'] is pp.kin_db
        assert kwargs['sim_db'] is pp.sim_db
        assert kwargs['prefix'] == 'PP'

        models = kwargs['models']
        assert [m.id for m in models] == [5, 9]
        assert all(m.origin_prefix == 'G' for m in models)
        assert all(m.gen == 0 for m in models)
        # _sim_offset = n_run + pp_band * n_pp = 3 + 0 * 1.
        assert all(m._sim_offset == 3 for m in models)
        assert [m.thread_id for m in models] == [0, 1]

    # -- test_set_postprocessing_dedup_across_ensembles
    with _mp_root.context() as monkeypatch:
        _patch_from_db_row(monkeypatch)
        recorded = _install_extrapolate_spy(monkeypatch)
        pp = _pp(
            sop_db=_FakeSopDB({'G0000': [(5, 1.0), (9, 2.0)]}),
            settings=_base_settings(pp_ensembles=['G0000', 'G0000']),
        )

        pp.set_postprocessing()

        models = recorded['kwargs']['models']
        # Four models collected across two bands collapse to two unique ones.
        assert [m.id for m in models] == [5, 9]
        assert len(models) == 2
        # Dedup keeps the first band, so the offset stays at band 0.
        assert all(m._sim_offset == 3 for m in models)
        assert recorded['init'] == 1


def test_set_postprocessing_gt_models_carry_origin_prefix_and_gen(monkeypatch) -> None:
    """gt models carry their origin prefix and generation; the log reports
    experiment metadata, not the grid."""
    _mp_root = monkeypatch
    # -- test_set_postprocessing_gt_models_carry_origin_prefix_and_gen
    with _mp_root.context() as monkeypatch:
        shared = _patch_from_db_row(monkeypatch)
        recorded = _install_extrapolate_spy(monkeypatch)
        goat_model = SimpleNamespace(sop=shared, id=42, gen=7)
        pp = _pp(
            sop_db=_FakeSopDB({}),
            goats=SimpleNamespace(
                prefix='G',
                get_goat_for_gen=lambda gen_id: [goat_model]),
            settings=_base_settings(pp_ensembles=['GT0002']),
        )

        pp.set_postprocessing()

        models = recorded['kwargs']['models']
        assert len(models) == 1
        mdl = models[0]
        assert mdl.id == 42
        assert mdl.gen == 7
        assert mdl.origin_prefix == 'G'  # == goats.prefix

    # -- test_set_postprocessing_logs_experiment_metadata_not_grid
    with _mp_root.context() as monkeypatch:
        pp = _pp(
            sop_db=_FakeSopDB({}),
            settings=_base_settings(
                pp_ensembles=[],
                pp_experiments=[
                    SimpleNamespace(P=101325.0, exp_type='TP', T=300.0,
                                    species=['A', 'B'], X={'A': 0.5, 'B': 0.5}),
                ],
            ),
        )

        pp.set_postprocessing()

        msgs = cast(_SpyLog, pp.klog).infos
        assert any('pp_exp #0' in m for m in msgs)
        assert any('TP' in m and 'A' in m for m in msgs)
        # The flat pp_temp / pp_pres grid dump must be gone.
        assert not any('pp_temp' in m or 'pp_pres' in m for m in msgs)


# ---------------------------------------------------------------------------
# initialize_databases
# ---------------------------------------------------------------------------
def test_initialize_databases_does_not_create_pp_dbs() -> None:
    src = inspect.getsource(KiMecO.initialize_databases)

    assert 'pp_sim_db' not in src
    assert 'pp_db' not in src
    # The three primary databases are still created.
    assert 'SOP_DB(' in src
    assert 'KIN_DB(' in src
    assert 'SIM_DB(' in src
