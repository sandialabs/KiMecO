from kimeco.gui.section import Section
from dash import html, dcc, Output, Input, State, MATCH
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate
import numpy as np
from typing import Any, cast
import plotly.graph_objects as go


class CORSection(Section):
    def __init__(self, gapp) -> None:
        super().__init__(gapp)
        # corr_tables stores html.Div blocks (each contains a DataTable and
        # an associated plot container), not raw DataTable objects.
        self.corr_tables: list[html.Div] = []
        self.sop_tables: dict[int, Any] = {}
        # Key is generation id
        self.cor_data: dict[int, np.ndarray] = {}
        self.col_names: dict[int, list[str]] = {}

    @property
    def layout(self) -> html.Div:
        return html.Div(
            id='cor',
            style={'display': 'none'},
            children=[
                html.Div(
                    id='cor_plot_button',
                    style={'display': 'block'},
                    children=[
                        html.Button(id='cor_plot_b',
                                    children='Plot',
                                    )]),
                html.Div(
                    id='cor content'
                )])

    def register_callbacks(self):
        # COR interactions
        # Create correlation table for each generation selected
        @self.app.callback(
            Output('cor content', 'children'),
            Input('cor_plot_b', 'n_clicks'),
            State('rb_start', 'value'),
            State('gen range slider', 'value')
        )
        def create_cor_plots(n_clicks,
                             start: str,
                             selected_gen: list[int]
                             ):
            self.corr_tables = []
            if start != 'COR' or n_clicks is None:
                raise PreventUpdate
            for gen_i in selected_gen:
                if gen_i not in self.sop_tables:
                    # Fetch Models for this generation and build the
                    # parameter table directly from Model.sop.parameters_names
                    models = self.gapp.goats.get_goat_for_gen(gen_i)
                    # Preserve GOAT ordering when building rows
                    rows: list[list[float]] = []
                    for mdl in models:
                        # parameters_names is an ordered dict-like mapping
                        vals = list(mdl.sop.parameters_names.values())
                        # Prepend the id into the row for compatibility with
                        # previous layout (original code used [:,1:])
                        rows.append([mdl.id] + [float(v) for v in vals])
                    if rows:
                        self.sop_tables[gen_i] = np.array(rows)
                    else:
                        self.sop_tables[gen_i] = np.empty((0, 0))
                self.create_cor_table(
                    table=np.array(self.sop_tables[gen_i])[:, 1:],
                    id=gen_i)
            return self.corr_tables

        @self.app.callback(
            Output({'type': 'cor_plt', 'index': MATCH}, 'children'),
            Input({'type': 'cor_table', 'index': MATCH}, 'selected_cells'),
            State({'type': 'cor_table', 'index': MATCH}, 'id'),
            prevent_initial_call=True
        )
        def on_cell_click(selected_cells: list[dict[str, Any]],
                          tbl_id: dict[str, Any]):
            if len(selected_cells) == 0:
                raise PreventUpdate
            gen_id = tbl_id['index']
            cor_plots = []
            scores = []
            for cell in selected_cells:
                row = cell['row']
                column = cell['column']
                if column == 0:
                    continue
                px = self.col_names[gen_id][row]
                py = self.col_names[gen_id][column-1]
                x = self.cor_data[gen_id][:, row]
                y = self.cor_data[gen_id][:, column-1]
                scores: list[float] = []  # Used for color mapping
                score_cols = [
                    idx+1 for idx, col in enumerate(self.sop_db.columns)
                    if 'score' in col]
                for row in self.sop_tables[gen_id]:
                    sc = 0
                    for idx in score_cols:
                        sc += row[idx]
                    scores.append(sc)
                # Create a heatmap
                fig = go.Figure(data=go.Scatter(
                    x=x,
                    y=y,
                    mode='markers',
                    marker=dict(
                        size=10,
                        color=scores,
                        colorscale='jet',
                        colorbar=dict(title='Score'),
                        showscale=True
                    )
                ))

                # Add correlation line
                # Calculate the slope and intercept manually
                x_mean = np.mean(x)
                y_mean = np.mean(y)

                # Calculate the slope (m) and intercept (b)
                numerator = np.sum((x - x_mean) * (y - y_mean))
                denominator = np.sum((x - x_mean) ** 2)
                slope = numerator / denominator
                intercept = y_mean - slope * x_mean

                # Calculate R^2 value
                y_pred = slope * x + intercept
                ss_total = np.sum((y - y_mean) ** 2)
                ss_residual = np.sum((y - y_pred) ** 2)
                r_squared = 1 - (ss_residual / ss_total)

                # Create trendline data
                x_trendline = np.linspace(min(x), max(x), 100)
                y_trendline = slope * x_trendline + intercept

                # Add trendline to the plot
                fig.add_trace(go.Scatter(
                    x=x_trendline,
                    y=y_trendline,
                    mode='lines',
                    line=dict(color='red', width=2),
                    name='R²'
                ))

                # Add R^2 value annotation
                fig.add_annotation(
                    x=0.1,  # Position of the annotation (x-axis)
                    y=0.92,  # Position of the annotation (y-axis)
                    xref='paper',  # Reference to the paper coordinates
                    yref='paper',
                    text=f'R² = {r_squared:.2f}',  # Format R² value
                    showarrow=False,
                    font=dict(size=16)
                )
                # Update layout
                fig.update_layout(
                    title=f'Correlation heatmap in G{gen_id:04d}',
                    xaxis_title=px,
                    yaxis_title=py,
                    showlegend=False,
                    width=600,
                    height=600,
                    plot_bgcolor='white',  # plot area
                    paper_bgcolor='white'  # entire figure
                )
                fig.update_xaxes(showgrid=True, gridcolor='black')
                fig.update_yaxes(showgrid=True, gridcolor='black')
                cor_plots.append(dcc.Graph(figure=fig))
            return cor_plots

    def create_cor_table(self,
                         table: np.ndarray,
                         id: int):
        # Calculate the correlation matrix
        stds = np.std(table, axis=0)
        # Filter out non-perturbed parameters
        non_constant_data = table[:, stds > 1e-10]
        perturbed_cols = [
            i for idx, i in enumerate(self.sop_db.columns)
            if stds[idx] > 1e-10]
        self.col_names[id] = perturbed_cols
        self.cor_data[id] = non_constant_data
        cor = np.corrcoef(non_constant_data, rowvar=False)
        r2 = cor**2
        # Prepare the data for the DataTable
        data: list[dict[str, str | int | float | bool]] = [
            {**{'Header': col_name}, **{p: float(f'{v:.2f}')
                                        for p, v in zip(perturbed_cols, row)}}
            for col_name, row in zip(perturbed_cols, r2)
        ]

        header: list[dict[str, str]] = [
            {'name': f'G{id:04d}', 'id': 'Header', 'type': 'text'}
        ] + [
            {'name': col, 'id': col, 'type': 'numeric'}
            for col in perturbed_cols
        ]
        cond_style = self.get_cond_style(perturbed_cols)
        self.corr_tables.append(html.Div(children=[
            DataTable(
                columns=cast(Any, header),
                data=cast(Any, data),
                style_cell=dict(textAlign='center'),
                id={"type": "cor_table", "index": id},
                editable=False,
                style_table={'overflowX': 'auto'},
                style_header={'backgroundColor': 'lightgrey'},
                style_data_conditional=cast(Any, cond_style),
                cell_selectable=True,  # Enable cell selection
                selected_cells=[],  # Initialize as empty
            ),
            html.Div(id={"type": "cor_plt", "index": id})],
            style={"padding": "15px"})
        )

    # def score_to_color(self,
    #                    score: float) -> str:
    #     """return a color depending on r2 value

    #     Args:
    #         r2_value (float): correlation

    #     Returns:
    #         str: color in rgba format
    #     """
    #     if r2_value < 0:
    #         return 'white'  # Out of bounds
    #     elif r2_value <= 0.5:
    #         # Interpolate from white to orange
    #         r = int(255 * (r2_value / 0.5))
    #         g = 165  # Orange
    #         b = 0
    #     elif r2_value <= 1:
    #         # Interpolate from orange to red
    #         r = 255  # Red
    #         g = int(165 * (1 - (r2_value - 0.5) / 0.5))
    #         b = 0
    #     else:
    #         return 'red'  # Out of bounds
    #     return f'rgba({r}, {g}, {b}, 1)'

    def get_cond_style(self,
                       cols: list[str]):
        cond: list[dict[str, Any]] = [
            {
                'if': {
                    'column_id': 'Header',
                },
                'backgroundColor': 'lightgrey'
            }]
        cond.extend(
            [{
                'if': {
                    'filter_query': '{{{}}} >= 0 && {{{}}} < 0.25'.format(
                        col, col),
                    'column_id': col
                },
                'backgroundColor': 'green'
            } for col in cols])
        cond.extend(
            [{
                'if': {
                    'filter_query': '{{{}}} >= 0.25 && {{{}}} < 0.5'.format(
                        col, col),
                    'column_id': col
                },
                'backgroundColor': 'yellow'
            } for col in cols])
        cond.extend(
            [{
                'if': {
                    'filter_query': '{{{}}} >= 0.5 && {{{}}} < 0.75'.format(
                        col, col),
                    'column_id': col
                },
                'backgroundColor': 'orange'
            } for col in cols])
        cond.extend(
            [{
                'if': {
                    'filter_query': '{{{}}} >= 0.75 && {{{}}} <= 1'.format(
                        col, col),
                    'column_id': col
                },
                'backgroundColor': 'red'
            } for col in cols])
        return cond
