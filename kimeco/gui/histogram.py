import plotly.graph_objects as go
from dash import dash_table, html, dcc
import numpy as np
from typing import Any
from enum import Enum


class StatColumns(Enum):
    GN = 'Generation #'
    MEAN = 'MEAN'
    STD = 'STD'
    MODE = 'MODE'
    NEL = '# of elements'


class Histogram:
    __id__ = 0

    def __init__(self,
                 data: dict[int, list[float]],
                 settings: dict[str, Any],
                 histfunc: str = "count",
                 ) -> None:
        """Create a plotly histogram with associated
        data analysis and controls.

        Args:
            data (dict[int, list[float]]): The histograms to overlay
            histfunc (str, optional): The type of histogram.
                                      Defaults to "count".
            title (str, optional): The title of the histogram.
                                   Defaults to ''.
        """
        self.id = Histogram.__id__
        Histogram.__id__ += 1
        self.n_bin = 30
        self.hist = go.Figure()
        self.stat_table: dash_table.DataTable
        self.title = settings['title']
        self.tickformat = settings['tickformat']
        self.unit = settings['unit']
        self.font = 'sans serif'
        self.make_hist(data=data,
                       histfunc=histfunc)
        self.hist_formatting(settings['title'])
        self.make_table(data=data)

    def make_hist(self,
                  data: dict[int, list[float]],
                  histfunc: str):
        """Add the traces to the figure.

        Args:
            data (list[list[float]]): list of traces
            legends (list[str]): legend of each trace
            histfunc (str): type of histogram
        """
        for gen_id, trace in data.items():
            trace = np.concatenate(trace).tolist()
            self.hist.add_trace(
                go.Histogram(
                    histfunc=histfunc,
                    x=trace,
                    nbinsx=self.n_bin,
                    name=f'Gen {gen_id}'
                )
            )

    def hist_formatting(self,
                        title: str):
        """Final formatting of the histogram.

        Args:
            title (str): title of the histogram
        """
        self.hist.update_layout(
            barmode='overlay',
            xaxis=dict(
                title={
                    'text': title,
                    'font': {'family': self.font,
                             'size': 18,
                             'color': 'rgb(0, 0, 0)'}
                    },
                showline=True,
                showgrid=True,
                showticklabels=True,
                linecolor='rgb(0, 0, 0)',
                linewidth=2,
                ticks='inside',
                tickformat=self.tickformat,
                tickfont=dict(
                    family=self.font,
                    size=14,
                    color='rgb(0, 0, 0)')
            ),
            yaxis=dict(
                title={
                    'text': 'Count of elements',
                    'font': {'family': self.font,
                             'size': 18,
                             'color': 'rgb(0, 0, 0)'}
                    },
                showline=True,
                showgrid=True,
                showticklabels=True,
                linecolor='rgb(0, 0, 0)',
                linewidth=2,
                ticks='inside',
                tickfont=dict(
                    family=self.font,
                    size=14,
                    color='rgb(0, 0, 0)')
            ),
            plot_bgcolor='white'
            )
        # Reduce opacity to see all histograms
        self.hist.update_traces(opacity=0.75)

    def make_table(self,
                   data: dict[int, list[float]]):
        header = [
            {'name': StatColumns.GN.value,
             'id': StatColumns.GN.value},
            {'name': StatColumns.MEAN.value + self.unit,
             'id': StatColumns.MEAN.value},
            {'name': StatColumns.STD.value + self.unit,
             'id': StatColumns.STD.value},
            {'name': StatColumns.MODE.value + self.unit,
             'id': StatColumns.MODE.value},
            {'name': StatColumns.NEL.value,
             'id': StatColumns.NEL.value}
        ]
        self.stat_table = dash_table.DataTable(
            columns=header,
            data=self.make_stats(data),
            style_cell=dict(textAlign='center'),
            style_data=dict(backgroundColor="white"),
            id={"type": "stat_table", "index": self.id},
            editable=False,
            row_selectable=False,
            row_deletable=False,
            style_table={'overflowX': 'auto'},
            style_header={'backgroundColor': 'lightgrey'}
        )

    def make_stats(self,
                   data: dict[int, list[float]]):
        """Calculate the statistics for each rows

        Args:
            data (list[list[float]]): list of traces

        Returns:
            table_rows (list[dict[Any]]):
                [
                {'column1 name': value row1, 'column2 name': value row1},
                {'column1 name': value row2, 'column2 name': value row2}
                ]
        """
        table_rows: list[dict[Any]] = []
        for gen_id, trace in data.items():
            # Create bins and accumulate values
            hist, bin_edges = np.histogram(trace, bins=self.n_bin)

            # Find the bin with the maximum count
            mode_bin_index = np.argmax(hist)
            mode = f'[{bin_edges[mode_bin_index]:-3.2e}, ' +\
                f'{bin_edges[mode_bin_index + 1]:-3.2e}]'
            table_rows.append(
                {
                    StatColumns.GN.value: gen_id,
                    StatColumns.MEAN.value: f'{np.mean(trace):-3.2e}',
                    StatColumns.STD.value: f'{np.std(trace):-3.2e}',
                    StatColumns.MODE.value: mode,
                    StatColumns.NEL.value: len(trace)
                }
            )
        return table_rows

    def add_vline(self,
                  x: float,
                  line_width: float = 2.0,
                  line_color: str = 'black'):
        self.hist.add_vline(
            x=x,
            line_dash='dash',
            line_width=line_width,
            line_color=line_color

        )

    def layout(self):
        return [
            html.Div(
                children=[
                    html.Div(
                        children=[self.stat_table],
                        style={'flex': '0 0 70%', 'margin': '10px'}
                    ),
                    html.Div(
                        children=[
                            html.H3('Number of bin:'),
                            dcc.Input(
                                type='number',
                                value=self.n_bin,  # Default number of bins
                                min=1,
                                step=1,
                                style={'margin': '10px'},
                                id={"type": "nbin_sop", "index": self.id}
                            )],
                        style={'flex': '1', 'margin': '10px'}
                    )],
                style={'display': 'flex', 'flexDirection': 'row'}),
            html.Div(children=[
                dcc.Graph(
                    figure=self.hist,
                    id={"type": "sop_figure", "index": self.id}
                    )
            ])]
