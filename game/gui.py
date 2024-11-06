from dash import Dash, html, dcc, callback, Output, Input, dash_table
import plotly.express as px
import pandas as pd

# Incorporate data
# df = pd.read_csv('~/projects/ethylperoxy/me/file.csv')
from game.database.game_db import Game_db

wd = '/home/csoulie/projects/ethylperoxy/me/ethylperoxy_game'

sop_db = Game_db(name=f'GAME_DB_SOP', path=wd)
row: list[float] = [0]
row.extend(sop_db.get_sop_row(table='G0',id=0))
names = ['id', 'w_1_e', 'w_1_f0', 'w_1_f1', 'w_1_f2', 'w_1_f3', 'w_1_f4', 'w_1_f5', 'w_1_f6', 'w_1_f7', 'w_1_f8', 'w_1_f9', 'w_1_f10', 'w_1_f11', 'w_1_f12', 'w_1_f13', 'w_1_f14', 'w_1_f15', 'w_1_f16', 'w_1_f17', 'w_1_f18', 'w_1_r0', 'w_1_r1', 'w_2_e', 'w_2_f0', 'w_2_f1', 'w_2_f2', 'w_2_f3', 'w_2_f4', 'w_2_f5', 'w_2_f6', 'w_2_f7', 'w_2_f8', 'w_2_f9', 'w_2_f10', 'w_2_f11', 'w_2_f12', 'w_2_f13', 'w_2_f14', 'w_2_f15', 'w_2_f16', 'w_2_f17', 'w_2_r0', 'w_2_r1', 'w_2_r2', 'w_3_e', 'w_3_f0', 'w_3_f1', 'w_3_f2', 'w_3_f3', 'w_3_f4', 'w_3_f5', 'w_3_f6', 'w_3_f7', 'w_3_f8', 'w_3_f9', 'w_3_f10', 'w_3_f11', 'w_3_f12', 'w_3_f13', 'w_3_f14', 'w_3_f15', 'w_3_f16', 'w_3_f17', 'w_3_f18', 'w_3_f19', 'w_3_f20', 'w_4_e', 'w_4_f0', 'w_4_f1', 'w_4_f2', 'w_4_f3', 'w_4_f4', 'w_4_f5', 'w_4_f6', 'w_4_f7', 'w_4_f8', 'w_4_f9', 'w_4_f10', 'w_4_f11', 'w_4_f12', 'w_4_f13', 'w_4_f14', 'w_4_f15', 'w_4_f16', 'w_4_f17', 'w_4_f18', 'w_4_f19', 'w_4_f20', 'nobar_2_e', 'nobar_2_f0', 'nobar_2_f1', 'nobar_2_f2', 'nobar_2_f3', 'nobar_2_f4', 'nobar_2_f5', 'nobar_2_f6', 'nobar_2_f7', 'nobar_2_f8', 'nobar_2_f9', 'nobar_2_f10', 'nobar_2_f11', 'nobar_2_f12', 'nobar_2_f13', 'nobar_2_f14', 'nobar_1_e', 'nobar_1_f0', 'nobar_1_f1', 'nobar_1_f2', 'nobar_1_f3', 'nobar_1_f4', 'nobar_1_f5', 'nobar_1_f6', 'nobar_1_f7', 'nobar_1_f8', 'nobar_1_f9', 'nobar_1_f10', 'nobar_1_f11', 'nobar_1_f12', 'nobar_1_f13', 'nobar_1_f14', 'nobar_3_e', 'nobar_3_f0', 'nobar_3_f1', 'nobar_3_f2', 'nobar_3_f3', 'nobar_3_f4', 'nobar_3_f5', 'nobar_3_f6', 'nobar_3_f7', 'nobar_3_f8', 'nobar_3_f9', 'nobar_3_f10', 'nobar_3_f11', 'nobar_3_f12', 'nobar_3_f13', 'nobar_3_f14', 'nobar_3_f15', 'rxn_1_e', 'rxn_1_f0', 'rxn_1_f1', 'rxn_1_f2', 'rxn_1_f3', 'rxn_1_f4', 'rxn_1_f5', 'rxn_1_f6', 'rxn_1_f7', 'rxn_1_f8', 'rxn_1_f9', 'rxn_1_f10', 'rxn_1_f11', 'rxn_1_f12', 'rxn_1_f13', 'rxn_1_f14', 'rxn_1_f15', 'rxn_1_f16', 'rxn_1_f17', 'rxn_1_f18', 'rxn_1_f19', 'rxn_1_if', 'rxn_2_e', 'rxn_2_f0', 'rxn_2_f1', 'rxn_2_f2', 'rxn_2_f3', 'rxn_2_f4', 'rxn_2_f5', 'rxn_2_f6', 'rxn_2_f7', 'rxn_2_f8', 'rxn_2_f9', 'rxn_2_f10', 'rxn_2_f11', 'rxn_2_f12', 'rxn_2_f13', 'rxn_2_f14', 'rxn_2_f15', 'rxn_2_f16', 'rxn_2_f17', 'rxn_2_f18', 'rxn_2_f19', 'rxn_2_if', 'rxn_3_e', 'rxn_3_f0', 'rxn_3_f1', 'rxn_3_f2', 'rxn_3_f3', 'rxn_3_f4', 'rxn_3_f5', 'rxn_3_f6', 'rxn_3_f7', 'rxn_3_f8', 'rxn_3_f9', 'rxn_3_f10', 'rxn_3_f11', 'rxn_3_f12', 'rxn_3_f13', 'rxn_3_f14', 'rxn_3_f15', 'rxn_3_f16', 'rxn_3_f17', 'rxn_3_f18', 'rxn_3_f19', 'rxn_3_if', 'rxn_4_e', 'rxn_4_f0', 'rxn_4_f1', 'rxn_4_f2', 'rxn_4_f3', 'rxn_4_f4', 'rxn_4_f5', 'rxn_4_f6', 'rxn_4_f7', 'rxn_4_f8', 'rxn_4_f9', 'rxn_4_f10', 'rxn_4_f11', 'rxn_4_f12', 'rxn_4_f13', 'rxn_4_f14', 'rxn_4_f15', 'rxn_4_f16', 'rxn_4_r0', 'rxn_4_r1', 'rxn_4_r2', 'rxn_4_if', 'pr_1_e', 'fr_1_e', 'fr_1_f0', 'fr_1_f1', 'fr_1_f2', 'fr_1_f3', 'fr_1_f4', 'fr_1_f5', 'fr_1_f6', 'fr_1_f7', 'fr_1_f8', 'fr_1_f9', 'fr_1_f10', 'fr_1_f11', 'fr_2_e', 'fr_2_f0', 'fr_2_f1', 'fr_2_f2', 'pr_2_e', 'fr_3_e', 'fr_3_f0', 'fr_3_f1', 'fr_3_f2', 'fr_3_f3', 'fr_3_f4', 'fr_3_f5', 'fr_3_f6', 'fr_3_f7', 'fr_3_f8', 'fr_3_f9', 'fr_3_f10', 'fr_3_f11', 'fr_3_f12', 'fr_3_f13', 'fr_4_e', 'fr_4_f0', 'pr_3_e', 'fr_5_e', 'fr_5_f0', 'fr_6_e', 'fr_6_f0', 'fr_6_f1', 'fr_6_f2', 'fr_6_f3', 'fr_6_f4', 'fr_6_f5', 'fr_6_f6', 'fr_6_f7', 'fr_6_f8', 'fr_6_f9', 'fr_6_f10', 'fr_6_f11', 'fr_6_f12', 'fr_6_f13', 'fr_6_f14']
df = pd.DataFrame(data=[row], columns=names)
# Initialize app
external_stylesheets = ['~/projects/ethylperoxy/me/file.css']
app = Dash(external_stylesheets=external_stylesheets)

# App layout
app.layout = [
    html.Div(className='row', children='First SOP',
             style={'textAlign': 'center', 'color': 'blue', 'fontSize': 30}),

    html.Div(className='row', children=[
        dcc.RadioItems(options=names,
                       value='w_1_e',
                       inline=True,
                       id='my-radio-buttons-final')
    ]),

    html.Div(className='row', children=[
        html.Div(className='six columns', children=[
            dash_table.DataTable(data=df.to_dict('records'), page_size=11, style_table={'overflowX': 'auto'})
        ]),
        html.Div(className='six columns', children=[
            dcc.Graph(figure={}, id='histo-chart-final')
        ])
    ])
]

# Add controls to build the interaction
@callback(
    Output(component_id='histo-chart-final', component_property='figure'),
    Input(component_id='my-radio-buttons-final', component_property='value')
)

def update_graph(col_chosen):
    fig = px.histogram(df, x='id', y=col_chosen, histfunc='avg')
    return fig

PORT = '8000'
ADDRESS = '127.0.0.1'
if __name__ == '__main__':
    app.run(port=PORT, host=ADDRESS)
    