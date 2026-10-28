from curses.ascii import isdigit
from uu import Error
from kimeco.parameters import SOP
from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.well import Well
from kimeco.rotors.internalrotation import InternalRotation
from kimeco.logger_config import KMOLogger
from kimeco.database.kimeco_db import dbs
from kimeco.writers.mess import MessTemplate, OUTPUT_NAME_ROOT

import math
import os
import re
import sys
from collections import deque
from dataclasses import dataclass
from typing import Any, cast

from ase.data import atomic_masses, chemical_symbols


#: Labels of AutoMech fake wells (``FW-<bimol>`` in older inputs,
#: ``FakeW-<bimol>`` in newer ones). A fake well is not a mechanism species,
#: and the same fake well may appear in several input files.
FAKE_WELL_PREFIXES: tuple[str, ...] = ('FW-', 'FakeW-')

#: kcal/mol conversion factors of the energy units accepted in MESS headers
_CM2KCAL = 349.755
_KJ2KCAL = 4.184

#: A plain decimal number, with an optional sign and an optional exponent
#: (``1``, ``-1.5``, ``.5``, ``4.32982E-05``). ``nan`` and ``inf`` are not
#: numbers for the reader.
_NUMBER_RE = re.compile(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?')

#: Units accepted by MESS after ``HotEnergies`` (case-folded); MESS has no
#: unitless form of the key.
HOT_ENERGY_UNITS: tuple[str, ...] = ('kcal/mol', '1/cm', 'kj/mol')

#: Characters separating start, step and finish of a ``HotEnergies`` range
#: (``start<sep>step<sep>finish``), as in MESS.
_HOT_RANGE_SEPARATORS = ':;,&%$@#'


def _is_number(token: str) -> bool:
    """Tell whether a token is a number of a MESS input.

    Args:
        token (str): one whitespace-separated token.

    Returns:
        bool: True for a decimal number, E-notation included; False for any
        other token, ``nan`` and ``inf`` included.
    """
    return _NUMBER_RE.fullmatch(token) is not None


def is_fake_well_label(name: str) -> bool:
    """Tell whether a MESS label names an AutoMech fake well.

    Args:
        name (str): MESS label.

    Returns:
        bool: True for labels starting with ``FW-`` or ``FakeW-``.
    """
    return name.startswith(FAKE_WELL_PREFIXES)


def _header_token(line: str) -> str | None:
    """Keyword of a MESS line, case-folded and cut before its unit.

    ``'  ModelEnergyLimit[kcal/mol]  800'`` gives ``'modelenergylimit'``.
    Comment lines (``!`` or ``#``) and blank lines give None, so a commented
    keyword is never read.

    Args:
        line (str): one line of a MESS input.

    Returns:
        str | None: the keyword, or None.
    """
    tokens = line.split()
    if not tokens or tokens[0].startswith(('!', '#')):
        return None
    return tokens[0].casefold().split('[')[0]


def _leading_numbers(tokens: list[str]) -> list[float]:
    """Read the numbers at the start of a token list (stop at the first
    non-number, e.g. a comment).

    Args:
        tokens (list[str]): whitespace-separated tokens.

    Returns:
        list[float]: the leading numbers.
    """
    numbers: list[float] = []
    for arg in tokens:
        if _is_number(arg):
            numbers.append(float(arg))
        else:
            break
    return numbers


def _atom_element(label: str, mass: float) -> str | None:
    """Chemical element of a MESS ``Atom`` fragment.

    The label is used when it is a chemical symbol (``H``, ``O``...);
    otherwise the element whose standard atomic mass is the closest to the
    ``Mass[amu]`` value, within 0.1 amu.

    Args:
        label (str): fragment label.
        mass (float): ``Mass[amu]`` value.

    Returns:
        str | None: the chemical symbol, None when none matches.
    """
    if label in chemical_symbols[1:]:
        return label
    best = min(range(1, len(atomic_masses)),
               key=lambda number: abs(atomic_masses[number] - mass))
    if abs(atomic_masses[best] - mass) <= 0.1:
        return chemical_symbols[best]
    return None


@dataclass(frozen=True)
class HeaderKey:
    """A global MESS keyword read from the header of the input files.

    Attributes:
        label: keyword as written in MESS (e.g. ``'WellCutoff'``).
        sop_attr: attribute storing the value, on ``SOP`` for global keys
            (one value for every PES), on ``PesFileData`` for per-PES keys
            (also on ``SOP`` for those in ``_SOP_FALLBACK_ATTRS``).
        kind: how the value is read and compared: ``'number'`` (float),
            ``'energy'`` (float in kcal/mol after unit conversion),
            ``'word'`` (string, compared case-folded), ``'length'``
            ((value, unit) pair) or ``'flag_number'`` (float, the bare
            keyword meaning 0.0).
    """
    label: str
    sop_attr: str
    kind: str


#: Global keys: one value for every PES. A different value in two files
#: stops the read. A key present in some files only does not stop it: its
#: value holds for every PES, and its line (as written in the first file
#: carrying it) is added to the templates of the files without it.
SAME_IN_ALL_FILES_KEYS: tuple[HeaderKey, ...] = (
    HeaderKey('CalculationMethod', 'calculation_method', 'word'),
    HeaderKey('EnergyStepOverTemperature', 'ene_step_over_temp', 'number'),
    HeaderKey('ExcessEnergyOverTemperature', 'excess_ene_temp', 'number'),
    HeaderKey('ChemicalEigenvalueMax', 'chem_eig_max', 'number'),
    HeaderKey('ExponentCutoff', 'exp_cutoff', 'number'),
    HeaderKey('ReductionMethod', 'reduction_method', 'word'),
    HeaderKey('GroundEnergyShiftMax', 'ground_ene_shift_max', 'energy'),
    HeaderKey('FloatType', 'float_type', 'word'),
)

#: Keys kept per input file (never compared): each file is written back
#: with its own value, or without the key.
PER_PES_KEYS: tuple[HeaderKey, ...] = (
    HeaderKey('ModelEnergyLimit', 'model_ene_limit', 'energy'),
    HeaderKey('AtomDistanceMin', 'atom_distance_min', 'length'),
    HeaderKey('WellExtension', 'well_extension', 'flag_number'),
    HeaderKey('WellCutoff', 'well_cutoff', 'number'),
    HeaderKey('WellReductionThreshold', 'well_reduction_threshold',
              'number'),
)

#: Per-PES keys whose value is also stored on the SOP: the value of the
#: first file carrying the key (fallback for SOPs without per-file data).
_SOP_FALLBACK_ATTRS: tuple[str, ...] = (
    'model_ene_limit', 'well_cutoff', 'well_reduction_threshold')

#: Where a missing global line is added into a template (see
#: ``SAME_IN_ALL_FILES_KEYS``): {key label: (anchor keyword, True to insert
#: right after the anchor line, False right before it)}. Keys of the global
#: section go before ``Model`` (at the top of the template when there is no
#: ``Model`` line); ``GroundEnergyShiftMax`` is a key of the ``Model``
#: section; MESS reads ``ExponentCutoff`` inside the ``Exponential``
#: energy-transfer kernel (MESS ``libmess/model.cc``).
_MISSING_LINE_ANCHORS: dict[str, tuple[str, bool]] = {
    'CalculationMethod': ('Model', False),
    'EnergyStepOverTemperature': ('Model', False),
    'ExcessEnergyOverTemperature': ('Model', False),
    'ChemicalEigenvalueMax': ('Model', False),
    'ReductionMethod': ('Model', False),
    'FloatType': ('Model', False),
    'GroundEnergyShiftMax': ('Model', True),
    'ExponentCutoff': ('Exponential', True),
}

#: MESS output-file keywords and the ``{__output__.<kind>}`` placeholder
#: kind the template gets instead of the file name (each written input
#: names its own side outputs).
OUTPUT_NAME_KEYS: dict[str, str] = {
    'rateoutput': 'rate',
    'pedoutput': 'ped',
    'microrateoutput': 'micro',
}

#: Microcanonical output keys (per PES), index in PesFileData.micro_ener
MICRO_ENER_KEYS: dict[str, int] = {
    'microenermin': 0,
    'microenermax': 1,
    'microenerstep': 2,
}


class ColliderLine:
    """One Lennard-Jones line (``Epsilons``, ``Sigmas`` or ``Masses``)
    followed across the input files.

    The first value of the line is the collider (bath gas): it must be the
    same in every file. The second value is PES-specific.

    Attributes:
        label: keyword (e.g. ``'Epsilons'``).
        token: keyword token with its unit, case-folded, of the first file
            having the line (e.g. ``'epsilons[1/cm]'``).
        collider: first value of the first file having the line.
        second_by_file: second value of each file, keyed by file index.
    """

    def __init__(self, label: str) -> None:
        self.label: str = label
        self.token: str | None = None
        self.collider: float | None = None
        self.second_by_file: dict[int, float] = {}


class PesEnergyAlignment:
    """Align the energies of MESS input files that share items.

    Each input file has its own energy zero. An item read from several
    files (same label) fixes the offset between their zeros:
    ``offset[g] = offset[f] + E_g - E_f``. Files are visited in
    ``mess_inputs`` order; the first file of each group of linked files is
    the reference of the group (offset 0); a file sharing nothing keeps
    offset 0. After alignment every shared energy must agree within
    ``TOLERANCE``.

    Attributes:
        n_files: number of input files.
        energies: raw energy of each item in each file that declares it,
            ``{label: {file index: kcal/mol}}``.
        anchors: labels used to link files (wells, bimoleculars, saddle
            points); the other labels are only checked.
        offsets: offset of each file (kcal/mol), filled by ``solve``.
        links: item that linked each non-reference file to its group.
    """

    #: Largest difference (kcal/mol) allowed between two aligned energies
    TOLERANCE = 0.01

    def __init__(self,
                 n_files: int,
                 energies: dict[str, dict[int, float]],
                 anchors: set[str]) -> None:
        self.n_files: int = n_files
        self.energies: dict[str, dict[int, float]] = energies
        self.anchors: set[str] = anchors
        self.offsets: dict[int, float] = {}
        self.links: dict[int, str] = {}

    def _neighbours(self) -> dict[int, list[tuple[int, str]]]:
        """Files linked by a shared anchor, for each file."""
        graph: dict[int, list[tuple[int, str]]] = {
            fid: [] for fid in range(self.n_files)}
        for label, per_file in self.energies.items():
            if label not in self.anchors or len(per_file) < 2:
                continue
            files = sorted(per_file)
            for first in files:
                for second in files:
                    if first != second:
                        graph[first].append((second, label))
        return graph

    def solve(self) -> dict[int, float]:
        """Compute the offset of every file (breadth-first over the files
        linked by shared anchors).

        Returns:
            dict[int, float]: offset (kcal/mol) of each file index.
        """
        graph = self._neighbours()
        self.offsets = {}
        for start in range(self.n_files):
            if start in self.offsets:
                continue
            self.offsets[start] = 0.0
            queue: deque[int] = deque([start])
            while queue:
                current = queue.popleft()
                for other, label in graph[current]:
                    if other in self.offsets:
                        continue
                    per_file = self.energies[label]
                    self.offsets[other] = (self.offsets[current]
                                           + per_file[other]
                                           - per_file[current])
                    self.links[other] = label
                    queue.append(other)
        return self.offsets

    def mismatches(self) -> list[tuple[str, int, int, float]]:
        """Shared energies that disagree after alignment.

        Returns:
            list[tuple[str, int, int, float]]: (label, first file, other
            file, difference in kcal/mol) for every disagreement larger
            than ``TOLERANCE``.
        """
        found: list[tuple[str, int, int, float]] = []
        for label, per_file in self.energies.items():
            files = sorted(per_file)
            first = files[0]
            reference = per_file[first] - self.offsets[first]
            for other in files[1:]:
                diff = per_file[other] - self.offsets[other] - reference
                if abs(diff) > self.TOLERANCE + 1e-9:
                    found.append((label, first, other, diff))
        return found

    def aligned_energy(self, label: str) -> float:
        """Energy of an item in the aligned frame (from its first file).

        Args:
            label (str): item label.

        Returns:
            float: raw energy in its first file minus that file's offset.
        """
        per_file = self.energies[label]
        first = min(per_file)
        return per_file[first] - self.offsets[first]


# TODO: Make the parsing robust to file swap on
# restart regarding shifted energies

class MessInputReader:
    """Class that read a mess input file and transforms it into
     an object with easily extractable data.

    Several input files (one PES each) are read into a single SOP: items
    with the same label in several files are one object carrying the PES
    id of every file (their data must be identical), energies are aligned
    between files sharing items, global keys are checked or kept per file.
    """
    def __init__(self,
                 settings: dict,
                 mechanism_species: list[str],
                 klog: KMOLogger,
                 postprocess: bool = False) -> None:
        """Save the file content as a string for further manipulation

        Args:
            settings (dict): Content of the input file
                             with additional default parameters
        """
        self.klog: KMOLogger = klog
        self.filenames: list[str] = []
        for mess_input in settings['mess_inputs']:
            if os.path.isabs(mess_input):
                resolved_path = os.path.abspath(mess_input)
            else:
                resolved_path = os.path.abspath(
                    os.path.join(settings['init_loc'], mess_input)
                )
            self.filenames.append(resolved_path)
        n_exp = settings.get('n_exp')
        if n_exp is None:
            n_exp = len(settings.get('experiments', []))
        if n_exp <= 0:
            self.klog.error("Number of experiments must be positive.")
            sys.exit(1)
        self.SOP: SOP = SOP(n_exp=n_exp)

        if postprocess:
            self.SOP.temp = settings["pp_temp"]
            self.SOP.pres = settings["pp_pres"]
        else:
            self.SOP.temp = settings.get("rc_temp", [])
            self.SOP.pres = settings.get("rc_pres", [])
        self.SOP.pres_unit = 'bar'
        self.klog: KMOLogger = klog
        self.mechanism_species: list[str] = mechanism_species
        self.force_new_molecules: bool = settings['force_new_molecules']
        # Prompt (non-thermal) reactions requested: the read then checks
        # that the PEDSpecies products of a file are HotEnergies species of
        # another file (_check_prompt_links).
        self.prompt_reactions: bool = bool(
            settings.get('prompt_reactions', False))
        self.files2copy: list[str] = []
        self.pes_files: list[list[str]] = []
        for filename in self.filenames:
            if os.path.isfile(path=filename):
                with open(file=filename, mode='r') as f:
                    self.pes_files.append(f.readlines())
            else:
                raise FileNotFoundError(
                    f'Mess input file {filename} not found.'
                )

        self.tpls: list[list[str]] = []
        # Set to true if a species from MESS input is not present
        # in the mechanism file and 'force_new_molecules' is False,
        # or if the input files are not consistent with each other,
        # to trigger the stop of the program after reading the input file.
        self._trigger_stop = False
        # Raw energy (kcal/mol) of each item in each file declaring it:
        # {label: {file index: energy}}, aligned after all files are read.
        self._file_energies: dict[str, dict[int, float]] = {}
        # File index where each label was first read (error messages).
        self._first_file: dict[str, int] = {}
        # Items read again (another file, another bimolecular, same
        # bimolecular twice) are parsed into throwaway copies held by this
        # scratch SOP, then compared with the stored item:
        # {label: (stored item or None when not compared, copy)}.
        self._scratch: SOP = SOP(n_exp=1)
        self._rereads: dict[str, tuple[Any, Any]] = {}
        # Input files in which each checked global key appears.
        self._key_files: dict[str, set[int]] = {}
        # Line of each global key (SAME_IN_ALL_FILES_KEYS label) as written
        # in the first file carrying it: copied into the templates of the
        # files without the key.
        self._key_lines: dict[str, str] = {}
        # Lennard-Jones lines followed across the files.
        self._colliders: dict[str, ColliderLine] = {
            'epsilons': ColliderLine('Epsilons'),
            'sigmas': ColliderLine('Sigmas'),
            'masses': ColliderLine('Masses'),
        }

    def _file_label(self, fid: int) -> str:
        """Name of an input file in messages (its path when known)."""
        if 0 <= fid < len(self.filenames):
            return self.filenames[fid]
        return f'MESS input file #{fid}'

    def _stop(self, msg: str) -> None:
        """Log a consistency error and stop the run after the read."""
        self.klog.error(msg)
        self._trigger_stop = True

    def validate_species(self,
                         species: str,
                         species_type: str) -> None:
        if species in self.mechanism_species or is_fake_well_label(species):
            return
        msg: str = (
            f"{species_type} '{species}' from MESS input is not present "
            "in the mechanism file."
        )
        self.klog.warning(msg)
        if not self.force_new_molecules:
            err = (
                f"{msg} Set 'force_new_molecules' to true to continue "
                "with species from MESS input."
            )
            self.klog.error(err)
            self._trigger_stop = True

    def _reject_dbs_in_name(self, name: str, item_type: str) -> bool:
        if dbs in name:
            err = (
                f"{item_type} name '{name}' from MESS input contains the "
                f"reserved separator '{dbs}'."
            )
            self.klog.error(err)
            self._trigger_stop = True
            return True
        return False

    # ------------------------------------------------------------------
    # Items read again: throwaway copies compared with the stored item
    # ------------------------------------------------------------------
    def _target_sop(self, name: str) -> SOP:
        """SOP receiving the data of item ``name``: the scratch SOP while
        the item is read again, the real SOP otherwise."""
        if name in self._rereads:
            return self._scratch
        return self.SOP

    def _target_item(self, name: str) -> Any:
        """Object receiving the data of item ``name`` (see _target_sop)."""
        return self._target_sop(name).items[name]

    def _lookup(self, name: str) -> Any:
        """Object receiving the data of item ``name``, None if unknown."""
        return self._target_sop(name).items.get(name)

    def _open_reread(self,
                     name: str,
                     stored: Any,
                     copy: Any) -> None:
        """Start reading item ``name`` again into ``copy``.

        Args:
            name (str): item label.
            stored: item already in the SOP to compare with, or None to
                discard the copy without comparison (after an error).
            copy: fresh object receiving the data read now.
        """
        if name in self._rereads:
            self._close_reread(name, len(self.tpls) - 1)
        self._scratch.items[name] = copy
        self._rereads[name] = (stored, copy)

    def _close_reread(self, name: str, fid: int) -> None:
        """Compare a re-read copy with the stored item and drop it.

        Any difference stops the read (identical labels must describe
        identical items).
        """
        stored, copy = self._rereads.pop(name)
        self._scratch.items.pop(name, None)
        if stored is None:
            return
        fields = stored.differing_fields(copy)
        if fields:
            first = self._first_file.get(name, fid)
            self._stop(
                f"{type(stored).__name__} {name} differs between "
                f"{self._file_label(first)} and {self._file_label(fid)} "
                f"in: {', '.join(fields)}.")

    def _flush_rereads(self, fid: int) -> None:
        """Compare and drop every open re-read copy (at each new item block
        and at the end of each file)."""
        for name in list(self._rereads):
            self._close_reread(name, fid)

    # ------------------------------------------------------------------
    # Global keys of the header
    # ------------------------------------------------------------------
    def _energy_in_kcal(self,
                        value: float,
                        unit: str,
                        label: str,
                        fid: int) -> float:
        """Convert a header energy to kcal/mol.

        Args:
            value (float): value read.
            unit (str): unit between brackets, case-folded ('' if none).
            label (str): keyword (messages).
            fid (int): file index (messages).

        Returns:
            float: the value in kcal/mol, the raw value for an unknown unit
            (with a warning).
        """
        if unit == '1/cm':
            return value / _CM2KCAL
        if unit == 'kj/mol':
            return value / _KJ2KCAL
        if unit in ('', 'kcal/mol'):
            return value
        msg = f"Unknown {label} unit '{unit}'"
        msg += f" in {self._file_label(fid)};"
        msg += " raw value stored."
        self.klog.warning(msg)
        return value

    @staticmethod
    def _unit_of(line: str) -> str:
        """Unit between brackets of the keyword, case-folded ('' if none)."""
        key = line.split()[0].casefold()
        if '[' in key and ']' in key:
            return key.split('[')[1].split(']')[0]
        return ''

    def _key_value(self,
                   key: HeaderKey,
                   line: str,
                   fid: int) -> Any:
        """Value of a header key line, in the form of ``key.kind``.

        Returns:
            The value, or None when the line has no readable value (an
            error is logged and the read stops).
        """
        tokens = line.split()
        if key.kind == 'flag_number' and (
                len(tokens) < 2 or tokens[1].startswith(('!', '#'))):
            return 0.0
        if len(tokens) < 2:
            self._stop(f"{key.label} has no value in "
                       f"{self._file_label(fid)}.")
            return None
        if key.kind == 'word':
            return tokens[1]
        try:
            value = float(tokens[1])
        except ValueError:
            self._stop(f"{key.label} value '{tokens[1]}' is not a number "
                       f"in {self._file_label(fid)}.")
            return None
        if key.kind == 'energy':
            return self._energy_in_kcal(
                value, self._unit_of(line), key.label, fid)
        if key.kind == 'length':
            return (value, self._unit_of(line))
        return value

    @staticmethod
    def _same_value(key: HeaderKey, first: Any, other: Any) -> bool:
        """Compare two values of a same-in-all-files key (words
        case-folded, numbers after unit conversion)."""
        if key.kind == 'word':
            return str(first).casefold() == str(other).casefold()
        return math.isclose(first, other, rel_tol=1e-9, abs_tol=1e-12)

    def _read_header_key(self,
                         token: str,
                         line: str,
                         fid: int,
                         tpl: list[str]) -> bool:
        """Handle a global header line identified by its exact keyword.

        Args:
            token (str): keyword from ``_header_token``.
            line (str): the line.
            fid (int): file index.
            tpl (list[str]): template of the file.

        Returns:
            bool: True when the line was handled (and added to the
            template), False when the keyword is not a header key.
        """
        for key in SAME_IN_ALL_FILES_KEYS:
            if token == key.label.casefold():
                self._key_files.setdefault(key.label, set()).add(fid)
                self._key_lines.setdefault(key.label, line)
                value = self._key_value(key, line, fid)
                saved = getattr(self.SOP, key.sop_attr)
                if value is None:
                    pass
                elif saved is None:
                    setattr(self.SOP, key.sop_attr, value)
                elif not self._same_value(key, saved, value):
                    msg = f"Different {key.label}"
                    msg += f" in {self._file_label(fid)}."
                    msg += "\n"
                    msg += f" Saved value: {saved}."
                    self.klog.warning(msg)
                    self._trigger_stop = True
                tpl.append(line)
                return True
        for key in PER_PES_KEYS:
            if token == key.label.casefold():
                value = self._key_value(key, line, fid)
                if value is not None:
                    setattr(self.SOP.file_data(fid), key.sop_attr, value)
                    if (key.sop_attr in _SOP_FALLBACK_ATTRS
                            and getattr(self.SOP, key.sop_attr) is None):
                        setattr(self.SOP, key.sop_attr, value)
                tpl.append(line)
                return True
        if token == 'pedspecies':
            species: list[str] = []
            for arg in line.split()[1:]:
                if arg.startswith(('!', '#')):
                    break
                species.append(arg)
            self.SOP.file_data(fid).ped_species = species
            tpl.append(line)
            return True
        if token in MICRO_ENER_KEYS:
            tokens = line.split()
            numbers = _leading_numbers(tokens[1:2])
            tpl.append(line)
            if not numbers:
                self._stop(f"{tokens[0]} has no value in "
                           f"{self._file_label(fid)}.")
                return True
            value = self._energy_in_kcal(
                numbers[0], self._unit_of(line), tokens[0].split('[')[0],
                fid)
            data = self.SOP.file_data(fid)
            micro = list(data.micro_ener or (None, None, None))
            micro[MICRO_ENER_KEYS[token]] = value
            data.micro_ener = (micro[0], micro[1], micro[2])
            return True
        if token in OUTPUT_NAME_KEYS:
            tpl.append(line.split()[0] + " {" + OUTPUT_NAME_ROOT + "."
                       + OUTPUT_NAME_KEYS[token] + "}\n")
            return True
        return False

    def _read_hot_energies(self,
                           line: str,
                           lnum: int,
                           fid: int,
                           tpl: list[str]) -> int:
        """Read a ``HotEnergies`` block into ``PesFileData.hot_energies``.

        MESS grammar (``mess_driver.cc``): ``HotEnergies[<unit>] N``, unit
        kcal/mol, 1/cm or kJ/mol, then N species lines ``<well> <token>``,
        token = one energy or a range ``start<sep>step<sep>finish`` (sep:
        one of ``:;,&%$@#``). Blank and comment lines are skipped, ``End``
        ends the block early. The energies are stored in kcal/mol, as read
        (this file's energy zero), and the whole block is replaced in the
        template by ``{SOP.r_hot_energies_pes[<fid>]}``.

        Any error stops the read (one message naming HotEnergies and the
        file); the lines read so far are then kept verbatim in the template
        and the offending line is left to the main loop.

        Args:
            line (str): the ``HotEnergies`` key line.
            lnum (int): its line number in the file.
            fid (int): file index.
            tpl (list[str]): template of the file.

        Returns:
            int: number of lines after the key line consumed by the block
            (skipped by the main loop).
        """
        where = f"HotEnergies of {self._file_label(fid)}"
        unit = self._unit_of(line)
        if unit not in HOT_ENERGY_UNITS:
            self._stop(
                f"{where}: '{line.split()[0]}' has no accepted unit; MESS "
                "reads HotEnergies[kcal/mol], HotEnergies[1/cm] or "
                "HotEnergies[kJ/mol].")
            tpl.append(line)
            return 0
        tokens = line.split()
        count_token = tokens[1] if len(tokens) > 1 else ''
        try:
            count = int(count_token)
        except ValueError:
            count = 0
        if count <= 0:
            self._stop(f"{where}: the number of species '{count_token}' "
                       "is not a positive integer.")
            tpl.append(line)
            return 0
        energies: dict[str, tuple[float, ...]] = {}
        # Lines of the block read so far (kept verbatim on error)
        block_lines: list[str] = []
        n_species = 0
        error: str | None = None
        for block_line in self.pes_files[fid][lnum + 1:]:
            if n_species == count:
                break
            # Words of the line before any comment
            words: list[str] = []
            for word in block_line.split():
                if word.startswith(('!', '#')):
                    break
                words.append(word)
            if not words:
                block_lines.append(block_line)
                continue
            if words[0].casefold() == 'end':
                block_lines.append(block_line)
                break
            name = words[0]
            if len(words) == 1:
                error = (f"{where}: no energy given for {name} (species "
                         f"line {n_species + 1} of the {count} announced).")
                break
            if len(words) > 2:
                error = (f"{where}: {name} has {len(words) - 1} energy "
                         "tokens; give one energy or one start:step:finish "
                         "range per species line.")
                break
            if name in energies:
                error = f"{where}: {name} is given twice."
                break
            try:
                energies[name] = self._hot_energy_values(words[1], unit, fid)
            except ValueError as exc:
                error = f"{where}: {name}: {exc}"
                break
            block_lines.append(block_line)
            n_species += 1
        data = self.SOP.file_data(fid)
        if error is None and n_species != count:
            error = (f"{where}: {count} species announced but "
                     f"{n_species} species lines read.")
        if error is None and data.hot_energies is not None:
            error = f"{where}: the file holds two HotEnergies blocks."
        if error is not None:
            self._stop(error)
            tpl.append(line)
            tpl.extend(block_lines)
            return len(block_lines)
        data.hot_energies = energies
        tpl.append("{SOP.r_hot_energies_pes[" + str(fid) + "]}\n")
        return len(block_lines)

    def _hot_energy_values(self,
                           token: str,
                           unit: str,
                           fid: int) -> tuple[float, ...]:
        """Energies of one ``HotEnergies`` species line, in kcal/mol.

        Args:
            token (str): one energy, or ``start<sep>step<sep>finish``.
            unit (str): unit of the block (one of ``HOT_ENERGY_UNITS``).
            fid (int): file index (messages).

        Returns:
            tuple[float, ...]: ``(value,)`` or ``(start, step, finish)``.

        Raises:
            ValueError: the token is not an energy or a valid range (the
                message explains why).
        """
        parts = re.split('[' + re.escape(_HOT_RANGE_SEPARATORS) + ']', token)
        if len(parts) == 2:
            raise ValueError(
                f"'{token}' has one separator; a range is "
                "start<sep>step<sep>finish.")
        if len(parts) > 3 or not all(_is_number(part) for part in parts):
            raise ValueError(f"'{token}' is not an energy or a "
                             "start<sep>step<sep>finish range.")
        values = tuple(
            self._energy_in_kcal(float(part), unit, 'HotEnergies', fid)
            for part in parts)
        if len(values) == 3:
            start, step, finish = values
            if step <= 0.0:
                raise ValueError(f"the step of '{token}' must be positive.")
            if finish < start:
                raise ValueError(f"the range '{token}' holds no energy "
                                 "(finish below start).")
        return values

    def _check_hot_species(self, fid: int) -> None:
        """Stop when a ``HotEnergies`` species of file ``fid`` is not a Well
        of that file.

        A well of this file that is also a bimolecular fragment in another
        file (one shared item) is accepted.

        Args:
            fid (int): file index (called once the file is read).
        """
        hot_energies = self.SOP.file_data(fid).hot_energies
        if not hot_energies:
            return
        wells_here = self.SOP.wells_in(fid)
        for name in hot_energies:
            item = self.SOP.items.get(name)
            if not any(well is item for well in wells_here):
                self._stop(f"HotEnergies species {name} of "
                           f"{self._file_label(fid)} is not a Well of this "
                           "file.")

    def _read_collider_line(self,
                            kind: str,
                            line: str,
                            fid: int,
                            tpl: list[str]) -> None:
        """Read an ``Epsilons`` or ``Sigmas`` line.

        The first number is the collider value (same in every file), the
        second one is PES-specific: file ``fid`` stores it at index
        ``fid + 1`` of ``SOP.epsilons``/``SOP.sigmas`` (assembled after all
        files are read). Further numbers are a comment (MESS reads two).

        Args:
            kind (str): 'epsilons' or 'sigmas'.
            line (str): the line.
            fid (int): file index.
            tpl (list[str]): template of the file.
        """
        collider = self._colliders[kind]
        self._key_files.setdefault(collider.label, set()).add(fid)
        tokens = line.split()
        token = tokens[0].casefold()
        numbers = _leading_numbers(tokens[1:])
        if len(numbers) < 2:
            self._stop(
                f"{collider.label} needs two values (collider, then the "
                f"value of this PES) in {self._file_label(fid)}: "
                f"{line.strip()}")
            tpl.append(line)
            return
        if collider.token is not None and token != collider.token:
            self._stop(
                f"{collider.label} is given as '{tokens[0]}' in "
                f"{self._file_label(fid)} but as '{collider.token}' in the "
                "first file: use the same unit in every file.")
            tpl.append(line)
            return
        if collider.collider is None:
            collider.collider = numbers[0]
            collider.token = token
        elif numbers[0] != collider.collider:
            msg = f"Different {kind[:-1]} 0 (collider)"
            msg += f" in {self._file_label(fid)}."
            msg += "\n"
            msg += f" Saved value: {collider.collider}."
            self.klog.warning(msg)
            self._trigger_stop = True
            tpl.append(line)
            return
        collider.second_by_file[fid] = numbers[1]
        tpl.append(tokens[0] + " {SOP.r_" + kind + "_pes[" + str(fid)
                   + "]}\n")

    def _read_masses_line(self,
                          line: str,
                          fid: int,
                          tpl: list[str]) -> None:
        """Read a ``Masses[amu]`` line: the first value (collider) must be
        the same in every file, the others are kept per PES."""
        collider = self._colliders['masses']
        self._key_files.setdefault(collider.label, set()).add(fid)
        tpl.append(line)
        masses = _leading_numbers(line.split()[1:])
        self.SOP.file_data(fid).masses = masses
        if not masses:
            return
        if collider.collider is None:
            collider.collider = masses[0]
            self.SOP.masses = masses
        elif masses[0] != collider.collider:
            msg = "Different bath mass (collider, first value of"
            msg += f" Masses[amu]) in {self._file_label(fid)}."
            msg += "\n"
            msg += " Saved value:"
            msg += f" {collider.collider}."
            self.klog.warning(msg)
            self._trigger_stop = True
        elif masses != self.SOP.masses:
            self.klog.info(
                f"Masses[amu] {masses} of {self._file_label(fid)} kept for "
                "this PES (the first value, the collider, is the same in "
                "every file).")

    def _check_presence(self) -> None:
        """Stop when a collision-model line (``Factor``, ``Power``,
        ``Epsilons``, ``Sigmas``, ``Masses``) is in some files only.

        The global keys of ``SAME_IN_ALL_FILES_KEYS`` may be in some files
        only (see ``_add_missing_global_lines``).
        """
        n_files = len(self.pes_files)
        labels = ['Factor', 'Power', 'Epsilons', 'Sigmas', 'Masses']
        for label in labels:
            present = self._key_files.get(label, set())
            if 0 < len(present) < n_files:
                absent = [self._file_label(fid) for fid in range(n_files)
                          if fid not in present]
                found = [self._file_label(fid) for fid in sorted(present)]
                self._stop(
                    f"{label} is set in {', '.join(found)} but absent from "
                    f"{', '.join(absent)}: it must be in every MESS input "
                    "file or in none.")

    def _add_missing_global_lines(self) -> None:
        """Use a global key read in some files only for every PES.

        For each key of ``SAME_IN_ALL_FILES_KEYS`` present in some files
        only, its line as written in the first file carrying it is added to
        the template of every file without it (see
        ``_MISSING_LINE_ANCHORS`` for the place), so that the template path
        computes every PES with the same value as the automech path. One
        info message per completed file.
        """
        n_files = len(self.pes_files)
        added: dict[int, list[str]] = {}
        for key in SAME_IN_ALL_FILES_KEYS:
            present = self._key_files.get(key.label, set())
            if not present or len(present) == n_files:
                continue
            line = self._key_lines[key.label]
            if not line.endswith('\n'):
                line += '\n'
            for fid in range(n_files):
                if fid in present:
                    continue
                if self._insert_global_line(key.label, line, fid):
                    added.setdefault(fid, []).append(line.strip())
        for fid, lines in added.items():
            self.klog.info(
                f"Global keys absent from {self._file_label(fid)} are "
                "taken from the other MESS inputs (one value for every "
                f"PES) and added to its template: {'; '.join(lines)}.")

    def _insert_global_line(self,
                            label: str,
                            line: str,
                            fid: int) -> bool:
        """Insert the line of a global key into the template of one file.

        Args:
            label (str): key label (``SAME_IN_ALL_FILES_KEYS``).
            line (str): line to insert (ends with a newline).
            fid (int): index of the file lacking the key.

        Returns:
            bool: True when inserted; False when the template has no line
            to anchor a key of the ``Model`` section to (the read stops).
        """
        anchor, after = _MISSING_LINE_ANCHORS[label]
        tpl = self.tpls[fid]
        position = next(
            (idx for idx, tpl_line in enumerate(tpl)
             if _header_token(tpl_line) == anchor.casefold()), None)
        if position is None and after:
            found = [self._file_label(other) for other in
                     sorted(self._key_files.get(label, set()))]
            self._stop(
                f"{label} is set in {', '.join(found)} but absent from "
                f"{self._file_label(fid)}, which has no {anchor} line to "
                "add it to.")
            return False
        if position is None:
            position = 0
        elif after:
            position += 1
        tpl.insert(position, line)
        return True

    def _assemble_lennard_jones(self) -> None:
        """Build SOP.epsilons and SOP.sigmas: collider first, then the
        second value of each file at index file + 1."""
        n_files = len(self.pes_files)
        for kind in ('epsilons', 'sigmas'):
            collider = self._colliders[kind]
            if collider.collider is None:
                continue
            files = sorted(collider.second_by_file)
            if files == list(range(n_files)):
                values = [collider.collider]
                values += [collider.second_by_file[fid]
                           for fid in range(n_files)]
            else:
                # Some file lacks the line (the read already stops).
                values = [collider.collider]
                values += [collider.second_by_file[fid] for fid in files]
            setattr(self.SOP, kind, values)

    # ------------------------------------------------------------------
    # Item blocks
    # ------------------------------------------------------------------
    def _open_well(self, name: str, fid: int) -> None:
        """Handle a ``Well <name>`` line."""
        existing = self.SOP.items.get(name)
        if existing is None:
            self.validate_species(species=name, species_type='Well')
            self.SOP.add_new_well(name=name, pes_id=fid)
            self._first_file[name] = fid
            return
        copy = Well(name=name, pes_ids=[fid])
        if isinstance(existing, (Barrier, Bimolecular)):
            self._stop(
                f"Label {name} names a {type(existing).__name__} in "
                f"{self._file_label(self._first_file.get(name, fid))} and "
                f"a Well in {self._file_label(fid)}.")
            self._open_reread(name, None, copy)
            return
        if self.SOP.check_well(name=name, pes_id=fid):
            self._stop(
                f"Well {name} is declared twice in {self._file_label(fid)}.")
            self._open_reread(name, None, copy)
            return
        self.klog.info(f"Well {name} is shared by several MESS inputs "
                       f"(PES ids {existing.pes_ids}).")
        self._open_reread(name, existing, copy)

    def _open_bimolecular(self, name: str, fid: int) -> None:
        """Handle a ``Bimolecular <name>`` line."""
        existing = self.SOP.items.get(name)
        if existing is None:
            self.SOP.add_new_bimol(name=name, pes_id=fid)
            self._first_file[name] = fid
            return
        copy = Bimolecular(name=name, pes_ids=[fid])
        if not isinstance(existing, Bimolecular):
            self._stop(
                f"Label {name} names a {type(existing).__name__} in "
                f"{self._file_label(self._first_file.get(name, fid))} and "
                f"a Bimolecular in {self._file_label(fid)}.")
            self._open_reread(name, None, copy)
            return
        if fid in existing.pes_ids:
            msg: str = f"Multiple Bimolecular {name} exist"
            msg += f" in {self._file_label(fid)}."
            self.klog.warning(msg)
            self._trigger_stop = True
            self._open_reread(name, None, copy)
            return
        self.SOP.add_new_bimol(name=name, pes_id=fid)
        self.klog.info(f"Bimolecular {name} is shared by several MESS "
                       f"inputs (PES ids {existing.pes_ids}).")
        self._open_reread(name, existing, copy)

    def _barrier_sides_in_file(self,
                               name: str,
                               sides: tuple[str, str],
                               fid: int) -> bool:
        """Check that both sides of a barrier are declared in its file."""
        ok = True
        for side in sides:
            item = self.SOP.items.get(side)
            if item is None or fid not in item.pes_ids:
                self._stop(
                    f"Barrier {name} connects {side}, which is not a Well or "
                    f"Bimolecular declared in {self._file_label(fid)}.")
                ok = False
        return ok

    def _open_barrier(self,
                      name: str,
                      lside: str,
                      rside: str,
                      fid: int) -> None:
        """Handle a ``Barrier <name> <lside> <rside>`` line."""
        existing = self.SOP.items.get(name)
        sides_ok = self._barrier_sides_in_file(name, (lside, rside), fid)
        if existing is None and sides_ok:
            self.SOP.add_new_barrier(name=name, lside=lside, rside=rside,
                                     pes_id=fid)
            self._first_file[name] = fid
            return
        if isinstance(existing, Barrier):
            copy = Barrier(name=name,
                           lside=existing.connected[0],
                           rside=existing.connected[1],
                           pes_id=fid)
        else:
            copy = Barrier(name=name,
                           lside=Well(name=lside, pes_ids=[]),
                           rside=Well(name=rside, pes_ids=[]),
                           pes_id=fid)
        if existing is None or not sides_ok:
            self._open_reread(name, None, copy)
            return
        if not isinstance(existing, Barrier):
            self._stop(
                f"Label {name} names a {type(existing).__name__} in "
                f"{self._file_label(self._first_file.get(name, fid))} and "
                f"a Barrier in {self._file_label(fid)}.")
            self._open_reread(name, None, copy)
            return
        stored_sides = (existing.connected[0].name,
                        existing.connected[1].name)
        if stored_sides != (lside, rside):
            self._stop(
                f"Barrier {name} connects {stored_sides[0]} and "
                f"{stored_sides[1]} in "
                f"{self._file_label(self._first_file.get(name, fid))} but "
                f"{lside} and {rside} in {self._file_label(fid)}.")
            self._open_reread(name, None, copy)
            return
        if self.SOP.check_barrier(name=name, pes_id=fid):
            self._stop(f"Barrier {name} is declared twice in "
                       f"{self._file_label(fid)}.")
            self._open_reread(name, None, copy)
            return
        self.klog.info(f"Barrier {name} is shared by several MESS inputs "
                       f"(PES ids {existing.pes_ids}).")
        self._open_reread(name, existing, copy)

    def _open_fragment(self,
                       bimol_name: str,
                       fname: str,
                       density: bool,
                       fid: int) -> None:
        """Handle a ``Fragment <fname> [density]`` line of a bimolecular."""
        # Fresh object receiving the fragment data when the label was read
        # before (compared with it) or after an error (discarded).
        copy = Well(name=fname, pes_ids=[])
        bim = self._lookup(bimol_name)
        if not isinstance(bim, Bimolecular):
            msg = f"Cannot add a fragment to non-bimol {bimol_name}."
            msg += "\n"
            msg += f"Error in {self._file_label(fid)}."
            self.klog.warning(msg=msg)
            self._trigger_stop = True
            self._open_reread(fname, None, copy)
            return
        if len(bim.fragments) >= 2:
            self.klog.warning(
                f"Bimol{bimol_name} already has two fragments. "
                f"Cannot add fragment {fname}.")
            self._trigger_stop = True
            self._open_reread(fname, None, copy)
            return
        existing = self.SOP.items.get(fname)
        if existing is None and bimol_name in self._rereads:
            # The bimolecular is read again and this fragment is unknown:
            # the slot difference is reported when the bimolecular copy is
            # compared with the stored one.
            bim.attach_fragment(copy, density=density)
            self._open_reread(fname, None, copy)
            return
        if existing is None:
            self.validate_species(species=fname, species_type='Fragment')
            # Fragments don't get a pes_id because they are not part of
            # the same pes as the bimol
            bim.add_new_frag(fname, density=density)
            self.SOP.items[fname] = bim.fragments[-1]
            self._first_file[fname] = fid
            return
        if isinstance(existing, Barrier):
            msg = f"Fragment {fname} points to a barrier object."
            self.klog.warning(msg)
            self._trigger_stop = True
            self._open_reread(fname, None, copy)
            return
        if not isinstance(existing, Well):
            msg = f"Fragment {fname} is not a well object."
            self.klog.warning(msg)
            self._trigger_stop = True
            self._open_reread(fname, None, copy)
            return
        if fname not in bim.frag_names and bimol_name not in self._rereads:
            self.validate_species(species=fname, species_type='Fragment')
        # The same species object fills the slot (shared fragment, or the
        # same fragment twice in one bimolecular); its data is read again
        # and compared.
        bim.attach_fragment(existing, density=density)
        self._open_reread(fname, existing, copy)

    def read(self) -> tuple[SOP, list[list[str]]]:
        """Reads a mess input file and transforms it into a
        SetOfParameter object and a mess_template file.

        Returns:
            list[SOP, list[list[str]]]:
            [SetOfParameters, mess_templates]
        """
        name = ''
        fname = ''
        last_item = ''
        skip = 0
        for fid, file in enumerate(self.pes_files):
            self.tpls.append(MessTemplate(pes_id=fid))
            tpl: list[str] = self.tpls[-1]
            self.SOP.file_data(fid)
            for lnum, line in enumerate(file):

                # Avoid writing data in template
                if skip:
                    skip -= 1
                    continue

                # Global keys identified by their exact keyword
                token = _header_token(line)
                # HotEnergies block: the key line and its species lines
                if token == 'hotenergies':
                    skip += self._read_hot_energies(line, lnum, fid, tpl)
                    continue
                if token is not None and self._read_header_key(
                        token, line, fid, tpl):
                    continue

                # General parameters

                if line.lstrip().casefold().startswith('temperaturelist'):
                    # self.save_temperatures(lnum=lnum)
                    tpl.append(line.split()[0] + " {SOP.r_rc_temp}\n")
                    continue
                elif line.lstrip().casefold().startswith('pressurelist'):
                    # self.save_pressures(lnum=lnum)
                    tpl.append(
                        "PressureList[{SOP.pres_unit}] {SOP.r_rc_pres}\n")
                    continue
                elif line.lstrip().casefold().startswith('factor'):
                    self._key_files.setdefault('Factor', set()).add(fid)
                    if not hasattr(self.SOP, "factor"):
                        self.SOP.factor = float(line.split()[1])
                    else:
                        if self.SOP.factor != float(line.split()[1]):
                            self.klog.warning(
                                f"Different factor in {self._file_label(fid)}.\
                                Using the first one encountered: "
                                f"{self.SOP.factor}."
                            )
                            self._trigger_stop = True
                    tpl.append(line.split()[0] + " {SOP.factor}\n")
                    continue
                elif line.lstrip().casefold().startswith('power'):
                    self._key_files.setdefault('Power', set()).add(fid)
                    if not hasattr(self.SOP, "power"):
                        self.SOP.power = float(line.split()[1])
                    else:
                        if self.SOP.power != float(line.split()[1]):
                            msg = "Different power in "
                            msg += f"{self._file_label(fid)}."
                            msg += "\n"
                            msg += f" Saved value: {self.SOP.power}."
                            self.klog.warning(msg)
                            self._trigger_stop = True
                    tpl.append(line.split()[0] + " {SOP.power}\n")
                    continue
                elif line.lstrip().casefold().startswith('epsilons'):
                    self._read_collider_line('epsilons', line, fid, tpl)
                    continue
                elif line.lstrip().casefold().startswith('sigmas'):
                    self._read_collider_line('sigmas', line, fid, tpl)
                    continue
                elif line.lstrip().casefold().startswith('masses'):
                    self._read_masses_line(line, fid, tpl)
                    continue

                # Set the name of the current item

                # WELL
                elif (line.lstrip().casefold().startswith('well') and
                      line.lstrip().casefold().split()[0] == 'well'):
                    self._flush_rereads(fid)
                    last_item = 'well'
                    name: str = line.split()[1]
                    if self._reject_dbs_in_name(name, 'Well'):
                        continue
                    self._open_well(name, fid)
                    new_line: str = line.split()[0] \
                        + " {" \
                        + f"{name}.name" \
                        + "}\n"
                    tpl.append(new_line)
                    continue
                # BIMOLECULAR
                elif line.lstrip().casefold().startswith('bimolecular'):
                    self._flush_rereads(fid)
                    last_item = 'bimo'
                    name: str = line.split()[1]
                    if self._reject_dbs_in_name(name, 'Bimolecular'):
                        continue
                    self._open_bimolecular(name, fid)
                    new_line: str = line.split()[0] \
                        + " {" \
                        + f"{name}.name" \
                        + "}\n"
                    tpl.append(new_line)
                    continue
                # BARRIER
                elif line.lstrip().casefold().startswith('barrier'):
                    self._flush_rereads(fid)
                    last_item = 'barr'
                    tokens = line.split()[1:4]
                    if len(tokens) < 3:
                        err = (
                            f"Malformed BARRIER directive in "
                            f"{self._file_label(fid)} "
                            f"at line {lnum + 1}.\n"
                            f"Expected: Barrier <name> <left_side> <right_side>\n"
                            f"Got: {line.rstrip()}\n"
                            f"Only {len(tokens)} token(s) found: {tokens}"
                        )
                        self.klog.error(err)
                        self._trigger_stop = True
                        continue
                    name, lside, rside = tokens
                    if self._reject_dbs_in_name(name, 'Barrier'):
                        continue
                    self._open_barrier(name, lside, rside, fid)
                    new_line: str = line.split()[0]
                    new_line += " {" + f"{name}.name" + "}"
                    new_line += " {" + f"{lside}.name" + "}"
                    new_line += " {" + f"{rside}.name" + "}\n"
                    tpl.append(new_line)
                    continue
                # Different types of barrierless
                elif (line.lstrip().casefold().startswith('core')
                      and
                      line.lstrip().casefold().split()[1] == 'phasespacetheory'
                      and
                      isinstance(self._lookup(name), Barrier)):
                    bar = cast(Barrier, self._target_item(name))
                    bar.barrierless = True
                    tpl.append(line)
                    skip += self.save_phasespacetheory(name, lnum)
                    continue
                elif (line.lstrip().casefold().startswith('core')
                      and line.lstrip().casefold().split()[1] == 'rotd'
                      and isinstance(self._lookup(name), Barrier)):
                    bar = cast(Barrier, self._target_item(name))
                    bar.barrierless = True
                    tpl.append(line)
                    skip += self.save_rotd(name, lnum)
                    continue
                # FRAGMENT
                elif line.lstrip().casefold().startswith('fragment')\
                        and 'geom' not in line.casefold():
                    last_item = 'frag'
                    frag_tokens = line.split()
                    fname: str = frag_tokens[1]
                    if self._reject_dbs_in_name(fname, 'Fragment'):
                        continue
                    # MESS 'density' keyword of this fragment slot
                    density = (len(frag_tokens) > 2 and
                               frag_tokens[2].casefold() == 'density')
                    self._open_fragment(name, fname, density, fid)
                    new_line: str = line.split()[0] \
                        + " {" \
                        + f"{fname}.name" \
                        + "}" \
                        + (" density" if density else "") \
                        + "\n"
                    tpl.append(new_line)
                    continue

                # ATOM (fragment described by its mass and electronic
                # levels only)
                elif token == 'atom' and last_item == 'frag':
                    self._target_item(fname).is_atom = True
                    tpl.append(line)
                    continue
                elif (token == 'mass' and last_item == 'frag'
                      and self._target_item(fname).is_atom):
                    mass = float(line.split()[1])
                    element = _atom_element(fname, mass)
                    if element is None:
                        self._stop(
                            f"Atom {fname} in {self._file_label(fid)}: no "
                            f"chemical element matches its label or its "
                            f"mass {mass} amu.")
                    else:
                        self._target_item(fname).set_atom(element, mass)
                    tpl.append(line)
                    continue

                # Dummy
                elif line.lstrip().casefold().startswith('dummy'):
                    tpl.append(line)
                    self._target_item(name).dummy = True
                    continue

                # Add parameters to items

                # GEOMETRY
                elif line.lstrip().casefold().startswith('geometry')\
                        and 'rotor' not in file[lnum-1].casefold():
                    natom = int(line.split()[1])
                    tpl.append(line)
                    if last_item == 'frag':
                        self.save_geom(
                            fname,
                            lnum,
                            natom)
                    else:
                        self.save_geom(
                            name,
                            lnum,
                            natom)
                    continue
                elif line.lstrip().casefold().startswith('fragmentgeometry'):
                    natom = int(line.split()[1])
                    tpl.append(line)
                    self.save_geom(fname, lnum, natom)
                    continue

                # FREQUENCIES
                elif line.lstrip().casefold().startswith('frequencies'):
                    nfreq = int(line.split()[1])
                    tpl.append(line)
                    if last_item == 'frag':
                        nlines: int = self.save_freq(name=fname,
                                                     lnum=lnum,
                                                     nfreq=nfreq)
                    else:
                        nlines: int = self.save_freq(name=name,
                                                     lnum=lnum,
                                                     nfreq=nfreq)
                    skip += nlines
                    continue

                # HINDERED ROTOR
                elif line.lstrip().casefold().startswith('rotor') and\
                        line.split()[1].casefold() == 'hindered':
                    tpl.append(line)
                    if last_item == 'frag':
                        skip += self.save_rotor(name=fname,
                                                lnum=lnum)
                    else:
                        skip += self.save_rotor(name=name,
                                                lnum=lnum)
                    continue

                # MULTI ROTOR
                elif (line.lstrip().casefold().startswith('core') and
                      line.split()[1].casefold() == 'multirotor'):
                    tpl.append(line)
                    if last_item == 'frag':
                        skip += self.save_multirotor(name=fname,
                                                     lnum=lnum)
                    else:
                        skip += self.save_multirotor(name=name,
                                                     lnum=lnum)
                    continue

                # SYMMETRY FACTOR (rigid-rotor core of a well / saddle)
                elif line.lstrip().casefold().startswith('symmetryfactor'):
                    target = fname if last_item == 'frag' else name
                    item = self._lookup(target)
                    if isinstance(item, Barrier):
                        item._symFact = float(line.split()[1])
                    elif isinstance(item, Well):
                        item.sym_factor = float(line.split()[1])
                    tpl.append(line)
                    continue

                # ENERGY
                elif line.lstrip().casefold().startswith('zeroenergy'):
                    energy = float(line.split()[1])
                    if last_item == 'frag':
                        self.save_energy(name=fname,
                                         energy=energy,
                                         lnum=lnum,
                                         frag=True)
                    else:
                        self.save_energy(name=name,
                                         energy=energy,
                                         lnum=lnum)
                    continue
                elif line.lstrip().casefold().startswith('groundenergy'):
                    # for bimolec
                    energy = float(line.split()[1])
                    self.save_energy(name=name,
                                     energy=energy,
                                     lnum=lnum)
                    continue

                # TUNNELING
                elif line.lstrip().casefold().startswith('tunneling'):
                    tun_type = str(line.split()[1])
                    tpl.append(line)
                    skip += self.save_tunneling(name=name,
                                                tun_type=tun_type,
                                                lnum=lnum)
                    continue

                # ELECTRONIC LEVELS (additive: parse spin multiplicity /
                # electronic degeneracies for the automech serializer without
                # altering existing parsing/template behavior).
                elif line.lstrip().casefold().startswith('electroniclevels'):
                    tpl.append(line)
                    try:
                        nlevels = int(line.split()[1])
                    except (IndexError, ValueError):
                        nlevels = 0
                    target = fname if last_item == 'frag' else name
                    skip += self.save_elec_levels(name=target,
                                                  lnum=lnum,
                                                  nlevels=nlevels)
                    continue

                # All other lines
                else:
                    tpl.append(line)
            # Compare the items read again at the end of the file
            self._flush_rereads(fid)
            # HotEnergies species must be wells of this file (now all read)
            self._check_hot_species(fid)

        self._check_presence()
        self._add_missing_global_lines()
        self._assemble_lennard_jones()
        self._align_energies()
        for bar in self.SOP.barriers:
            for well_idx in range(len(bar.connected)):
                # Set the enegy of dummies from tunneling logic
                if bar.connected[well_idx].dummy:
                    bar.connected[well_idx]._energy = \
                        bar.energy - bar._well_depth[well_idx]
        self._default_elec_levels()
        self._check_atoms()
        self._check_file_items()
        if self.prompt_reactions:
            self._check_prompt_links()
        self.SOP.files2copy = self.files2copy
        return (self.SOP, self.tpls)

    def _check_atoms(self) -> None:
        """Stop when an ``Atom`` fragment has no ``Mass[amu]`` line."""
        for label, item in self.SOP.items.items():
            if (isinstance(item, Well) and item.is_atom
                    and item.atom_mass is None):
                self._stop(f"Atom {label} has no Mass[amu] line.")

    def _check_file_items(self) -> None:
        """Check the layout that maps template k to PES id k.

        Every input file must own at least one well or bimolecular (its PES
        id then exists in ``SOP.pes_ids``), and the Lennard-Jones lists
        hold the collider plus one value per file.
        """
        if self._trigger_stop:
            return
        n_files = len(self.pes_files)
        for fid in range(n_files):
            if not self.SOP.wells_in(fid) and not self.SOP.bimols_in(fid):
                self._stop(
                    f"{self._file_label(fid)} declares no Well and no "
                    "Bimolecular: every MESS input file must hold at least "
                    "one of them.")
        for kind in ('epsilons', 'sigmas'):
            values = getattr(self.SOP, kind)
            if len(values) not in (0, n_files + 1):
                raise ValueError(
                    f"SOP.{kind} holds {len(values)} values for {n_files} "
                    "MESS input files (expected the collider plus one value "
                    "per file).")

    def _ped_products(self) -> dict[int, set[str]]:
        """Product fragments of the ``PEDSpecies`` pairs of every file.

        A ``PEDSpecies`` entry is a pair ``<reactants>=<products>`` (e.g.
        ``A+B=C+D``): MESS writes the energy distribution of the products
        formed from the reactants (PED output). The products are the names
        on the right of ``=``, split on ``+``. A malformed entry (not
        exactly one ``=``, or an empty name) stops the run.

        Returns:
            dict[int, set[str]]: {file index: product fragment names}, for
            every file with a ``PEDSpecies`` line.
        """
        products: dict[int, set[str]] = {}
        for fid, data in sorted(self.SOP.pes_file_data.items()):
            if not data.ped_species:
                continue
            products[fid] = set()
            for pair in data.ped_species:
                sides = pair.split('=')
                names = [name for side in sides for name in side.split('+')]
                if len(sides) != 2 or not all(names):
                    self._stop(
                        f"PEDSpecies entry '{pair}' of "
                        f"{self._file_label(fid)} is not a pair "
                        "<reactants>=<products> (e.g. A+B=C+D).")
                    continue
                products[fid].update(sides[1].split('+'))
        return products

    def _check_prompt_links(self) -> None:
        """Check, in prompt mode, that the input files link a PED PES to a
        hot PES.

        A file is linked when one of its ``PEDSpecies`` products is a
        ``HotEnergies`` species of another file: the PED output of the
        first file then gives the initial energy of the hot well of the
        second one (prompt reaction). A product that is hot in its own file
        does not count. Stops when no file is linked (no ``PEDSpecies`` or
        no ``HotEnergies`` anywhere included). A file with ``PEDSpecies``
        but no link only gets a warning. A linked file must set
        ``MicroEnerMin``, ``MicroEnerMax`` and ``MicroEnerStep``, else
        MESS writes no microcanonical rate output (``_ke.out``) for it.
        """
        if self._trigger_stop:
            return
        ped_products = self._ped_products()
        if self._trigger_stop:
            return
        # {file index: names of its HotEnergies wells}
        hot_species: dict[int, set[str]] = {
            fid: set(data.hot_energies)
            for fid, data in self.SOP.pes_file_data.items()
            if data.hot_energies
        }
        # {file index with PEDSpecies: its products hot in another file}
        links: dict[int, set[str]] = {}
        for fid, products in ped_products.items():
            hot_elsewhere: set[str] = set().union(
                *(names for other, names in hot_species.items()
                  if other != fid))
            links[fid] = products & hot_elsewhere
        if not any(links.values()):
            self._stop(
                "'prompt_reactions' is true but no PEDSpecies product of a "
                "MESS input is a HotEnergies species of another input "
                f"(PEDSpecies in {len(ped_products)} input(s), HotEnergies "
                f"in {len(hot_species)} input(s)). Add the input of the hot "
                "PES (with its HotEnergies block) to 'mess_inputs', or set "
                "'prompt_reactions' to false.")
            return
        for fid, linked in links.items():
            file_label = self._file_label(fid)
            if not linked:
                self.klog.warning(
                    "Prompt reactions: no PEDSpecies product of "
                    f"{file_label} is a HotEnergies species of another MESS "
                    "input; its PED output gives no prompt reaction.")
                continue
            micro_ener = self.SOP.pes_file_data[fid].micro_ener
            if micro_ener is None or None in micro_ener:
                self._stop(
                    "Prompt reactions: the PEDSpecies products "
                    f"{', '.join(sorted(linked))} of {file_label} are "
                    "HotEnergies species of another MESS input, but the "
                    "file does not set all of MicroEnerMin, MicroEnerMax and "
                    "MicroEnerStep: MESS then writes no microcanonical rate "
                    "output (_ke.out), which the prompt calculation needs.")

    def _align_energies(self) -> None:
        """Align the energies of the input files sharing items.

        Sets every item's energy in the aligned frame and stores each
        file's offset in ``SOP.pes_file_data[fid].energy_offset``, so that
        the writers put each file back in its own energy zero.
        """
        anchors: set[str] = set()
        for label in self._file_energies:
            item = self.SOP.items.get(label)
            if isinstance(item, Barrier) and item.barrierless:
                continue
            anchors.add(label)
        alignment = PesEnergyAlignment(
            n_files=len(self.pes_files),
            energies=self._file_energies,
            anchors=anchors)
        offsets = alignment.solve()
        for label, first, other, diff in alignment.mismatches():
            self._stop(
                f"Energy of {label} is not consistent between "
                f"{self._file_label(first)} and {self._file_label(other)} "
                f"after aligning the files ({diff:+.4f} kcal/mol, tolerance "
                f"{PesEnergyAlignment.TOLERANCE} kcal/mol).")
        # Aligned energies and offsets are rounded to 1e-10 kcal/mol to drop
        # the float artefacts of the subtractions (inputs carry far fewer
        # decimals).
        for label in self._file_energies:
            item = self.SOP.items.get(label)
            if item is not None:
                item._energy = round(alignment.aligned_energy(label), 10)
        for fid, offset in offsets.items():
            offset = round(offset, 10)
            self.SOP.file_data(fid).energy_offset = offset
            if offset != 0.0:
                self.klog.info(
                    f"Energies of {self._file_label(fid)} are "
                    f"{offset:+.4f} kcal/mol above the reference file of "
                    f"its group (through {alignment.links.get(fid)}); they "
                    "are aligned in the SOP and written back in the file's "
                    "own energy zero.")

    def save_elec_levels(self,
                         name: str,
                         lnum: int,
                         nlevels: int) -> int:
        """Additively parse an ``ElectronicLevels`` block.

        Records the electronic states (energy in 1/cm, degeneracy) on the
        target Well/Barrier/fragment item as ``elec_levels`` so the automech
        serializer can build ``mess_io.writer.molecule``/``atom`` elec_levels.
        The corresponding lines are appended to the template verbatim, exactly
        as the fall-through path would, keeping template output unchanged.

        Args:
            name (str): Item name owning the electronic levels.
            lnum (int): Header line number of the ElectronicLevels block.
            nlevels (int): Number of electronic-level lines to consume.

        Returns:
            int: Number of consumed lines to skip in the main read loop.
        """
        fid: int = len(self.tpls) - 1
        file: list[str] = self.pes_files[fid]
        levels: list[list[float]] = []
        read: int = 0
        for line in file[lnum + 1:]:
            if read >= nlevels:
                break
            tokens = line.split()
            if len(tokens) >= 2:
                try:
                    energy = float(tokens[0])
                    degen = float(tokens[1])
                    deg_val: float = (
                        int(degen) if degen == int(degen) else degen
                    )
                    levels.append([energy, deg_val])
                except ValueError:
                    pass
            self.tpls[-1].append(line)
            read += 1
        if levels:
            item = self._lookup(name)
            if isinstance(item, Well):
                item.elec_levels = levels
        return read

    def _default_elec_levels(self) -> None:
        """Assign a singlet default to every Well/Barrier/fragment without a
        parsed ElectronicLevels block.
        """
        items: list[Well] = []
        seen: set[int] = set()
        for well in self.SOP.wells:
            items.append(well)
        for bar in self.SOP.barriers:
            items.append(bar)
        for bim in self.SOP.bimolecular:
            for frag in bim.fragments:
                items.append(frag)
        for item in items:
            if id(item) in seen:
                continue
            seen.add(id(item))
            if not hasattr(item, 'elec_levels'):
                item.elec_levels = [[0.0, 1]]
                self.klog.debug(
                    f"No ElectronicLevels parsed for {item.name}; "
                    "defaulting to singlet [[0.0, 1]]."
                )

    def save_phasespacetheory(self,
                              name: str,
                              lnum: int) -> int:
        """Save the barierless parameters in case of a phasespacetheory core

        Args:
            name (str): name of the barrier
            lnum (int): line number from wich to record this core

        Returns:
            int: number of line to skip to not double read this core
        """
        item = self._target_item(name)
        if not isinstance(item, Barrier):
            raise TypeError(f'Expected Barrier for {name}')
        bar: Barrier = item
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        tpl = self.tpls[-1]

        # Read the file
        for lnum2, line in enumerate(file[lnum+1:]):
            if line.lstrip().casefold().startswith('symmetryfactor'):
                bar._symFact = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                                + " {" + f"{name}" \
                                + ".symFact}\n"
                skip += 1
                tpl.append(new_line)
            elif line.lstrip().casefold().startswith('potentialprefactor'):
                bar.pp = float(line.split()[1])
                skip += 1
                tpl.append(line)
            elif line.lstrip().casefold().startswith('potentialpowerexponent'):
                bar.ppe = float(line.split()[1])
                skip += 1
                tpl.append(line)
            elif line.lstrip().casefold().startswith('tstlevel'):
                # Level of the PST rate (E, EJ or T), kept as written
                bar.tst_level = line.split()[1]
                skip += 1
                tpl.append(line)
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                skip += 1
                tpl.append(line)
        raise Error(
            f'Incorrect termination of phasespacetheory core for {name}'
            )

    def save_rotd(self,
                  name: str,
                  lnum: int) -> int:
        """Save the barierless parameters in case of a rotd core

        Args:
            name (str): name of the barrier
            lnum (int): line number from wich to record this core

        Returns:
            int: number of line to skip to not double read this core
        """
        item = self._target_item(name)
        if not isinstance(item, Barrier):
            raise TypeError(f'Expected Barrier for {name}')
        bar: Barrier = item
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        tpl: list[str] = self.tpls[-1]
        # Read the file
        for lnum2, line in enumerate(file[lnum+1:]):
            if line.lstrip().casefold().startswith('symmetryfactor'):
                bar._symFact = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                                + " {" + f"{name}" \
                                + ".symFact}\n"
                skip += 1
                tpl.append(new_line)
            elif line.lstrip().casefold().startswith('file'):
                bar.file = line.split()[1]
                if bar.file not in self.files2copy:
                    self.files2copy.append(bar.file)
                skip += 1
                tpl.append(line)
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                skip += 1
                tpl.append(line)
        raise Error(
            f'Incorrect termination of rotd core for {name}'
            )

    def save_temperatures(self, lnum: int) -> None:
        """Save temperatures to be used for RC calculation,
        if they are not provided by the user.

        Args:
            lnum (int): line number to read from in input file
        """

        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        if self.SOP.temp == []:
            args: list[str] = file[lnum].split()
            temp_list: list = []
            arg_n = 1
            while arg_n < len(args) and _is_number(args[arg_n]):
                temp_list.append(float(args[arg_n]))
                arg_n += 1
            self.SOP.temp = temp_list

    def save_pressures(self, lnum: int) -> None:
        """Save pressures to be used for RC calculation,
        if they are not provided by the user.

        Args:
            lnum (int): line number to read from in input file
        """
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        if self.SOP.pres == []:
            args: list[str] = file[lnum].split()
            pres_list: list = []
            arg_n = 1
            while arg_n < len(args) and _is_number(args[arg_n]):
                pres_list.append(float(args[arg_n]))
                arg_n += 1
            self.SOP.pres = pres_list

    def save_freq(self,
                  name: str,
                  lnum: int,
                  nfreq: int) -> int:
        """Save the next frequencies encountered in Mess in
        the item name.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file
            nfreq (int): Number of frequencies to record

        Raises:
            TypeError: inconsistent number of freq

        Returns:
            int: number of line to skip readinding in the read method.
        """
        freqs: list = []
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for lnum2, line in enumerate(file[lnum+1:]):
            args: list[str] = line.split()
            arg_n = 0
            while arg_n < len(args) and _is_number(args[arg_n]):
                freqs.append(float(args[arg_n]))
                arg_n += 1
            if len(freqs) == nfreq:
                self._target_sop(name).set_freqs(name, freqs)
                new_line: str = " {" + f"{name}" + ".r_freq}\n"
                self.tpls[-1].append(new_line)
                return lnum2+1
            if lnum2 > nfreq:
                msg: str = f"Error in {self.filenames[fid]}:"
                msg += "\n"
                msg += f"wrong number of frequencies for {name}."
                raise TypeError(msg)
        return 0

    @staticmethod
    def _scan_placeholder(name: str, rot_num: int) -> str:
        """Template line holding the energies of rotor ``rot_num`` of item
        ``name``."""
        return " {" + f"{name}" + ".r_scan" + f"({rot_num})" + "}\n"

    def save_rotor(self,
                   name: str,
                   lnum: int) -> int:
        """Save the next hindered rotor encountered in Mess in
        the last structure dictionary.

        Reads ``Potential[kcal/mol] N`` (N energies) and
        ``PotentialSpline[kcal/mol] N [M]`` (N angles, then N energies)
        rotors. The energies are replaced in the template by an
        ``{<name>.r_scan(<k>)}`` placeholder (k = index of the rotor in the
        item); the spline angles are kept verbatim.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file

        Raises:
            TypeError: error in input file
            TypeError: error in input file
            TypeError: error in input file
            Error: unknown error

        Returns:
            int: number of line to skip readinding in the read method.
        """

        # default
        thermalpowermax = 0.0
        scan: list[float] = []
        # Angles of a PotentialSpline rotor (degrees)
        angles: list[float] = []
        is_spline: bool = False
        fexp: list[int] = []
        fcoef: list[float] = []
        npot: int = 0
        skip: int = 0
        symmetry: int = 0
        local_skip: int = 0
        item = self._target_item(name)
        if isinstance(item, Bimolecular):
            rot_num = len(item.fragments[-1].h_rotors)
        else:
            rot_num = len(item.h_rotors)
        # Position of the r_scan placeholder in the template (its rotor
        # index is fixed once the rotor is stored)
        scan_line_idx: int | None = None
        saved_f: int = 0
        group: list[int] = []
        axis: list[int] = []
        geo: list[list[Any]] = []
        # Read the file
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for lnum2, line in enumerate(file[lnum+1:]):
            stripped = line.lstrip()
            # SCAN
            if local_skip:
                local_skip -= 1
                self.tpls[-1].append(line)
                continue

            if line.lstrip().casefold().startswith('potential'):
                is_spline = line.split()[0].casefold().startswith(
                    'potentialspline')
                npot = int(line.split()[1])
                self.tpls[-1].append(line)
                if not is_spline:
                    scan_line_idx = len(self.tpls[-1])
                    self.tpls[-1].append(
                        self._scan_placeholder(name, rot_num))
                skip += 1
                saved_f = 0
                continue
            elif npot != 0 and is_spline and len(angles) < npot:
                # PotentialSpline: the N angles come first, verbatim
                numbers = _leading_numbers(line.split())
                if len(angles) + len(numbers) > npot:
                    raise TypeError(
                        f"Error in Messfile: a PotentialSpline line of "
                        f"{name} mixes angles and energies.")
                angles.extend(numbers)
                self.tpls[-1].append(line)
                if len(angles) == npot:
                    scan_line_idx = len(self.tpls[-1])
                    self.tpls[-1].append(
                        self._scan_placeholder(name, rot_num))
                skip += 1
                continue
            elif npot != 0 and saved_f < npot:
                # Potential energies: numbers up to a comment ('!' or '#');
                # any other token (e.g. the 'End' of a rotor with too few
                # energies) is an error instead of being swallowed.
                for arg in line.split():
                    if arg.startswith(('!', '#')):
                        break
                    if not _is_number(arg):
                        raise TypeError(
                            f"Error in {self._file_label(fid)}: hindered "
                            f"rotor {rot_num + 1} of {name} expects {npot} "
                            f"potential energies ({saved_f} read) but found "
                            f"'{arg}' (line {lnum + 2 + lnum2}).")
                    scan.append(float(arg))
                    saved_f += 1
                if saved_f > npot:
                    raise TypeError("Error in Messfile: wrong number of pot\
                                     for hindered rotor")
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('fourierexpansion'):
                self.tpls[-1].append(line)
                nexp = int(line.split()[1])
                abs_idx = lnum + 1 + lnum2
                fexp = [
                    int(exp_line.split()[0])
                    for exp_line in file[abs_idx+1:abs_idx+1+nexp]]
                fcoef = [
                    float(exp_line.split()[1])
                    for exp_line in file[abs_idx+1:abs_idx+1+nexp]]
                for li in file[abs_idx+1:abs_idx+1+nexp]:
                    self.tpls[-1].append(li)
                skip += 1 + nexp
                continue

            # Other keys
            elif line.lstrip().casefold().startswith('thermalpowermax'):
                thermalpowermax = float(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('group'):
                group: list[int] = []
                for nmbr in line.split()[1:]:
                    if nmbr.lstrip('+-').isdigit():
                        group.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor group.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('axis'):
                axis: list[int] = []
                for nmbr in line.split()[1:]:
                    if nmbr.lstrip('+-').isdigit():
                        axis.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor axis.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('geometry'):
                natom = int(line.split()[1])
                local_skip += natom
                skip += natom + 1
                self.tpls[-1].append(line)
                abs_idx = lnum + 1 + lnum2
                geo = [
                    [row.split()[0],
                     float(row.split()[1]),
                     float(row.split()[2]),
                     float(row.split()[3])]
                    for row in file[abs_idx+1:abs_idx+1+natom]]
                continue
            elif line.lstrip().casefold().startswith('symmetry'):
                symmetry = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            # END
            elif line.lstrip().casefold().startswith('end'):
                if saved_f != npot or (is_spline and len(angles) != npot):
                    raise TypeError("Error in Messfile: wrong number of pot\
                                     for hindered rotor")
                rot_idx = self._target_sop(name).set_hrotor(
                    name=name,
                    thermalpowermax=thermalpowermax,
                    group=group,
                    axis=axis,
                    symmetry=symmetry,
                    scan=scan,
                    fexp=fexp,
                    fcoef=fcoef,
                    geo=geo if geo else None,
                    spline_angles=angles if is_spline else None)
                if scan_line_idx is not None:
                    self.tpls[-1][scan_line_idx] = \
                        self._scan_placeholder(name, rot_idx)
                self.tpls[-1].append(line)
                skip += 1
                return skip
            elif line.strip() == '' or stripped.startswith(('#', '!', '+++')):
                self.tpls[-1].append(line)
                skip += 1
                continue
            else:
                raise Error(f'Incorrect termination of rotor for {name}')
        return 0

    def save_multirotor(self,
                        name: str,
                        lnum: int) -> int:
        """Save the next hindered rotor encountered in Mess in
        the last structure dictionary.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file

        Raises:
            TypeError: error in input file
            TypeError: error in input file
            TypeError: error in input file
            Error: unknown error

        Returns:
            int: number of line to skip readinding in the read method.
        """

        skip = 0
        item = self._target_item(name)
        if isinstance(item, Bimolecular):
            rot_idx = len(item.fragments[-1].m_rotors)
        else:
            rot_idx = len(item.m_rotors)
        irs: list[InternalRotation] = []
        ir_skip: int = 0
        sf: float | None = None
        iem: float | None = None
        pes: str | None = None
        qlem: float | None = None
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]

        for lnum2, line in enumerate(file[lnum+1:]):
            lower_line = line.lstrip().casefold()
            is_blank = line.strip() == ''
            # Skip through the lines of internal rotation
            if ir_skip != 0:
                ir_skip -= 1
                continue
            # SymmetryFactor
            if lower_line.startswith('symmetryfactor'):
                sf = float(line.split()[1])
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".symFact}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # InterpolationEnergyMax
            elif lower_line.startswith('interpolationenergymax'):
                iem = float(line.split()[1])
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".iem}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # PotentialEnergySurface
            elif lower_line.startswith('potentialenergysurface'):
                pes = line.split()[1]
                if pes not in self.files2copy:
                    self.files2copy.append(pes)
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".file}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # QuantumLevelEnergyMax
            elif lower_line.startswith('quantumlevelenergymax'):
                qlem = float(line.split()[1])
                new_line: str = f"{file[lnum2+lnum+1].split()[0]}" \
                                + " {" + f"{name}.m_rotors[{rot_idx}]" \
                                + ".qlem}\n"
                self.tpls[-1].append(new_line)
                skip += 1
                continue

            # InternalRotation
            elif lower_line.startswith('internalrotation'):
                self.tpls[-1].append(line)
                skip += 1
                ir_skip, ir = self.create_internal_rotation(
                    name=name,
                    lnum=lnum2+lnum+1)
                irs.append(ir)
                skip += ir_skip
                continue
            # END
            elif lower_line.startswith('end'):
                missing: list[str] = []
                if sf is None:
                    missing.append('SymmetryFactor')
                if iem is None:
                    missing.append('InterpolationEnergyMax')
                if pes is None:
                    missing.append('PotentialEnergySurface')
                if qlem is None:
                    missing.append('QuantumLevelEnergyMax')
                if missing:
                    miss = ', '.join(missing)
                    raise TypeError(
                        f"Missing MultiRotor keyword(s) for {name}: {miss}"
                    )
                assert sf is not None
                assert iem is not None
                assert pes is not None
                assert qlem is not None
                self._target_sop(name).set_mrotor(
                    name=name,
                    sf=sf,
                    iem=iem,
                    pes=pes,
                    qlem=qlem,
                    irs=irs
                )
                self.tpls[-1].append(line)
                skip += 1
                return skip
            elif is_blank or lower_line.startswith(('#', '!', '+++')):
                self.tpls[-1].append(line)
                skip += 1
                continue  # ignore comments
            else:
                raise Error(f'Incorrect termination of rotor for {name}')
        return 0

    def create_internal_rotation(self,
                                 name: str,
                                 lnum: int):
        """Create an InternalRotation Object

        Args:
            name (str): name of the SOP item
            lnum (int): line number to start to read after

        Raises:
            TypeError: not int in group
            TypeError: not int in axis
            AttributeError: unknown attribute

        Returns:
            tuple(int, InternalRotation):
                int: lines to skip
                ir object to be added to MultiRotor
        """
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        group: list[int] | None = None
        axis: list[int] | None = None
        symmetry: int | None = None
        mes: int | None = None
        pes: int | None = None
        hamiltonsizemin: int | None = None
        hamiltonsizemax: int | None = None
        gridsize: int | None = None
        for lnum2, line in enumerate(file[lnum+1:]):
            if line.lstrip().casefold().startswith('group'):
                group = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        group.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor group.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('axis'):
                axis = []
                for nmbr in line.split()[1:]:
                    if isdigit(nmbr):
                        axis.append(int(nmbr))
                    else:
                        raise TypeError('Incorrect type for rotor axis.')
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('symmetry'):
                symmetry = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('massexpansionsize'):
                mes = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('potentialexpansionsize'):
                pes = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('hamiltonsizemin'):
                hamiltonsizemin = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('hamiltonsizemax'):
                hamiltonsizemax = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('gridsize'):
                gridsize = int(line.split()[1])
                self.tpls[-1].append(line)
                skip += 1
                continue
            elif line.lstrip().casefold().startswith('end'):
                missing: list[str] = []
                if group is None:
                    missing.append('Group')
                if axis is None:
                    missing.append('Axis')
                if symmetry is None:
                    missing.append('Symmetry')
                if mes is None:
                    missing.append('MassExpansionSize')
                if pes is None:
                    missing.append('PotentialExpansionSize')
                if hamiltonsizemin is None:
                    missing.append('HamiltonSizeMin')
                if hamiltonsizemax is None:
                    missing.append('HamiltonSizeMax')
                if gridsize is None:
                    missing.append('GridSize')
                if missing:
                    miss = ', '.join(missing)
                    msg = "Missing InternalRotation keyword(s) "
                    msg += f"for {name}: {miss}"
                    raise TypeError(
                        msg
                    )
                assert group is not None
                assert axis is not None
                assert symmetry is not None
                assert mes is not None
                assert pes is not None
                assert hamiltonsizemin is not None
                assert hamiltonsizemax is not None
                assert gridsize is not None
                ir = InternalRotation(
                    group=group,
                    axis=axis,
                    symmetry=symmetry,
                    massexpansionsize=mes,
                    potentialexpansionsize=pes,
                    hamiltonsizemax=hamiltonsizemax,
                    hamiltonsizemin=hamiltonsizemin,
                    gridsize=gridsize
                )
                self.tpls[-1].append(line)
                skip += 1
                return (skip, ir)
            elif (line.lstrip().startswith('#') or
                  line.lstrip().startswith('!') or
                  line.strip() == '' or
                  line.lstrip().startswith('+++')):
                self.tpls[-1].append(line)
                skip += 1
                continue
            else:
                raise AttributeError('Unknown keyword for InternalRotation')
        raise Error(f'Incorrect termination of internalrotation for {name}')

    def save_geom(self,
                  name: str,
                  lnum: int,
                  natom: int) -> None:
        """Save the geometry of the object 'name'
        in the SOP object.

        Args:
            name (str): Object's (well, bimol, barrier) name
            lnum (int): Line number in input file
            natom (int): Number of atoms in the geometry
            fid (int): File ID
        """
        symbols: list[str] = []
        geom: list = []
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for idx, line in enumerate(file[lnum+1:lnum+natom+1], start=lnum+1):
            tokens = line.split()
            if len(tokens) < 4:
                err = (
                    f"Malformed geometry line in {self.filenames[-1]} "
                    f"at line {idx + 1}.\n"
                    f"Expected at least: <symbol> <x> <y> <z>\n"
                    f"Got: {line.rstrip()}\n"
                    f"Only {len(tokens)} token(s) found: {tokens}"
                )
                self.klog.error(err)
                self._trigger_stop = True
                break
            symbols.append(tokens[0])
            try:
                x, y, z = tokens[1:4]
                geom.append([float(x), float(y), float(z)])
            except ValueError:
                err = (
                    f"Invalid coordinate values in {self.filenames[-1]} "
                    f"at line {idx + 1}.\n"
                    f"Expected numbers for x, y, z but got: {tokens[1:4]}\n"
                    f"Full line: {line.rstrip()}"
                )
                self.klog.error(err)
                self._trigger_stop = True
                break

        self._target_sop(name).set_structure(
            name,
            symbols,
            geom,
            self.klog)

    def save_energy(self,
                    name: str,
                    energy: float,
                    lnum: int,
                    frag=False) -> None:
        """Save the energy of the object 'name'
        in the SOP object.

        The raw value of each file is also recorded: the energies of files
        sharing items are aligned after all files are read.

        Args:
            name (str): Object's (well, bimol, barrier) name
            energy (float): Energy of the object in (kcal/mol)
            lnum (int): Line number in input file
        """
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        reread = self._rereads.get(name)
        if reread is not None and reread[0] is None:
            # Item read again after an error: the value stays on its
            # throwaway copy and takes no part in the alignment.
            item = reread[1]
            record = False
        else:
            item = self.SOP.items[name]
            record = True
        if isinstance(item, Barrier):
            item._energy = energy
        else:
            # Do not change the energy of a specie
            # if it is encountered as a frag
            if not frag:
                item._energy = energy
        if not frag:
            if record:
                self._file_energies.setdefault(name, {})[fid] = energy
            new_line: str = f"{file[lnum].split()[0]}" \
                            + " {" + f"{name}" \
                            + ".energy}\n"
            self.tpls[-1].append(new_line)
        else:
            self.tpls[-1].append(file[lnum])

    def save_tunneling(self,
                       name: str,
                       tun_type: str,
                       lnum: int) -> int:
        """Save the imaginary freq for tunneling and check left/right energies.

        Args:
            name (str): Object's (well, bimol, barrier) name
            tun_type (str): Type of tunneling - for future development
            lnum (int): Line number in input file

        Returns:
            int: number of line to skip readinding in the read method.
        """
        well_depth: list[float] = [-1.0, -1.0]
        item = self._target_item(name)
        if not isinstance(item, Barrier):
            raise TypeError(f'Expected Barrier for {name}')
        bar: Barrier = item
        well_idx = 0
        skip = 0
        fid: int = len(self.tpls)-1
        file: list[str] = self.pes_files[fid]
        for line in file[lnum+1:]:
            if line.lstrip().casefold().startswith('imaginaryfrequency'):
                ifreq = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                    + " {" \
                    + f"{name}" \
                    + ".ifreq}\n"
                bar.ifreq = ifreq
                self.tpls[-1].append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('cutoffenergy'):
                # coff = float(line.split()[1])
                new_line: str = f"{line.split()[0]}" \
                    + " {" \
                    + f"{name}" \
                    + ".r_coff}\n"
                self.tpls[-1].append(new_line)
                skip += 1
            elif line.lstrip().casefold().startswith('welldepth'):
                well_depth[well_idx] = float(line.split()[1])
                if well_idx == 0:
                    new_line: str = f"{line.split()[0]}" \
                        + " {" \
                        + f"{name}" \
                        + ".r_lenergy}\n"
                elif well_idx == 1:
                    new_line: str = f"{line.split()[0]}" \
                        + " {" \
                        + f"{name}" \
                        + ".r_renergy}\n"
                bar._well_depth = well_depth
                self.tpls[-1].append(new_line)
                well_idx += 1
                skip += 1
            elif line.lstrip().casefold().startswith('end'):
                return skip
            else:
                self.tpls[-1].append(line)
                skip += 1
        raise Error(f'Incorrect termination of tunneling for {name}')
