from kimeco.parameters import SOP


class MessWriter:
    """Object that writes a set of parameters into
    a Mess file input.
    """
    def __init__(self,
                 SOP: SOP,
                 tpl) -> None:
        self.SOP = SOP
        self.tpl = tpl

    def _resolve_placeholder(self, placeholder: str):
        if '.' not in placeholder:
            raise ValueError(f'Unsupported placeholder: {placeholder}')

        root_name, path = placeholder.split('.', 1)
        if root_name == 'SOP':
            value = self.SOP
        else:
            value = self.SOP.items[root_name]

        for token in path.split('.'):
            value = getattr(value, token)

        return value

    def write(self,
              loc: str,
              filename: str) -> None:
        lines = []
        for k, v in self.SOP.parameters_names.items():
            lines.append(
                f"!{k}: {v}" + "\n"
            )
        for line in self.tpl:
            new_line = line
            while '{' in new_line and '}' in new_line:
                start = new_line.index('{')
                end = new_line.index('}', start)
                placeholder = new_line[start + 1:end]
                replacement = str(self._resolve_placeholder(placeholder))
                new_line = new_line[:start] + replacement + new_line[end + 1:]
            lines.append(new_line)

        with open(loc + '/' + filename, 'w') as f:
            f.writelines(lines)
