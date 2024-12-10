from game.gui.analyser import Analyser
from dash import html, dcc, callback, Output, Input

class SOPAnalyser(Analyser):

    def layout(self):
        children = [
            self.header,
            self.core
        ]

    @property
    def header(self) -> html.Div:
        hdr = html.Div(className='row',
                       children=[
                           html.H2('Choose type of parameter:'),
                           dcc.RadioItems(options=[
                               {'label': 'Wells energies', 'value': 'we'},
                               {'label': 'Barriers energies', 'value': 'be'},
                               {'label': 'Imaginary freq', 'value': 'if'},
                               {'label': 'Score', 'value': 'sc'}],
                            value='Wells energies',
                            inline=True,
                            id='ptype')
                       ])
        return hdr
