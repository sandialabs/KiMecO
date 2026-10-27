import os

from kimeco.parameters import SOP


#: Root of the template placeholders naming MESS side-output files
#: (``{__output__.rate}``, ``{__output__.ped}``, ``{__output__.micro}``).
#: An item name can never start with it (``__`` is the SOP DB separator).
OUTPUT_NAME_ROOT = '__output__'

#: Suffix appended to the stem of the written input file for each side
#: output: ``RateOutput`` -> ``<stem>.out``, ``PEDOutput`` ->
#: ``<stem>_ped.out``, ``MicroRateOutput`` -> ``<stem>_ke.out``. Every input
#: file of every model thus writes its own side outputs, even when several
#: inputs run in the same directory.
OUTPUT_NAME_SUFFIXES: dict[str, str] = {
    'rate': '.out',
    'ped': '_ped.out',
    'micro': '_ke.out',
}


class MessTemplate(list):
    """MESS input template of one input file (a list of template lines).

    Behaves exactly as the plain list of lines produced by the reader, and
    also carries the PES id of the input file it was read from, so that the
    writer can put that file's own data back (energy frame, per-file keys).
    """

    def __init__(self,
                 lines=(),
                 pes_id: int | None = None) -> None:
        """Create the template.

        Args:
            lines: initial template lines.
            pes_id (int | None): PES id (= index of the MESS input file).
        """
        super().__init__(lines)
        self.pes_id: int | None = pes_id


class MessWriter:
    """Object that writes a set of parameters into
    a Mess file input.
    """
    def __init__(self,
                 SOP: SOP,
                 tpl,
                 pres: list[float] | None = None,
                 temp: list[float] | None = None) -> None:
        self.SOP = SOP
        self.tpl = tpl
        # Optional sub-grid overriding only the rate-coefficient
        # temperature/pressure placeholders (postprocessing).
        self._pres_override = pres
        self._temp_override = temp
        # Energy offset (kcal/mol) of the template's input file: the SOP
        # stores energies aligned on a reference file, each file is written
        # back in its own energy zero. 0.0 for plain-list templates.
        self._energy_offset: float = 0.0
        pes_id = getattr(tpl, 'pes_id', None)
        if pes_id is not None:
            file_data = getattr(SOP, 'pes_file_data', {}).get(pes_id)
            if file_data is not None:
                self._energy_offset = float(file_data.energy_offset)
        # Stem of the file being written (set by write), used to name the
        # MESS side outputs.
        self._stem: str | None = None

    @staticmethod
    def _fmt_grid(values: list[float]) -> str:
        out = ""
        for v in values:
            # 5 significant figures: decimals depend on the magnitude.
            # Exponent taken after rounding so 9.99996 -> 10.000, not 10.0000.
            exponent = int(f"{v:.4e}".split('e')[1])
            decimals = max(0, 4 - exponent)
            out += f" {v: .{decimals}f}"
        out += '\n'
        return out

    def _output_name(self, kind: str) -> str:
        """Name of one MESS side-output file of the input being written.

        Args:
            kind (str): 'rate', 'ped' or 'micro'.

        Returns:
            str: ``<stem><suffix>``.
        """
        if kind not in OUTPUT_NAME_SUFFIXES:
            raise ValueError(f'Unknown MESS output placeholder: {kind}')
        if self._stem is None:
            raise ValueError(
                'MESS output names are only known while writing a file.')
        return self._stem + OUTPUT_NAME_SUFFIXES[kind]

    def _resolve_placeholder(self, placeholder: str):
        if (placeholder == 'SOP.r_rc_temp'
                and self._temp_override is not None):
            return self._fmt_grid(self._temp_override)
        if (placeholder == 'SOP.r_rc_pres'
                and self._pres_override is not None):
            return self._fmt_grid(self._pres_override)
        if '.' not in placeholder:
            raise ValueError(f'Unsupported placeholder: {placeholder}')

        root_name, path = placeholder.split('.', 1)
        if root_name == OUTPUT_NAME_ROOT:
            return self._output_name(path)
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

        # The energy of an item ({X.energy}) is the only absolute energy of
        # the templates: write it in the energy zero of the template's file
        # (rounded to 1e-10 kcal/mol to drop float artefacts of the shift).
        if (root_name != 'SOP' and path == 'energy'
                and self._energy_offset != 0.0):
            value = round(float(value) + self._energy_offset, 10)
        return value

    def write(self,
              loc: str,
              filename: str) -> None:
        self._stem = os.path.splitext(filename)[0]
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
