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
            # Support indexed placeholders such as m_rotors[0].symFact.
            if '[' in token or ']' in token:
                if token.count('[') != 1 or token.count(']') != 1:
                    raise ValueError(
                        f'Invalid indexed token in placeholder: {token}'
                    )
                attr_name, index_str = token.split('[', 1)
                index_str = index_str[:-1] if index_str.endswith(']') else ''
                if not attr_name or not index_str.isdigit():
                    raise ValueError(
                        f'Invalid indexed token in placeholder: {token}'
                    )
                value = getattr(value, attr_name)
                idx = int(index_str)
                try:
                    value = value[idx]
                except (IndexError, TypeError) as exc:
                    raise ValueError(
                        f'Cannot index token {token} in placeholder '
                        f'{placeholder}'
                    ) from exc
            else:
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
