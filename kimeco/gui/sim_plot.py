"""Shared helpers to build simulation concentration-profile figures.

These helpers are used by both the simulation section (many-model overlays)
and the database browser (single decoded result vs. experimental data) so
that the styling and experimental overlay logic live in a single place.
"""
from typing import Any

import plotly.graph_objects as go
from numpy.typing import NDArray


def apply_profile_layout(fig: go.Figure) -> go.Figure:
    """Apply the shared concentration-profile styling to ``fig``."""
    axis_common: dict[str, Any] = dict(
        showline=True,
        showgrid=True,
        showticklabels=True,
        linecolor='rgb(0, 0, 0)',
        linewidth=2,
        ticks='inside',
        tickformat='.2e',
        tickfont=dict(family='Arial', size=12, color='rgb(0, 0, 0)'),
    )
    fig.update_layout(
        xaxis=dict(title='time (s)', **axis_common),
        yaxis=dict(title='Density (molecules/cm<sup>3</sup>)', **axis_common),
        plot_bgcolor='white',
        hovermode='closest',
    )
    return fig


def build_profile_figure(decoded: NDArray,
                         species: list[str],
                         selected_species: list[str],
                         exp: Any = None) -> go.Figure:
    """Build a figure of a single decoded result for the selected species.

    Args:
        decoded: Row-oriented matrix ``[mdl_id, time, species...]`` as
            returned by :meth:`SIM_DB.decode_result_blob`.
        species: Ordered species names matching the ``decoded`` columns.
        selected_species: Species the user chose to display.
        exp: Optional experiment object exposing ``data``, ``error`` and
            ``species`` used to overlay the experimental profile.

    Returns:
        A styled ``plotly`` figure.
    """
    fig = go.Figure()
    time = decoded[:, 1]

    for sp in selected_species:
        if sp not in species:
            continue
        sp_idx = species.index(sp) + 2
        fig.add_trace(
            go.Scatter(
                x=time,
                y=decoded[:, sp_idx],
                mode='lines',
                name=f'{sp} (sim)',
                line=dict(color='#1E90FF'),
            )
        )

        if exp is None or getattr(exp, 'data', None) is None:
            continue
        exp_species = getattr(exp, 'species', []) or []
        if sp not in exp_species:
            continue
        exp_sp_idx = exp_species.index(sp) + 1
        error_y = None
        if getattr(exp, 'error', None) is not None:
            error_y = {'array': exp.error[exp_sp_idx]}
        fig.add_trace(
            go.Scatter(
                x=exp.data[0],
                y=exp.data[exp_sp_idx],
                error_y=error_y,
                mode='markers',
                name=f'{sp} (exp)',
                line=dict(color='black'),
            )
        )

    return apply_profile_layout(fig)
