from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import plotly.graph_objects as go

from kimeco.gui.sim_plot import build_profile_figure


def _decoded() -> np.ndarray:
    # columns: [mdl_id, time, A, B]
    return np.array(
        [
            [3.0, 0.0, 1.0, 0.0],
            [3.0, 1.0, 0.5, 0.3],
            [3.0, 2.0, 0.25, 0.6],
        ],
        dtype=float,
    )


def test_build_profile_figure_only_plots_selected_species() -> None:
    fig = build_profile_figure(
        decoded=_decoded(),
        species=['A', 'B'],
        selected_species=['A'],
        exp=None,
    )
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].name == 'A (sim)'
    assert list(fig.data[0].y) == [1.0, 0.5, 0.25]


def test_build_profile_figure_overlays_experimental_profile() -> None:
    exp = SimpleNamespace(
        species=['A'],
        data=np.array([[0.0, 1.0, 2.0], [1.1, 0.55, 0.27]], dtype=float),
        error=np.array([[0.0, 1.0, 2.0], [0.1, 0.1, 0.1]], dtype=float),
    )
    fig = build_profile_figure(
        decoded=_decoded(),
        species=['A', 'B'],
        selected_species=['A'],
        exp=exp,
    )
    names = sorted(trace.name for trace in fig.data)
    assert names == ['A (exp)', 'A (sim)']
    exp_trace = next(t for t in fig.data if t.name == 'A (exp)')
    assert list(exp_trace.y) == [1.1, 0.55, 0.27]
    assert list(exp_trace.error_y.array) == [0.1, 0.1, 0.1]


def test_build_profile_figure_skips_experiment_without_species() -> None:
    exp = SimpleNamespace(
        species=['A'],
        data=np.array([[0.0, 1.0], [1.0, 0.5]], dtype=float),
        error=None,
    )
    fig = build_profile_figure(
        decoded=_decoded(),
        species=['A', 'B'],
        selected_species=['B'],
        exp=exp,
    )
    # B has no experimental counterpart -> only the simulated trace.
    assert [t.name for t in fig.data] == ['B (sim)']
