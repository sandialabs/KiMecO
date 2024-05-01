import copy

class MessWriter:
    """Object that writes a set of parameters into
    a Mess file."""
    def __init__(self, SOP, tpl):
        self.SOP = copy.deepcopy(SOP)
        self.tpl = copy.deepcopy(tpl)
        pass