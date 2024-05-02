import copy

class MessWriter:
    """Object that writes a set of parameters into
    a Mess file."""
    def __init__(self, SOP, tpl):
        self.SOP = SOP
        self.tpl = tpl
    
    def write(self):
        lines = []
        for line in self.tpl:
            if '{' in line:
                new_line = line
                while '{' in new_line:
                    name = new_line.split('{')[1].split('.')[0]
                    line_start = new_line.split('}')[0] + '}'
                    line_end = ''
                    for arg in new_line.split('}')[1:]:
                        if '{' in arg:
                            line_end += arg + '}'
                        else:
                            line_end += arg
                    if name == 'SOP':
                        new_line = line_start.format(SOP=self.SOP) + line_end
                    else:
                        globv = {'ls': line_start,
                                'le': line_end,
                                'sop_name': self.SOP.items[name]}
                        locv = {}
                        #Execute this code using variables defined in globv
                        #Undefined variables are local and returned in locv
                        exec(f"new_line = ls.format({name}=sop_name) + le", globv, locv)
                        new_line = locv['new_line']
                lines.append(new_line)
            else:
                lines.append(line)

        with open('sop.out', 'w') as f:
            f.writelines(lines)
                

