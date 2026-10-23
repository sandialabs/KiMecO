"""CI-safe tests for the kmoui SIM section (``SIMSection``): experiment
resolution (regular ids below n_run, banded extrapolated ids), dropdown
options, the plot callbacks (captured from a fake Dash app) and the figure
built from nested SIM_DB results.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import plotly.graph_objects as go
import pyarrow as pa
import pyarrow.feather as feather
import pytest
from dash import html
from dash.exceptions import PreventUpdate

from kimeco.database.sim_db import SIM_DB
from kimeco.gui import simsection as simsection_mod
from kimeco.gui.simsection import SIMSection


# ===========================================================================
# Experiments, options and callbacks
# ===========================================================================
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _exp(exp_type='Time profile', pres=101325.0, temp=300.0, species=('A',)):
    n = len(species)
    return SimpleNamespace(
        exp_type=exp_type,
        P=pres,
        T=temp,
        species=list(species),
        data=np.array([[0.0, 1.0]] + [[0.1, 0.2]] * n),
        error=np.array([[0.0, 0.0]] + [[0.01, 0.01]] * n),
    )


def _bare_section(experiments=None,
                  pp_experiments=None,
                  n_run=None,
                  pp_ensembles=None,
                  **attrs) -> SIMSection:
    section = SIMSection.__new__(SIMSection)
    section.experiments = experiments if experiments is not None else []
    section.pp_experiments = (
        pp_experiments if pp_experiments is not None else [])
    section.n_run = n_run if n_run is not None else len(section.experiments)
    section.n_pp = len(section.pp_experiments)
    section.settings = {
        'pres_unit': 'bar',
        'n_run_exp': section.n_run,
        'pp_ensembles': pp_ensembles if pp_ensembles is not None else [],
    }
    for key, value in attrs.items():
        setattr(section, key, value)
    return section


def _capture_callbacks(monkeypatch, section: SIMSection) -> dict[str, Any]:
    callbacks: dict[str, Any] = {}

    def _fake_callback(*_args, **_kwargs):
        def _decorator(func):
            callbacks[func.__name__] = func
            return func

        return _decorator

    monkeypatch.setattr(simsection_mod, 'callback', _fake_callback)
    section.register_callbacks()
    return callbacks


# ---------------------------------------------------------------------------
# _resolve_experiment
# ---------------------------------------------------------------------------
def test_resolve_experiment() -> None:
    """Ids below n_run resolve to regular experiments, banded ids to
    extrapolated ones, out of range to None."""
    # -- test_resolve_experiment_regular_below_n_run
    exps = [_exp(species=['A', 'B'])]
    section = _bare_section(experiments=exps, n_run=1)

    exp_obj, show, label = section._resolve_experiment(0)

    assert exp_obj is exps[0]
    assert show is True
    assert 'Time profile #0' in label
    assert '1.013 bar' in label
    assert '300 K' in label
    assert label.endswith('A, B')

    # -- test_resolve_experiment_banded_extrapolated
    exps = [_exp()]
    pp = [_exp(exp_type='PP', temp=500.0, species=['C'])]
    section = _bare_section(
        experiments=exps, pp_experiments=pp, n_run=1,
        pp_ensembles=['G0000'])

    # experiment_id = n_run + band*n_pp + local = 1 + 0*1 + 0.
    exp_obj, show, label = section._resolve_experiment(1)

    assert exp_obj is pp[0]
    assert show is False
    assert 'Extrapolated (band 0)' in label
    assert 'PP' in label
    assert '500 K' in label

    # -- test_resolve_experiment_out_of_range_returns_none
    exps = [_exp()]
    section = _bare_section(experiments=exps, n_run=1, pp_ensembles=[])

    exp_obj, show, label = section._resolve_experiment(5)

    assert exp_obj is None
    assert show is False
    assert label == 'Simulation #5'


# ---------------------------------------------------------------------------
# _experiment_options
# ---------------------------------------------------------------------------
def test_experiment_options() -> None:
    """Options list the regular and banded experiments; none without
    experiments."""
    # -- test_experiment_options_lists_regular_and_banded
    exps = [_exp()]
    pp = [_exp(exp_type='PP', species=['C'])]
    section = _bare_section(
        experiments=exps, pp_experiments=pp, n_run=1,
        pp_ensembles=['G0000', 'G0001'])

    options = section._experiment_options()

    # value 0 (regular) + one banded id per (band, local): 1 and 2.
    assert [o['value'] for o in options] == [0, 1, 2]
    assert options[0]['label'] == section._resolve_experiment(0)[2]
    assert options[1]['label'] == section._resolve_experiment(1)[2]
    assert options[2]['label'] == section._resolve_experiment(2)[2]

    # -- test_experiment_options_empty
    section = _bare_section(
        experiments=[], pp_experiments=[], n_run=0, pp_ensembles=[])

    assert section._experiment_options() == []


# ---------------------------------------------------------------------------
# show_sim_plot_button callback
# ---------------------------------------------------------------------------
def test_show_sim_plot_button(monkeypatch) -> None:
    """The plot button shows once an experiment is selected; without experiments
    the update is prevented."""
    _mp_root = monkeypatch
    # -- test_show_sim_plot_button_selected
    with _mp_root.context() as monkeypatch:
        section = _bare_section()
        callbacks = _capture_callbacks(monkeypatch, section)

        assert callbacks['show_sim_plot_button']([0]) == {'display': 'block'}

    # -- test_show_sim_plot_button_empty_prevents
    _failures = []
    for experiments in [None, []]:
        try:
            with _mp_root.context() as monkeypatch:
                section = _bare_section()
                callbacks = _capture_callbacks(monkeypatch, section)

                with pytest.raises(PreventUpdate):
                    callbacks['show_sim_plot_button'](experiments)
        except AssertionError as _exc:
            _failures.append(
                f"test_show_sim_plot_button_empty_prevents"
                f"[experiments={experiments!r}]: {_exc}")
    assert not _failures, '\n'.join(_failures)


# ---------------------------------------------------------------------------
# update_sim_figure callback
# ---------------------------------------------------------------------------
def test_update_sim_figure(monkeypatch) -> None:
    """A regular experiment draws one figure per species; a banded id is routed
    as such; missing clicks or experiments prevent the update."""
    _mp_root = monkeypatch
    # -- test_update_sim_figure_regular_one_call_per_species
    with _mp_root.context() as monkeypatch:
        exps = [_exp(species=['A'])]
        section = _bare_section(experiments=exps, n_run=1)
        section.sim_db = cast(Any, SimpleNamespace(sv_species=['A']))

        reg_calls: list[dict] = []
        fig_calls: list[dict] = []

        def _fake_regular(selected_gen, experiment_id):
            reg_calls.append(
                {'selected_gen': selected_gen, 'experiment_id': experiment_id})
            return [{'G0000': {}}]

        monkeypatch.setattr(
            section, 'get_regular_condition_profiles', _fake_regular)
        monkeypatch.setattr(
            section, 'make_figure', lambda **kw: fig_calls.append(kw) or [])

        callbacks = _capture_callbacks(monkeypatch, section)
        style, _children = callbacks['update_sim_figure'](1, [0], [0])

        assert style == {'display': 'block'}
        assert len(fig_calls) == 1
        assert fig_calls[0]['experiment_id'] == 0
        assert fig_calls[0]['sp'] == 'A'
        assert reg_calls == [{'selected_gen': [0], 'experiment_id': 0}]

    # -- test_update_sim_figure_banded_routes_experiment_id
    with _mp_root.context() as monkeypatch:
        exps = [_exp(species=['A'])]
        pp = [_exp(exp_type='PP', species=['C'])]
        section = _bare_section(
            experiments=exps, pp_experiments=pp, n_run=1,
            pp_ensembles=['G0000'])
        section.sim_db = cast(Any, SimpleNamespace(sv_species=['C']))

        fig_calls: list[dict] = []
        monkeypatch.setattr(
            section, 'get_regular_condition_profiles',
            lambda selected_gen, experiment_id: [{'G0000': {}}])
        monkeypatch.setattr(
            section, 'make_figure', lambda **kw: fig_calls.append(kw) or [])

        callbacks = _capture_callbacks(monkeypatch, section)
        callbacks['update_sim_figure'](1, [1], [0])

        # The banded id resolves to the PP experiment's measured species.
        assert len(fig_calls) == 1
        assert fig_calls[0]['experiment_id'] == 1
        assert fig_calls[0]['sp'] == 'C'

    # -- test_update_sim_figure_prevents
    _failures = []
    for clic, experiments in [(1, []), (None, [0])]:
        try:
            with _mp_root.context() as monkeypatch:
                section = _bare_section(experiments=[_exp()], n_run=1)
                fig_calls: list[dict] = []
                monkeypatch.setattr(
                    section, 'make_figure', lambda **kw: fig_calls.append(kw) or [])

                callbacks = _capture_callbacks(monkeypatch, section)
                with pytest.raises(PreventUpdate):
                    callbacks['update_sim_figure'](clic, experiments, [0])

                assert fig_calls == []
        except AssertionError as _exc:
            _failures.append(
                f"test_update_sim_figure_prevents"
                f"[clic={clic!r} experiments={experiments!r}]: {_exc}")
    assert not _failures, '\n'.join(_failures)


# ---------------------------------------------------------------------------
# make_figure heading
# ---------------------------------------------------------------------------
def test_make_figure() -> None:
    """The heading names species and experiment; an absent species gives a bare
    figure; an unresolved experiment gives an empty one."""
    # -- test_make_figure_heading_contains_species_and_experiment
    exps = [_exp(species=['A'])]
    section = _bare_section(experiments=exps, n_run=1)
    section.sim_db = cast(Any, SimpleNamespace(sv_species=['A']))

    rendered = section.make_figure(
        gen_name='G0000', TPGenSP={}, experiment_id=0, sp='A')

    heading = rendered[0]
    assert isinstance(heading, html.H3)
    exp_label = section._resolve_experiment(0)[2]
    assert heading.children == f'A — {exp_label} — G0000'

    # -- test_make_figure_species_absent_returns_bare_figure
    exps = [_exp(species=['A'])]
    section = _bare_section(experiments=exps, n_run=1)
    section.sim_db = cast(Any, SimpleNamespace(sv_species=['B']))

    rendered = section.make_figure(
        gen_name='G0000', TPGenSP={}, experiment_id=0, sp='A')

    assert len(rendered) == 1
    assert isinstance(rendered[0], go.Figure)

    # -- test_make_figure_unresolved_experiment_returns_empty
    section = _bare_section(experiments=[], n_run=0, pp_ensembles=[])
    section.sim_db = cast(Any, SimpleNamespace(sv_species=['A']))

    rendered = section.make_figure(
        gen_name='G0000', TPGenSP={}, experiment_id=9, sp='A')

    assert rendered == []


# ===========================================================================
# Profiles from SIM_DB
# ===========================================================================
def _blob_from_dict(data: dict[str, list[float]]) -> bytes:
    table = pa.table(data)
    sink = pa.BufferOutputStream()
    feather.write_feather(table, sink)
    return sink.getvalue().to_pybytes()


def _pp_exp(pres=101325.0, temp=300.0, species=('A',)):
    return SimpleNamespace(
        exp_type='PP', P=pres, T=temp, species=list(species))


def test_sim_db_profiles_for_figures(tmp_path) -> None:
    """make_figure draws the species trace from nested SIM_DB results;
    get_regular_condition_profiles filters by experiment id (missing id, banded
    offset id included)."""
    _tmp_root = tmp_path
    # -- test_make_figure_uses_nested_sim_db_results_for_species_trace
    section = SIMSection.__new__(SIMSection)
    exp = _pp_exp(species=['A'])
    # Banded id -> show_exp_profile is False, so only the sim trace is drawn.
    section.experiments = [exp]
    section.pp_experiments = [exp]
    section.n_run = 1
    section.n_pp = 1
    section.settings = {
        'pres_unit': 'bar',
        'n_run_exp': 1,
        'pp_ensembles': ['G0000'],
        'experiments': [exp],
    }
    section.sim_db = cast(Any, SimpleNamespace(sv_species=['A']))

    rows = np.array([[7.0, 0.0, 1.0], [7.0, 1.0, 0.25]], dtype=float)
    rendered = section.make_figure(
        gen_name='G0000',
        TPGenSP={'G0000': {7: {1: rows}}},
        experiment_id=1,
        sp='A',
    )

    fig = cast(Any, rendered[-1]).figure

    assert len(fig.data) == 1
    assert list(fig.data[0].x) == [0.0, 1.0]
    assert list(fig.data[0].y) == [1.0, 0.25]

    # -- test_get_regular_condition_profiles_filters_by_experiment_id
    tmp_path = _tmp_root / 'test_get_regular_condition_profiles_filters_by_experiment_id'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_REG_SIM_DB', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    sim_db.prepare_batch_upsert(
        table='G0000', mdl_id=5, experiment_id=0,
        result=_blob_from_dict({'time': [0.0], 'A': [1.0]}))
    sim_db.prepare_batch_upsert(
        table='G0000', mdl_id=5, experiment_id=1,
        result=_blob_from_dict({'time': [0.0], 'A': [2.0]}))
    sim_db.batch_upsert()

    section = SIMSection.__new__(SIMSection)
    section.sim_db = sim_db
    section.gapp = cast(
        Any,
        SimpleNamespace(
            goats=SimpleNamespace(generations={0: [(0, 5)]}),
        ),
    )

    out = section.get_regular_condition_profiles(
        selected_gen=[0],
        experiment_id=1,
    )

    assert len(out) == 1
    # Only the requested experiment_id blob is returned.
    assert sorted(out[0]['G0000'][5]) == [1]
    assert out[0]['G0000'][5][1][0, 2] == 2.0

    # -- test_get_regular_condition_profiles_missing_experiment_id
    tmp_path = _tmp_root / 'test_get_regular_condition_profiles_missing_experiment_id'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_REG_SIM_DB_MISS', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    sim_db.prepare_batch_upsert(
        table='G0000', mdl_id=5, experiment_id=0,
        result=_blob_from_dict({'time': [0.0], 'A': [1.0]}))
    sim_db.batch_upsert()

    section = SIMSection.__new__(SIMSection)
    section.sim_db = sim_db
    section.gapp = cast(
        Any,
        SimpleNamespace(
            goats=SimpleNamespace(generations={0: [(0, 5)]}),
        ),
    )

    # No rows for experiment_id=9 -> no raise, empty per-gen mapping.
    out = section.get_regular_condition_profiles(
        selected_gen=[0],
        experiment_id=9,
    )

    assert len(out) == 1
    assert out[0].get('G0000', {}) == {}

    # -- test_get_regular_condition_profiles_with_offset_banded_id: A banded
    #    experiment_id selects the offset row written by that band.
    tmp_path = _tmp_root / 'test_get_regular_condition_profiles_with_offset_banded_id'
    tmp_path.mkdir(parents=True)
    sim_db = SIM_DB(name='TEST_REG_SIM_DB_OFF', path=str(tmp_path), threads=1)
    sim_db.create_new_table(name='G0000')
    sim_db.prepare_batch_upsert(
        table='G0000', mdl_id=5, experiment_id=0,
        result=_blob_from_dict({'time': [0.0], 'A': [1.0]}))
    sim_db.prepare_batch_upsert(
        table='G0000', mdl_id=5, experiment_id=4,
        result=_blob_from_dict({'time': [0.0], 'A': [9.0]}))
    sim_db.batch_upsert()

    section = SIMSection.__new__(SIMSection)
    section.sim_db = sim_db
    section.gapp = cast(
        Any,
        SimpleNamespace(
            goats=SimpleNamespace(generations={0: [(0, 5)]}),
        ),
    )

    out = section.get_regular_condition_profiles(
        selected_gen=[0],
        experiment_id=4,
    )

    assert sorted(out[0]['G0000'][5]) == [4]
    assert out[0]['G0000'][5][4][0, 2] == 9.0

