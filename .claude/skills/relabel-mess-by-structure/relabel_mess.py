#!/usr/bin/env python3
"""Give AutoMech MESS inputs structure-based labels (condensed formulas).

Two subcommands:

``formula XYZ [XYZ ...]``
    Read standard ``.xyz`` files (first line = atom count, second line =
    comment, then ``Element x y z`` in angstrom) and print one condensed
    formula per file, e.g. ``CH3CH2CH3`` for propane.

``relabel INPUT_DIR OUTPUT_DIR [--force]``
    Read every ``*.inp`` MESS input of INPUT_DIR (AutoMech prompt inputs made
    of fake wells, bimoleculars, phase-space-theory barriers and saddle
    points), rename every label from the structures it describes, check the
    result, then write into OUTPUT_DIR the renamed copies (same file names),
    one ``<stem>.map.json`` per file (``{old label: new label}``) and one
    ``rename_report.md``. Nothing is written when a blocking check fails.

Naming rule ("condensed formula", connectivity only):

* two atoms are bonded when their distance is at most
  ``BOND_SCALE * (r_cov,i + r_cov,j)``, radii from ``ase.data.covalent_radii``;
* every heavy (non-hydrogen) atom is written as its symbol followed by its
  hydrogen count (``C``, ``CH``, ``CH2``, ``CH3``); no bond orders, radical
  or cis/trans markers;
* the heavy-atom skeleton must be a tree (rings are unsupported); the main
  chain is a longest path, side branches are written in parentheses, and
  among all such writings the smallest string (Python ASCII order) wins;
* molecules with at most one heavy atom keep their usual formula
  (``H``, ``H2``, ``O``, ``OH``, ``H2O``, ``CH3``, ``CH4``).

Composite labels: bimolecular ``<A>+<B>`` (Fragment block order), fake well
``FakeW-<bimolecular label>``, barrier ``<lside>=<rside>`` (Barrier line order).

Exit codes: 0 success; 1 a blocking check failed (diagnostics on stderr,
nothing written); 2 usage or input-format error; 3 ``formula`` met a
structure it cannot name.

Runs in the ``kimeco`` conda environment (numpy, ase, rdkit).
"""

from __future__ import annotations

import argparse
import datetime
import itertools
import json
import platform
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ase
import numpy as np
import rdkit
from ase.data import atomic_masses, atomic_numbers, chemical_symbols, covalent_radii
from rdkit import Chem, RDLogger

# rdkit warns "not removing hydrogen atom without neighbors" for "[H]".
RDLogger.DisableLog('rdApp.warning')

# --------------------------------------------------------------------------
# Settings of the naming rule and of the checks
# --------------------------------------------------------------------------

#: Bond rule: atoms i and j are bonded when d_ij <= BOND_SCALE * (r_i + r_j).
BOND_SCALE = 1.2
#: Atom pairs whose distance is this close (angstrom) to the bond limit are
#: listed in the report, because a small geometry change would flip the bond.
BOND_MARGIN_WINDOW = 0.05
#: Heavy-atom RMSD (angstrom) above which two geometries sharing one name are
#: reported as a warning. Never blocking.
RMSD_WARNING_THRESHOLD = 0.05
#: Up to this many heavy atoms, the RMSD tries every same-element atom order.
MAX_PERMUTED_HEAVY_ATOMS = 8
#: Largest |Mass[amu] - tabulated mass| accepted to identify an Atom fragment.
ATOM_MASS_TOLERANCE = 0.1
#: KiMecO KIN_DB.batch_select truncates well/bimolecular names to this length.
KIN_DB_NAME_LIMIT = 30
#: Usual formulas that differ from "<element>H<n>" for a single heavy atom.
SINGLE_HEAVY_ATOM_NAMES = {('O', 2): 'H2O'}
#: Fake-well prefixes found in AutoMech inputs (old labels) and the one written.
OLD_FAKE_WELL_PREFIXES = ('FakeW-', 'FW-')
NEW_FAKE_WELL_PREFIX = 'FakeW-'
#: Text a new label may never contain, with the reason shown on a stop.
FORBIDDEN_LABEL_PARTS = {
    '.': 'KiMecO item names (SOP._check_item_name, MessWriter placeholders)',
    '{': 'KiMecO MessWriter placeholders',
    '}': 'KiMecO MessWriter placeholders',
    '__': 'KiMecO parameter names <label>__<type>',
    '!': 'MESS comment character',
    '#': 'MESS comment character',
    '/': 'MESS prints "name/energy" in its outputs',
}
#: First characters that would break the unquoted YAML scalar of a Cantera
#: equation (KiMecO ct_reaction_tpl.py).
YAML_INDICATORS = set('[]{}!&*#\'"%@`|>,?:-')

EXIT_OK = 0
EXIT_BLOCKING_CHECK = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3

# Label kinds used throughout the script.
FRAGMENT, BIMOLECULAR, WELL, BARRIER = 'fragment', 'bimolecular', 'well', 'barrier'


# --------------------------------------------------------------------------
# Errors and diagnostics
# --------------------------------------------------------------------------

class InputFormatError(Exception):
    """A file cannot be read as the expected format (exit code 2)."""


class UnsupportedStructure(Exception):
    """A molecule the condensed-formula writer cannot name (ring, bridging H)."""


class BlockingCheckFailed(Exception):
    """Raised once a relabel phase recorded at least one STOP diagnostic."""


@dataclass
class Diagnostic:
    """One message for stderr: a blocking STOP or a non-blocking WARNING.

    ``kind`` is a short category (``smiles``, ``collision``, ...) and
    ``location`` is ``<file>:<line>`` (or a file name for file-level issues).
    """

    kind: str
    location: str
    message: str


class Diagnostics:
    """Collect STOP and WARNING messages while the relabel phases run."""

    def __init__(self):
        """Start with no message."""
        self.stops: list[Diagnostic] = []
        self.warnings: list[Diagnostic] = []

    def stop(self, kind: str, location: str, message: str) -> None:
        """Record a blocking problem; the run ends after the current phase."""
        self.stops.append(Diagnostic(kind, location, message))

    def warn(self, kind: str, location: str, message: str) -> None:
        """Record a non-blocking remark, also listed in the report."""
        self.warnings.append(Diagnostic(kind, location, message))

    def raise_if_stopped(self) -> None:
        """End the run (BlockingCheckFailed) if any STOP was recorded."""
        if self.stops:
            raise BlockingCheckFailed()

    def print_all(self, stream=sys.stderr) -> None:
        """Print every STOP then every WARNING, one per line."""
        for diag in self.stops:
            print(f'STOP {diag.kind} {diag.location}: {diag.message}', file=stream)
        for diag in self.warnings:
            print(f'WARNING {diag.kind} {diag.location}: {diag.message}', file=stream)


# --------------------------------------------------------------------------
# Chemistry: formulas, graphs, geometries
# --------------------------------------------------------------------------

def hill_formula(counts: Counter) -> str:
    """Return the Hill formula (C, H, then alphabetical; no count of 1).

    Without carbon every element, hydrogen included, is alphabetical.
    """
    present = [element for element, number in counts.items() if number > 0]
    if 'C' in present:
        order = ['C'] + (['H'] if 'H' in present else [])
        order += sorted(e for e in present if e not in ('C', 'H'))
    else:
        order = sorted(present)
    return ''.join(e if counts[e] == 1 else f'{e}{counts[e]}' for e in order)


def canonical_smiles(smiles: str) -> str:
    """Return rdkit's canonical isomeric SMILES (keeps cis/trans markers)."""
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError(f'rdkit cannot parse SMILES {smiles!r}')
    return Chem.MolToSmiles(molecule)


class _SkeletonWriter:
    """Write a tree of heavy atoms as the smallest condensed-formula string.

    ``tokens`` maps each heavy atom to its text (``CH2``); ``adjacency`` maps
    it to its heavy neighbours. A "rooted writing" of atom ``a`` seen from its
    ``parent`` is: token(a), then every side branch in parentheses (sorted),
    then the writing of the "main child", which must start a longest path
    below ``a``; ties between main children keep the smallest string.
    """

    def __init__(self, tokens: dict[int, str], adjacency: dict[int, list[int]]):
        """Store the tree; results are cached per (atom, parent)."""
        self._tokens = tokens
        self._adjacency = adjacency
        self._heights: dict[tuple[int, int | None], int] = {}
        self._writings: dict[tuple[int, int | None], str] = {}

    def write(self) -> str:
        """Return the smallest writing started from an end of a longest path."""
        return min(self._rooted(end, None) for end in self._longest_path_ends())

    def _longest_path_ends(self) -> list[int]:
        """Return the atoms whose eccentricity equals the tree diameter."""
        eccentricity = {atom: self._eccentricity(atom) for atom in self._adjacency}
        diameter = max(eccentricity.values())
        return [atom for atom, value in eccentricity.items() if value == diameter]

    def _eccentricity(self, start: int) -> int:
        """Return the largest bond count from ``start`` to any atom (BFS)."""
        depth = {start: 0}
        queue = [start]
        for atom in queue:
            for neighbour in self._adjacency[atom]:
                if neighbour not in depth:
                    depth[neighbour] = depth[atom] + 1
                    queue.append(neighbour)
        return max(depth.values())

    def _children(self, atom: int, parent: int | None) -> list[int]:
        """Return the heavy neighbours of ``atom`` except ``parent``."""
        return [n for n in self._adjacency[atom] if n != parent]

    def _height(self, atom: int, parent: int | None) -> int:
        """Return the number of atoms on the longest downward path from atom."""
        key = (atom, parent)
        if key not in self._heights:
            children = self._children(atom, parent)
            self._heights[key] = 1 + max((self._height(c, atom) for c in children), default=0)
        return self._heights[key]

    def _rooted(self, atom: int, parent: int | None) -> str:
        """Return the smallest writing of the subtree of ``atom`` below parent."""
        key = (atom, parent)
        if key in self._writings:
            return self._writings[key]
        children = self._children(atom, parent)
        if not children:
            best = self._tokens[atom]
        else:
            tallest = max(self._height(c, atom) for c in children)
            best = None
            for main in (c for c in children if self._height(c, atom) == tallest):
                branches = sorted('(' + self._rooted(c, atom) + ')' for c in children if c != main)
                candidate = self._tokens[atom] + ''.join(branches) + self._rooted(main, atom)
                if best is None or candidate < best:
                    best = candidate
        self._writings[key] = best
        return best


class MolecularGraph:
    """Atoms (element symbols) and bonds, without coordinates or bond orders.

    Built from a geometry (distance rule) or from a SMILES string (rdkit), so
    both can be named by the same condensed-formula writer and compared.
    """

    def __init__(self, symbols: list[str], edges: list[tuple[int, int]]):
        """Store the symbols and the undirected bonds (pairs of atom indices)."""
        self.symbols = list(symbols)
        self.adjacency: dict[int, set[int]] = {i: set() for i in range(len(self.symbols))}
        for i, j in edges:
            self.adjacency[i].add(j)
            self.adjacency[j].add(i)

    @classmethod
    def from_smiles(cls, smiles: str) -> 'MolecularGraph':
        """Build the graph of a SMILES string with explicit hydrogens (rdkit)."""
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            raise ValueError(f'rdkit cannot parse SMILES {smiles!r}')
        molecule = Chem.AddHs(molecule)
        symbols = [atom.GetSymbol() for atom in molecule.GetAtoms()]
        edges = [(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) for b in molecule.GetBonds()]
        return cls(symbols, edges)

    def element_counts(self) -> Counter:
        """Return the number of atoms of each element."""
        return Counter(self.symbols)

    def hill_formula(self) -> str:
        """Return the Hill formula of all atoms."""
        return hill_formula(self.element_counts())

    def components(self) -> list[list[int]]:
        """Return the molecules (connected atom sets), ordered by first atom."""
        seen: set[int] = set()
        result = []
        for start in range(len(self.symbols)):
            if start in seen:
                continue
            group = [start]
            seen.add(start)
            for atom in group:
                for neighbour in sorted(self.adjacency[atom]):
                    if neighbour not in seen:
                        seen.add(neighbour)
                        group.append(neighbour)
            result.append(sorted(group))
        return result

    def subgraph(self, atoms: list[int]) -> 'MolecularGraph':
        """Return the graph restricted to ``atoms`` (renumbered from 0)."""
        position = {atom: k for k, atom in enumerate(atoms)}
        edges = [(position[i], position[j]) for i in atoms for j in self.adjacency[i]
                 if j in position and i < j]
        return MolecularGraph([self.symbols[a] for a in atoms], edges)

    def name(self) -> str:
        """Return the condensed formula of every molecule, joined by ``+``."""
        return '+'.join(self.subgraph(c).condensed_formula() for c in self.components())

    def condensed_formula(self) -> str:
        """Return the condensed formula of a single connected molecule.

        Raises UnsupportedStructure for a ring, a hydrogen that is not bonded
        to exactly one heavy atom, or more than one molecule.
        """
        if len(self.components()) != 1:
            raise UnsupportedStructure(f'{len(self.components())} molecules, expected 1')
        heavy = [i for i, s in enumerate(self.symbols) if s != 'H']
        hydrogens = [i for i, s in enumerate(self.symbols) if s == 'H']
        if not heavy:
            if len(hydrogens) <= 2:
                return 'H' if len(hydrogens) == 1 else 'H2'
            raise UnsupportedStructure(f'{len(hydrogens)} bonded hydrogen atoms')
        hydrogen_count = {atom: 0 for atom in heavy}
        for h in hydrogens:
            neighbours = self.adjacency[h]
            heavy_neighbours = [n for n in neighbours if self.symbols[n] != 'H']
            if len(neighbours) != 1 or len(heavy_neighbours) != 1:
                raise UnsupportedStructure(
                    f'hydrogen atom {h + 1} has {len(neighbours)} bonded neighbours '
                    f'({len(heavy_neighbours)} heavy), expected exactly one heavy atom')
            hydrogen_count[heavy_neighbours[0]] += 1
        tokens = {}
        for atom, count in hydrogen_count.items():
            suffix = '' if count == 0 else 'H' if count == 1 else f'H{count}'
            tokens[atom] = self.symbols[atom] + suffix
        if len(heavy) == 1:
            atom = heavy[0]
            return SINGLE_HEAVY_ATOM_NAMES.get((self.symbols[atom], hydrogen_count[atom]), tokens[atom])
        skeleton = {a: sorted(n for n in self.adjacency[a] if self.symbols[n] != 'H') for a in heavy}
        bond_count = sum(len(v) for v in skeleton.values()) // 2
        if bond_count != len(heavy) - 1:
            raise UnsupportedStructure(
                f'ring: {len(heavy)} heavy atoms joined by {bond_count} bonds (a tree has {len(heavy) - 1})')
        return _SkeletonWriter(tokens, skeleton).write()


@dataclass
class Geometry:
    """Cartesian coordinates in angstrom, with where they were read."""

    symbols: list[str]
    coords: np.ndarray
    location: str

    def element_counts(self) -> Counter:
        """Return the number of atoms of each element."""
        return Counter(self.symbols)

    def distance_matrix(self) -> np.ndarray:
        """Return all interatomic distances (angstrom)."""
        difference = self.coords[:, None, :] - self.coords[None, :, :]
        return np.linalg.norm(difference, axis=-1)

    def bond_limits(self) -> np.ndarray:
        """Return BOND_SCALE * (r_cov,i + r_cov,j) for every atom pair."""
        radii = np.array([covalent_radii[atomic_numbers[s]] for s in self.symbols])
        return BOND_SCALE * (radii[:, None] + radii[None, :])

    def graph(self) -> MolecularGraph:
        """Return the bond graph from the distance rule."""
        distances, limits = self.distance_matrix(), self.bond_limits()
        count = len(self.symbols)
        edges = [(i, j) for i in range(count) for j in range(i + 1, count)
                 if distances[i, j] <= limits[i, j]]
        return MolecularGraph(self.symbols, edges)

    def near_limit_pairs(self, window: float = BOND_MARGIN_WINDOW) -> list[tuple[int, int, float, float]]:
        """Return (i, j, distance, limit) for pairs within ``window`` of the limit."""
        distances, limits = self.distance_matrix(), self.bond_limits()
        count = len(self.symbols)
        return [(i, j, float(distances[i, j]), float(limits[i, j]))
                for i in range(count) for j in range(i + 1, count)
                if abs(distances[i, j] - limits[i, j]) <= window]

    def same_as(self, other: 'Geometry') -> bool:
        """Return True when symbols and coordinates are identical."""
        return self.symbols == other.symbols and np.array_equal(self.coords, other.coords)


class GeometryComparer:
    """Heavy-atom RMSD after the best rotation (Kabsch) and atom matching."""

    @staticmethod
    def kabsch_rmsd(first: np.ndarray, second: np.ndarray) -> float:
        """Return the RMSD of two matched point sets after centring and rotation."""
        p = first - first.mean(axis=0)
        q = second - second.mean(axis=0)
        u, _, vt = np.linalg.svd(p.T @ q)
        sign = np.sign(np.linalg.det(vt.T @ u.T)) or 1.0
        rotation = vt.T @ np.diag([1.0, 1.0, sign]) @ u.T
        return float(np.sqrt(np.mean(np.sum((p @ rotation.T - q) ** 2, axis=1))))

    @classmethod
    def heavy_atom_rmsd(cls, first: Geometry, second: Geometry) -> float | None:
        """Return the smallest heavy-atom RMSD, or None if the elements differ.

        Same-element heavy atoms are matched in every order when there are at
        most MAX_PERMUTED_HEAVY_ATOMS heavy atoms, else in file order.
        """
        heavy_first = [i for i, s in enumerate(first.symbols) if s != 'H']
        heavy_second = [i for i, s in enumerate(second.symbols) if s != 'H']
        symbols_first = [first.symbols[i] for i in heavy_first]
        if sorted(symbols_first) != sorted(second.symbols[i] for i in heavy_second):
            return None
        if len(heavy_first) < 2:
            return 0.0
        points_first = first.coords[heavy_first]
        # For each element: positions in the first list, candidate atoms in the second.
        positions = defaultdict(list)
        candidates = defaultdict(list)
        for k, symbol in enumerate(symbols_first):
            positions[symbol].append(k)
        for atom in heavy_second:
            candidates[second.symbols[atom]].append(atom)
        elements = sorted(positions)
        if len(heavy_first) <= MAX_PERMUTED_HEAVY_ATOMS:
            choices = [list(itertools.permutations(candidates[e])) for e in elements]
        else:
            choices = [[tuple(candidates[e])] for e in elements]
        best = None
        for combination in itertools.product(*choices):
            order = [0] * len(heavy_first)
            for element, atoms in zip(elements, combination):
                for position, atom in zip(positions[element], atoms):
                    order[position] = atom
            value = cls.kabsch_rmsd(points_first, second.coords[order])
            if best is None or value < best:
                best = value
        return best


def element_from_mass(mass: float) -> str | None:
    """Return the element whose tabulated mass is nearest (Z >= 1), or None.

    ``ase.data.atomic_masses[0]`` belongs to the dummy atom X and is skipped.
    """
    differences = np.abs(np.asarray(atomic_masses[1:]) - mass)
    best = int(np.argmin(differences))
    if differences[best] > ATOM_MASS_TOLERANCE:
        return None
    return chemical_symbols[best + 1]


def read_xyz(path: Path) -> Geometry:
    """Read a standard .xyz file (angstrom); raise InputFormatError if malformed."""
    lines = path.read_text(encoding='utf-8').splitlines()
    if not lines:
        raise InputFormatError('empty file')
    try:
        count = int(lines[0].split()[0])
    except (ValueError, IndexError):
        raise InputFormatError('first line must be the number of atoms') from None
    if count < 1 or len(lines) < count + 2:
        raise InputFormatError(f'expected {count} atom lines after the comment line')
    symbols, coords = [], []
    for number, line in enumerate(lines[2:count + 2], start=3):
        parts = line.split()
        symbol = parts[0].capitalize() if parts else ''
        if len(parts) < 4 or atomic_numbers.get(symbol, 0) == 0:
            raise InputFormatError(f'line {number}: expected "Element x y z"')
        try:
            coords.append([float(v) for v in parts[1:4]])
        except ValueError:
            raise InputFormatError(f'line {number}: coordinates must be numbers') from None
        symbols.append(symbol)
    return Geometry(symbols, np.array(coords, dtype=float), str(path))


# --------------------------------------------------------------------------
# MESS input files
# --------------------------------------------------------------------------

@dataclass
class LabelToken:
    """One label written in a MESS input line, located by character span.

    ``kind`` is what the token names (fragment, bimolecular, well, barrier,
    or ``endpoint`` for a Barrier lside/rside, a well or a bimolecular).
    ``role`` is ``declaration`` (the label line of the item), ``reference``
    (a Barrier endpoint or a PEDSpecies term) or ``comment`` (the label in
    ``! Fake Well for <bimolecular>``).
    """

    line_index: int
    start: int
    end: int
    text: str
    kind: str
    role: str


@dataclass
class FragmentRecord:
    """A ``Fragment`` block of a Bimolecular: geometry, or Atom with a mass."""

    label: str
    line_index: int
    bimolecular: str
    smiles: str | None
    geometry: Geometry | None = None
    is_atom: bool = False
    atom_mass: float | None = None
    new_label: str | None = None
    key: tuple | None = None
    element_counts: Counter | None = None


@dataclass
class BimolecularRecord:
    """A ``Bimolecular`` block: its two fragments and its SMILES comment."""

    label: str
    line_index: int
    comment_smiles: list[str] | None
    fragments: list[FragmentRecord] = field(default_factory=list)
    new_label: str | None = None
    key: tuple | None = None


@dataclass
class WellRecord:
    """A ``Well`` block (AutoMech fake well): geometry and comment label."""

    label: str
    line_index: int
    comment_bimolecular: str | None
    geometry: Geometry | None = None
    new_label: str | None = None
    key: tuple | None = None


@dataclass
class BarrierRecord:
    """A ``Barrier <name> <lside> <rside>`` block (PST or saddle point)."""

    label: str
    lside: str
    rside: str
    line_index: int
    is_pst: bool = False
    fragment_geometries: list[Geometry] = field(default_factory=list)
    geometry: Geometry | None = None
    new_label: str | None = None
    key: tuple | None = None
    check: str = ''


@dataclass
class PedSpeciesRecord:
    """A ``PEDSpecies`` line: each token ``A+B=C+D`` split into its two terms."""

    line_index: int
    pairs: list[tuple[str, str, str]]


def mess_ped_pair(token: str, bimolecular_names: list[str]) -> tuple[str, ...]:
    """Return the bimoleculars MESS reads in a PEDSpecies token.

    Mirrors ``MasterEquation::set_ped_pair`` (MESS ``mess.cc``): from the
    current position take the earliest bimolecular name found as a substring,
    the longest one when several start there, then continue after it. MESS
    accepts the token only when exactly two names are found.
    """
    found = []
    start = 0
    while start < len(token):
        best_position, best_name = len(token), None
        for name in bimolecular_names:
            position = token.find(name, start)
            if position == -1:
                continue
            if position < best_position or (position == best_position and best_name is not None
                                             and len(name) > len(best_name)):
                best_position, best_name = position, name
        if best_name is None:
            break
        found.append(best_name)
        start = best_position + len(best_name)
    return tuple(found)


class MessInputFile:
    """One MESS input: its exact text, its label tokens and its items.

    Only the lines that carry labels are interpreted: ``PEDSpecies``,
    ``Well`` (with its ``! Fake Well for`` comment), ``Bimolecular``,
    ``Fragment``, ``Barrier``; plus the geometry blocks, ``Atom``/``Mass``
    of Atom fragments, ``Core PhaseSpaceTheory`` and ``Rotor`` lines.
    The "main" geometry of an item is the first ``Geometry[angstrom] N``
    block right under ``RRHO`` and before any ``Rotor`` block (rotor blocks
    repeat a reoriented geometry that must be ignored).
    """

    _PED = re.compile(r'^(\s*PEDSpecies\s+)(.*)$')
    _WELL = re.compile(r'^(\s*Well\s+)(\S+)(.*)$')
    _FAKE_COMMENT = re.compile(r'!\s*Fake Well for\s+(\S+)')
    _BIMOLECULAR = re.compile(r'^(\s*Bimolecular\s+)(\S+)(.*)$')
    _BIMOLECULAR_COMMENT = re.compile(r'!\s*\[(.*)\]\s*$')
    _FRAGMENT = re.compile(r'^(\s*Fragment\s+)(\S+)(.*)$')
    _SMILES_COMMENT = re.compile(r'!\s*(\S+)')
    _BARRIER = re.compile(r'^(\s*Barrier\s+)(\S+)(\s+)(\S+)(\s+)(\S+)')
    _GEOMETRY = re.compile(r'^\s*(Fragment)?Geometry\[([^\]]*)\]\s+(\d+)')
    _MASS = re.compile(r'^\s*Mass\[([^\]]*)\]\s+(\S+)')

    def __init__(self, name: str, text: str, diagnostics: Diagnostics):
        """Parse ``text`` (the whole file); ``name`` is the file name."""
        self.name = name
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.tokens: list[LabelToken] = []
        self.ped_species: list[PedSpeciesRecord] = []
        self.wells: dict[str, WellRecord] = {}
        self.bimoleculars: dict[str, BimolecularRecord] = {}
        self.fragments: list[FragmentRecord] = []
        self.barriers: list[BarrierRecord] = []
        self._diagnostics = diagnostics
        self._parse()

    @classmethod
    def read(cls, path: Path, diagnostics: Diagnostics) -> 'MessInputFile':
        """Read and parse a file, keeping its line endings unchanged."""
        with open(path, encoding='utf-8', newline='') as handle:
            return cls(path.name, handle.read(), diagnostics)

    @property
    def stem(self) -> str:
        """Return the file name without its extension."""
        return Path(self.name).stem

    def location(self, line_index: int) -> str:
        """Return ``<file>:<line number>`` for a 0-based line index."""
        return f'{self.name}:{line_index + 1}'

    def _token(self, line_index: int, match: re.Match, group: int, kind: str, role: str) -> LabelToken:
        """Record the token of a regex group and return it."""
        token = LabelToken(line_index, match.start(group), match.end(group), match.group(group), kind, role)
        self.tokens.append(token)
        return token

    def _parse(self) -> None:
        """Walk the lines once, filling tokens, items and their geometries."""
        owner = None            # item whose block we are in (well, fragment, barrier, ...)
        rotor_seen = False      # a Rotor block started inside the current owner
        previous_word = ''      # first word of the previous significant line
        bimolecular = None      # current Bimolecular, parent of Fragment blocks
        index = 0
        while index < len(self.lines):
            body = self.lines[index].rstrip('\r\n')
            stripped = body.strip()
            words = stripped.split()
            if (match := self._PED.match(body)):
                self._parse_ped(index, match)
            elif (match := self._WELL.match(body)):
                owner, rotor_seen, bimolecular = self._parse_well(index, match), False, None
            elif (match := self._BIMOLECULAR.match(body)):
                owner, rotor_seen = self._parse_bimolecular(index, match), False
                bimolecular = owner
            elif (match := self._FRAGMENT.match(body)):
                if bimolecular is None:
                    raise InputFormatError(f'{self.location(index)}: Fragment outside a Bimolecular block')
                owner, rotor_seen = self._parse_fragment(index, match, bimolecular), False
            elif (match := self._BARRIER.match(body)):
                owner, rotor_seen, bimolecular = self._parse_barrier(index, match), False, None
            elif words[:1] == ['Rotor']:
                rotor_seen = True
            elif words[:2] == ['Core', 'PhaseSpaceTheory'] and isinstance(owner, BarrierRecord):
                owner.is_pst = True
            elif words == ['Atom'] and isinstance(owner, FragmentRecord):
                owner.is_atom = True
            elif (match := self._MASS.match(body)) and isinstance(owner, FragmentRecord) and owner.is_atom:
                if match.group(1) != 'amu':
                    self._diagnostics.stop('units', self.location(index), f'Mass[{match.group(1)}], expected amu')
                else:
                    owner.atom_mass = float(match.group(2))
            elif (match := self._GEOMETRY.match(body)):
                count = int(match.group(3))
                self._parse_geometry_block(index, match, count, owner, rotor_seen, previous_word)
                previous_word = words[0]
                index += count + 1
                continue
            if stripped and not stripped.startswith(('!', '#')):
                previous_word = words[0]
            index += 1

    def _parse_ped(self, index: int, match: re.Match) -> None:
        """Record a PEDSpecies line: each ``A+B=C+D`` token gives two terms."""
        rest_start = match.start(2)
        rest = match.group(2)
        cut = min([p for p in (rest.find('!'), rest.find('#')) if p >= 0], default=len(rest))
        pairs = []
        for word in re.finditer(r'\S+', rest[:cut]):
            text = word.group(0)
            if text.count('=') != 1:
                self._diagnostics.stop('format', self.location(index),
                                       f'PEDSpecies token {text!r} must contain exactly one "="')
                continue
            left, right = text.split('=')
            begin = rest_start + word.start()
            for term, offset in ((left, 0), (right, len(left) + 1)):
                self.tokens.append(LabelToken(index, begin + offset, begin + offset + len(term),
                                              term, BIMOLECULAR, 'reference'))
            pairs.append((text, left, right))
        self.ped_species.append(PedSpeciesRecord(index, pairs))

    def _parse_well(self, index: int, match: re.Match) -> WellRecord:
        """Record a Well line and the bimolecular named in its comment."""
        token = self._token(index, match, 2, WELL, 'declaration')
        comment = self._FAKE_COMMENT.search(match.string, token.end)
        comment_label = None
        if comment:
            comment_label = self._token(index, comment, 1, BIMOLECULAR, 'comment').text
        record = WellRecord(token.text, index, comment_label)
        if token.text in self.wells:
            self._diagnostics.stop('format', self.location(index), f'Well {token.text!r} declared twice')
        self.wells[token.text] = record
        return record

    def _parse_bimolecular(self, index: int, match: re.Match) -> BimolecularRecord:
        """Record a Bimolecular line and the two SMILES of its ``! [A + B]`` comment."""
        token = self._token(index, match, 2, BIMOLECULAR, 'declaration')
        comment = self._BIMOLECULAR_COMMENT.search(match.string, token.end)
        smiles = None
        if comment and len(comment.group(1).split(' + ')) == 2:
            smiles = [s.strip() for s in comment.group(1).split(' + ')]
        record = BimolecularRecord(token.text, index, smiles)
        if token.text in self.bimoleculars:
            self._diagnostics.stop('format', self.location(index), f'Bimolecular {token.text!r} declared twice')
        self.bimoleculars[token.text] = record
        return record

    def _parse_fragment(self, index: int, match: re.Match, bimolecular: BimolecularRecord) -> FragmentRecord:
        """Record a Fragment line and the SMILES of its comment."""
        token = self._token(index, match, 2, FRAGMENT, 'declaration')
        comment = self._SMILES_COMMENT.search(match.string, token.end)
        record = FragmentRecord(token.text, index, bimolecular.label, comment.group(1) if comment else None)
        bimolecular.fragments.append(record)
        self.fragments.append(record)
        return record

    def _parse_barrier(self, index: int, match: re.Match) -> BarrierRecord:
        """Record a Barrier line: name, lside and rside tokens."""
        name = self._token(index, match, 2, BARRIER, 'declaration')
        lside = self._token(index, match, 4, 'endpoint', 'reference')
        rside = self._token(index, match, 6, 'endpoint', 'reference')
        record = BarrierRecord(name.text, lside.text, rside.text, index)
        self.barriers.append(record)
        return record

    def _parse_geometry_block(self, index: int, match: re.Match, count: int, owner,
                              rotor_seen: bool, previous_word: str) -> None:
        """Keep a geometry block if it is a PST FragmentGeometry or a main geometry."""
        is_fragment_geometry = match.group(1) is not None
        unit = match.group(2)
        if is_fragment_geometry:
            if not isinstance(owner, BarrierRecord):
                raise InputFormatError(f'{self.location(index)}: FragmentGeometry outside a Barrier block')
            wanted = True
        else:
            wanted = (isinstance(owner, (WellRecord, FragmentRecord, BarrierRecord))
                      and owner.geometry is None and not rotor_seen and previous_word == 'RRHO')
        if not wanted:
            return
        if unit != 'angstrom':
            self._diagnostics.stop('units', self.location(index), f'Geometry[{unit}], expected angstrom')
            return
        geometry = self._read_geometry(index, count)
        if is_fragment_geometry:
            owner.fragment_geometries.append(geometry)
        else:
            owner.geometry = geometry

    def _read_geometry(self, header_index: int, count: int) -> Geometry:
        """Read the ``count`` lines ``Element x y z`` after a geometry header."""
        symbols, coords = [], []
        for line_index in range(header_index + 1, header_index + count + 1):
            parts = self.lines[line_index].split() if line_index < len(self.lines) else []
            if len(parts) < 4 or atomic_numbers.get(parts[0], 0) == 0:
                raise InputFormatError(f'{self.location(line_index)}: expected "Element x y z"')
            try:
                coords.append([float(v) for v in parts[1:4]])
            except ValueError:
                raise InputFormatError(f'{self.location(line_index)}: coordinates must be numbers') from None
            symbols.append(parts[0])
        return Geometry(symbols, np.array(coords, dtype=float), self.location(header_index))

    def rewrite(self, mapping: dict[str, str]) -> str:
        """Return the text with every label token replaced through ``mapping``.

        Tokens are replaced by character span, from the end of each line, so
        a label is never replaced inside a longer one (``H`` in ``H2``).
        """
        lines = list(self.lines)
        by_line = defaultdict(list)
        for token in self.tokens:
            by_line[token.line_index].append(token)
        for line_index, tokens in by_line.items():
            line = lines[line_index]
            for token in sorted(tokens, key=lambda t: t.start, reverse=True):
                line = line[:token.start] + mapping[token.text] + line[token.end:]
            lines[line_index] = line
        return ''.join(lines)

    def resolution_problems(self) -> list[tuple[int, str]]:
        """Return (line index, message) for every reference that does not resolve.

        Barrier endpoints must be declared wells or bimoleculars; PEDSpecies
        terms and fake-well comments must be declared bimoleculars, and MESS's
        substring matching must read each PEDSpecies token as its two terms.
        """
        problems = []
        endpoints = set(self.wells) | set(self.bimoleculars)
        for barrier in self.barriers:
            for side in (barrier.lside, barrier.rside):
                if side not in endpoints:
                    problems.append((barrier.line_index, f'Barrier {barrier.label}: endpoint {side!r} '
                                                         'is not a declared Well or Bimolecular'))
        for ped in self.ped_species:
            for token, left, right in ped.pairs:
                missing = [t for t in (left, right) if t not in self.bimoleculars]
                if missing:
                    problems.append((ped.line_index, f'PEDSpecies term(s) {missing} not declared Bimolecular'))
                    continue
                read = mess_ped_pair(token, list(self.bimoleculars))
                if read != (left, right):
                    problems.append((ped.line_index, f'MESS would read PEDSpecies {token!r} as {list(read)}'))
        for well in self.wells.values():
            if well.comment_bimolecular is not None and well.comment_bimolecular not in self.bimoleculars:
                problems.append((well.line_index, f'comment of Well {well.label}: '
                                                  f'{well.comment_bimolecular!r} is not a declared Bimolecular'))
        return problems


# --------------------------------------------------------------------------
# Relabelling of a folder of MESS inputs
# --------------------------------------------------------------------------

@dataclass
class Occurrence:
    """One declared item of one file with its old and new label.

    ``key`` is the structure key used to detect collisions: two occurrences
    with the same new label must have the same key.
    """

    file: str
    kind: str
    old: str
    new: str
    key: tuple
    location: str


def label_rule_problems(label: str, kind: str) -> list[str]:
    """Return why ``label`` is not usable as a new label of this kind ([] if fine)."""
    problems = []
    if not label or any(c.isspace() for c in label):
        problems.append('empty or contains whitespace')
    for part, reason in FORBIDDEN_LABEL_PARTS.items():
        if part in label:
            problems.append(f'contains {part!r} ({reason})')
    if label[:1] in YAML_INDICATORS:
        problems.append('starts with a YAML indicator (Cantera equations)')
    if kind in (FRAGMENT, BIMOLECULAR, WELL) and '=' in label:
        problems.append('contains "=" (mess_io splits PEDSpecies on "=")')
    if kind == FRAGMENT:
        if '+' in label:
            problems.append('contains "+" (bimolecular separator)')
        if 'geom' in label.lower():
            problems.append('contains "geom" (KiMecO MessInputReader reads it as a geometry)')
    if kind in (FRAGMENT, BIMOLECULAR) and 'Fake' in label:
        problems.append('contains "Fake" (mess_io would treat it as a fake well)')
    if kind == BIMOLECULAR and label.count('+') != 1:
        problems.append('must be <fragment>+<fragment>')
    if kind == WELL and not label.startswith(NEW_FAKE_WELL_PREFIX):
        problems.append(f'fake well must start with {NEW_FAKE_WELL_PREFIX}')
    if kind == BARRIER and label.count('=') != 1:
        problems.append('must be <lside>=<rside>')
    return problems


class Relabeler:
    """Rename every label of a folder of AutoMech MESS inputs from structures.

    Phases, each ending the run on a blocking problem: read files; name
    fragments (geometry or Atom mass, checked against the SMILES comment);
    name bimoleculars; name fake wells (checked against their two molecules);
    name barriers (PST fragments or saddle-point formula checked); build one
    map per file; check label rules, collisions and reversed barriers; rewrite
    each file and verify it (references resolve, every token covered, the
    inverse map gives back the original byte for byte).
    """

    def __init__(self, input_dir: Path, diagnostics: Diagnostics):
        """Prepare a run on the ``*.inp`` files of ``input_dir``."""
        self.input_dir = input_dir
        self.diag = diagnostics
        self.files: list[MessInputFile] = []
        self.occurrences: list[Occurrence] = []
        self.maps: dict[str, dict[str, str]] = {}
        self.renamed_text: dict[str, str] = {}
        self.counts: Counter = Counter()
        self.file_counts: dict[str, Counter] = {}
        self.fragment_rows: dict[tuple, dict] = {}
        self.rmsd_rows: list[tuple] = []
        self.margin_rows: list[tuple] = []
        self.kin_db_rows: list[tuple] = []

    # ---- driver -----------------------------------------------------------
    def run(self) -> None:
        """Run every phase; raise BlockingCheckFailed on the first failed phase."""
        self._read_files()
        for phase in (self._name_fragments, self._name_bimoleculars, self._name_fake_wells,
                      self._name_barriers, self._build_maps, self._check_labels_and_collisions,
                      self._check_input_resolution, self._rewrite_and_verify):
            phase()
            self.diag.raise_if_stopped()
        self._collect_warnings()

    def _read_files(self) -> None:
        """Parse every ``*.inp`` of the input folder (sorted by name)."""
        for path in sorted(self.input_dir.glob('*.inp')):
            self.files.append(MessInputFile.read(path, self.diag))
        self.diag.raise_if_stopped()

    def _add(self, mfile: MessInputFile, kind: str, record, location_index: int) -> None:
        """Register one named item for the collision and alias checks."""
        self.occurrences.append(Occurrence(mfile.name, kind, record.label, record.new_label,
                                           record.key, mfile.location(location_index)))

    # ---- fragments --------------------------------------------------------
    def _name_fragments(self) -> None:
        """Name every Fragment and check it against its SMILES comment."""
        for mfile in self.files:
            for fragment in mfile.fragments:
                self._name_fragment(mfile, fragment)

    def _name_fragment(self, mfile: MessInputFile, fragment: FragmentRecord) -> None:
        """Name one fragment from its geometry (or Atom mass) and check it with rdkit."""
        location = mfile.location(fragment.line_index)
        if fragment.smiles is None:
            self.diag.stop('missing-smiles', location, f'Fragment {fragment.label} has no "! <SMILES>" comment')
            return
        try:
            smiles_graph = MolecularGraph.from_smiles(fragment.smiles)
            smiles_name = smiles_graph.name()
            key = ('species', canonical_smiles(fragment.smiles))
        except (ValueError, UnsupportedStructure) as error:
            self.diag.stop('smiles', location, f'Fragment {fragment.label}: SMILES {fragment.smiles!r}: {error}')
            return
        if fragment.is_atom:
            if fragment.atom_mass is None:
                self.diag.stop('atom', location, f'Atom fragment {fragment.label} has no Mass[amu]')
                return
            element = element_from_mass(fragment.atom_mass)
            if element is None:
                self.diag.stop('atom', location, f'no element within {ATOM_MASS_TOLERANCE} amu '
                                                 f'of Mass {fragment.atom_mass}')
                return
            name, counts = element, Counter({element: 1})
            source = f'Atom, Mass {fragment.atom_mass} amu -> {element}'
        elif fragment.geometry is not None:
            graph = fragment.geometry.graph()
            try:
                name = graph.condensed_formula()
            except UnsupportedStructure as error:
                self.diag.stop('unsupported', location, f'Fragment {fragment.label}: {error}')
                return
            counts = graph.element_counts()
            source = f'Geometry, {len(graph.symbols)} atoms'
        else:
            self.diag.stop('format', location, f'Fragment {fragment.label}: no Geometry under RRHO and no Atom block')
            return
        if name != smiles_name or hill_formula(counts) != smiles_graph.hill_formula():
            self.diag.stop('smiles', location,
                           f'Fragment {fragment.label}: structure gives {name} ({hill_formula(counts)}) but SMILES '
                           f'{fragment.smiles!r} gives {smiles_name} ({smiles_graph.hill_formula()})')
            return
        fragment.new_label, fragment.key, fragment.element_counts = name, key, counts
        self._add(mfile, FRAGMENT, fragment, fragment.line_index)
        row = self.fragment_rows.setdefault((fragment.label, name, fragment.smiles), {
            'canonical': key[1], 'hill': hill_formula(counts), 'source': source, 'files': []})
        row['files'].append(mfile.stem)
        self.counts['smiles checks'] += 1

    # ---- bimoleculars -------------------------------------------------------
    def _name_bimoleculars(self) -> None:
        """Name every Bimolecular ``<A>+<B>`` in Fragment order."""
        for mfile in self.files:
            for bimolecular in mfile.bimoleculars.values():
                location = mfile.location(bimolecular.line_index)
                if len(bimolecular.fragments) != 2:
                    self.diag.stop('format', location, f'Bimolecular {bimolecular.label} has '
                                                       f'{len(bimolecular.fragments)} fragments, expected 2')
                    continue
                first, second = bimolecular.fragments
                if bimolecular.comment_smiles is not None:
                    if bimolecular.comment_smiles != [first.smiles, second.smiles]:
                        self.diag.stop('smiles', location, f'Bimolecular comment {bimolecular.comment_smiles} '
                                                           f'differs from Fragment SMILES {[first.smiles, second.smiles]}')
                        continue
                    self.counts['bimolecular comment checks'] += 1
                bimolecular.new_label = f'{first.new_label}+{second.new_label}'
                bimolecular.key = (BIMOLECULAR, first.key, second.key)
                self._add(mfile, BIMOLECULAR, bimolecular, bimolecular.line_index)

    # ---- fake wells ---------------------------------------------------------
    def _name_fake_wells(self) -> None:
        """Name every fake Well ``FakeW-<bimolecular>`` and check its two molecules."""
        for mfile in self.files:
            for well in mfile.wells.values():
                self._name_fake_well(mfile, well)

    def _name_fake_well(self, mfile: MessInputFile, well: WellRecord) -> None:
        """Check one fake well against the bimolecular its label names."""
        location = mfile.location(well.line_index)
        prefix = next((p for p in OLD_FAKE_WELL_PREFIXES if well.label.startswith(p)), None)
        if prefix is None:
            self.diag.stop('real-well', location, f'Well {well.label} is not a fake well '
                                                  f'(prefix {"/".join(OLD_FAKE_WELL_PREFIXES)}); unsupported')
            return
        suffix = well.label[len(prefix):]
        bimolecular = mfile.bimoleculars.get(suffix)
        if bimolecular is None:
            self.diag.stop('fake-well', location, f'Well {well.label}: {suffix!r} is not a Bimolecular of this file')
            return
        if well.comment_bimolecular is not None and well.comment_bimolecular != suffix:
            self.diag.stop('fake-well', location, f'Well {well.label}: comment names {well.comment_bimolecular!r}')
            return
        if well.geometry is None:
            self.diag.stop('format', location, f'Well {well.label}: no Geometry under RRHO')
            return
        try:
            molecules = well.geometry.graph().name().split('+')
        except UnsupportedStructure as error:
            self.diag.stop('unsupported', location, f'Well {well.label}: {error}')
            return
        expected = [f.new_label for f in bimolecular.fragments]
        if sorted(molecules) != sorted(expected):
            self.diag.stop('fake-well', location, f'Well {well.label}: geometry holds {molecules}, '
                                                  f'Bimolecular {suffix} holds {expected}')
            return
        well.new_label = NEW_FAKE_WELL_PREFIX + bimolecular.new_label
        well.key = (WELL, bimolecular.key)
        self._add(mfile, WELL, well, well.line_index)
        self.counts['fake well checks'] += 1

    # ---- barriers -----------------------------------------------------------
    def _endpoint(self, mfile: MessInputFile, label: str):
        """Return the well or bimolecular record named ``label`` in a file, or None."""
        return mfile.wells.get(label) or mfile.bimoleculars.get(label)

    @staticmethod
    def _endpoint_counts(record) -> Counter:
        """Return the element counts of a well (geometry) or a bimolecular (fragments)."""
        if isinstance(record, WellRecord):
            return record.geometry.element_counts()
        return sum((f.element_counts for f in record.fragments), Counter())

    def _name_barriers(self) -> None:
        """Name every Barrier ``<lside>=<rside>`` and check what it can."""
        for mfile in self.files:
            for barrier in mfile.barriers:
                self._name_barrier(mfile, barrier)

    def _name_barrier(self, mfile: MessInputFile, barrier: BarrierRecord) -> None:
        """Name one barrier from its endpoints; check PST fragments or TS formula."""
        location = mfile.location(barrier.line_index)
        left, right = self._endpoint(mfile, barrier.lside), self._endpoint(mfile, barrier.rside)
        if left is None or right is None:
            self.diag.stop('resolution', location, f'Barrier {barrier.label}: endpoint not declared before use')
            return
        barrier.new_label = f'{left.new_label}={right.new_label}'
        if barrier.is_pst:
            bimolecular = left if isinstance(left, BimolecularRecord) else right
            if not isinstance(bimolecular, BimolecularRecord):
                self.diag.stop('pst', location, f'PST Barrier {barrier.label} has no Bimolecular endpoint')
                return
            try:
                names = [g.graph().name() for g in barrier.fragment_geometries]
            except UnsupportedStructure as error:
                self.diag.stop('unsupported', location, f'Barrier {barrier.label}: {error}')
                return
            expected = [f.new_label for f in bimolecular.fragments]
            if names != expected:
                self.diag.stop('pst', location, f'PST Barrier {barrier.label}: FragmentGeometry blocks give '
                                                f'{names}, Bimolecular {bimolecular.label} gives {expected}')
                return
            self.counts['pst checks'] += 1
            self.counts['atom pst checks'] += sum(f.is_atom for f in bimolecular.fragments)
            barrier.key = ('pst', left.key, right.key)
            barrier.check = 'PST FragmentGeometry names'
        elif barrier.geometry is not None:
            formulas = {hill_formula(barrier.geometry.element_counts()),
                        hill_formula(self._endpoint_counts(left)), hill_formula(self._endpoint_counts(right))}
            if len(formulas) != 1:
                self.diag.stop('ts-formula', location, f'Barrier {barrier.label}: saddle point and endpoints '
                                                       f'have different formulas {sorted(formulas)}')
                return
            self.counts['ts checks'] += 1
            # Identity of a saddle point cannot be read from its endpoints:
            # one shared by two files is reported as a collision.
            barrier.key = ('saddle point', mfile.name, barrier.label)
            barrier.check = f'Hill formula {formulas.pop()}'
        else:
            barrier.key = ('barrier without geometry', mfile.name, barrier.label)
            barrier.check = 'no geometry'
            self.diag.warn('no-geometry', location, f'Barrier {barrier.label}: neither PST nor geometry; '
                                                    'named from its endpoints only')
        self._add(mfile, BARRIER, barrier, barrier.line_index)

    # ---- maps ---------------------------------------------------------------
    def _build_maps(self) -> None:
        """Build ``{old: new}`` per file (fragments, bimoleculars, wells, barriers)."""
        for mfile in self.files:
            mapping: dict[str, str] = {}
            records = (list(mfile.fragments) + list(mfile.bimoleculars.values())
                       + list(mfile.wells.values()) + list(mfile.barriers))
            for record in records:
                if mapping.get(record.label, record.new_label) != record.new_label:
                    self.diag.stop('flat-map', mfile.location(record.line_index),
                                   f'{record.label!r} would map to both {mapping[record.label]!r} '
                                   f'and {record.new_label!r}')
                mapping.setdefault(record.label, record.new_label)
            olds_of_new = defaultdict(list)
            for old, new in mapping.items():
                olds_of_new[new].append(old)
            for new, olds in olds_of_new.items():
                if len(olds) > 1:
                    self.diag.stop('collision', mfile.name, f'{olds} would all become {new!r} in this file')
            self.maps[mfile.name] = mapping

    # ---- set-wide checks ------------------------------------------------------
    def _check_labels_and_collisions(self) -> None:
        """Check label rules, structure collisions and reversed barriers set-wide."""
        by_new = defaultdict(list)
        for occurrence in self.occurrences:
            by_new[occurrence.new].append(occurrence)
        for new, occurrences in by_new.items():
            first = occurrences[0]
            for problem in label_rule_problems(new, first.kind):
                self.diag.stop('label-rule', first.location, f'{new!r} ({first.kind}): {problem}')
            kinds = sorted({o.kind for o in occurrences})
            if len(kinds) > 1:
                self.diag.stop('collision', first.location, f'{new!r} would name items of kinds {kinds}')
                continue
            keys = {o.key for o in occurrences}
            if len(keys) > 1:
                owners = sorted({f'{o.old} ({o.file})' for o in occurrences})
                self.diag.stop('collision', first.location,
                               f'{new!r} would name structurally different items: {"; ".join(owners)}')
        barriers = {o.new: o for o in self.occurrences if o.kind == BARRIER}
        for name, occurrence in barriers.items():
            left, _, right = name.partition('=')
            if f'{right}={left}' in barriers and name < f'{right}={left}':
                self.diag.stop('reversed-barrier', occurrence.location,
                               f'{name!r} and {right}={left!r} both exist (same pair, both directions)')
        bimoleculars = {o.new: o for o in self.occurrences if o.kind == BIMOLECULAR}
        for name, occurrence in bimoleculars.items():
            first, _, second = name.partition('+')
            if first != second and f'{second}+{first}' in bimoleculars and name < f'{second}+{first}':
                self.diag.stop('collision', occurrence.location, f'{name!r} and {second}+{first!r} both exist')

    def _check_input_resolution(self) -> None:
        """Check that every reference of the original files resolves."""
        for mfile in self.files:
            for line_index, message in mfile.resolution_problems():
                self.diag.stop('resolution', mfile.location(line_index), f'input: {message}')

    # ---- rewrite and verify -------------------------------------------------
    def _rewrite_and_verify(self) -> None:
        """Rewrite each file and prove the result is complete and reversible."""
        for mfile in self.files:
            mapping = self.maps[mfile.name]
            missing = sorted({t.text for t in mfile.tokens if t.text not in mapping})
            if missing:
                self.diag.stop('coverage', mfile.name, f'label tokens without a new label: {missing}')
                continue
            new_text = mfile.rewrite(mapping)
            check_diagnostics = Diagnostics()
            renamed = MessInputFile(mfile.name, new_text, check_diagnostics)
            if check_diagnostics.stops:
                self.diag.stop('round-trip', mfile.name, f'renamed file does not parse: '
                                                         f'{check_diagnostics.stops[0].message}')
                continue
            shape_before = [(t.line_index, t.kind, t.role) for t in mfile.tokens]
            shape_after = [(t.line_index, t.kind, t.role) for t in renamed.tokens]
            if shape_before != shape_after:
                self.diag.stop('round-trip', mfile.name, 'renamed file has a different set of label tokens')
                continue
            for line_index, message in renamed.resolution_problems():
                self.diag.stop('resolution', renamed.location(line_index), f'output: {message}')
            for well in renamed.wells.values():
                if well.label[len(NEW_FAKE_WELL_PREFIX):] not in renamed.bimoleculars:
                    self.diag.stop('resolution', renamed.location(well.line_index),
                                   f'output: {well.label} is not {NEW_FAKE_WELL_PREFIX}<declared Bimolecular>')
            self._check_stale_labels(mfile, renamed, mapping)
            inverse = {new: old for old, new in mapping.items()}
            restored = renamed.rewrite(inverse)
            if restored != mfile.text:
                restored_lines = restored.splitlines(keepends=True)
                first = next((i for i, (a, b) in enumerate(zip(restored_lines, mfile.lines)) if a != b),
                             min(len(restored_lines), len(mfile.lines)))
                self.diag.stop('round-trip', mfile.location(first), 'inverse map does not give back this line')
                continue
            self.renamed_text[mfile.name] = new_text
            counts = Counter(t.role for t in mfile.tokens)
            counts['changed lines'] = sum(a != b for a, b in zip(mfile.lines, renamed.lines))
            self.file_counts[mfile.name] = counts

    def _check_stale_labels(self, original: MessInputFile, renamed: MessInputFile,
                            mapping: dict[str, str]) -> None:
        """Stop if an old label that was renamed still appears outside comments.

        Catches labels in MESS keywords this script does not know. Element
        symbols are skipped because geometry lines are full of them.
        """
        stale = {old for old, new in mapping.items() if old != new} - set(mapping.values())
        stale -= {s for s in stale if atomic_numbers.get(s, 0) > 0}
        for line_index, line in enumerate(renamed.lines):
            code = re.split(r'[!#]', line, maxsplit=1)[0]
            words = {part for word in code.split() for part in word.split('=')}
            found = sorted(words & stale)
            if found:
                self.diag.stop('coverage', original.location(line_index),
                               f'old label(s) {found} still present after renaming')

    # ---- warnings -----------------------------------------------------------
    def _collect_warnings(self) -> None:
        """Collect the non-blocking findings: RMSD, bond margins, KIN_DB length."""
        geometries = defaultdict(list)   # new label -> main geometries carrying it
        margins = defaultdict(list)      # (label, atom pair, d, limit) -> file stems
        for mfile in self.files:
            # Geometries whose bonds decide or check a name.
            naming = [(f.new_label, f.geometry) for f in mfile.fragments if f.geometry is not None]
            naming += [(w.new_label, w.geometry) for w in mfile.wells.values()]
            pst = [(f'{b.new_label} FragmentGeometry {k + 1}', g) for b in mfile.barriers
                   for k, g in enumerate(b.fragment_geometries)]
            saddles = [(b.new_label, b.geometry) for b in mfile.barriers if b.geometry is not None]
            for label, geometry in naming + saddles:
                geometries[label].append(geometry)
            for label, geometry in naming + pst:
                for i, j, distance, limit in geometry.near_limit_pairs():
                    pair = f'{geometry.symbols[i]}{i + 1}-{geometry.symbols[j]}{j + 1}'
                    margins[(label, pair, round(distance, 5), round(limit, 5))].append(mfile.stem)
        for label, group in sorted(geometries.items()):
            reference = group[0]
            distinct = [g for k, g in enumerate(group) if not any(g.same_as(h) for h in group[:k])]
            values = [GeometryComparer.heavy_atom_rmsd(reference, g) for g in distinct[1:]]
            worst = max((v for v in values if v is not None), default=0.0)
            self.rmsd_rows.append((label, len(group), len(distinct), worst, None in values))
            if worst > RMSD_WARNING_THRESHOLD or None in values:
                self.diag.warn('rmsd', reference.location, f'{label}: geometries differ, max heavy-atom RMSD '
                                                           f'{worst:.3f} angstrom')
        for (label, pair, distance, limit), stems in sorted(margins.items()):
            self.margin_rows.append((label, pair, distance, limit, sorted(set(stems))))
            self.diag.warn('bond-margin', label, f'{pair} {distance:.5f} angstrom vs limit {limit:.5f} '
                                                 f'({"bonded" if distance <= limit else "not bonded"})')
        for occurrence in self.occurrences:
            if occurrence.kind in (WELL, BIMOLECULAR) and len(occurrence.new) > KIN_DB_NAME_LIMIT:
                row = (occurrence.new, len(occurrence.new))
                if row not in self.kin_db_rows:
                    self.kin_db_rows.append(row)
                    self.diag.warn('kin-db', occurrence.location, f'{occurrence.new} has {len(occurrence.new)} '
                                                                  f'characters > {KIN_DB_NAME_LIMIT} (KIN_DB read-back)')

    # ---- summaries used by the report and stdout ----------------------------
    def distinct_labels(self) -> dict[str, list[str]]:
        """Return the distinct new labels per kind, in first-seen order."""
        result = defaultdict(list)
        for occurrence in self.occurrences:
            if occurrence.new not in result[occurrence.kind]:
                result[occurrence.kind].append(occurrence.new)
        return result

    def alias_groups(self) -> dict[str, dict[str, list[str]]]:
        """Return {new label: {old label: [files]}} when several old labels merge."""
        groups = defaultdict(lambda: defaultdict(list))
        for occurrence in self.occurrences:
            groups[occurrence.new][occurrence.old].append(Path(occurrence.file).stem)
        return {new: dict(olds) for new, olds in groups.items() if len(olds) > 1}

    def reused_labels(self) -> dict[str, dict[str, list[str]]]:
        """Return {old label: {new label: [files]}} when one old label has several meanings."""
        groups = defaultdict(lambda: defaultdict(list))
        for occurrence in self.occurrences:
            groups[occurrence.old][occurrence.new].append(Path(occurrence.file).stem)
        return {old: dict(news) for old, news in groups.items() if len(news) > 1}


# --------------------------------------------------------------------------
# Outputs: renamed inputs, maps, report
# --------------------------------------------------------------------------

class RelabelOutputWriter:
    """Write the renamed inputs, their maps and ``rename_report.md``."""

    def __init__(self, relabeler: Relabeler, output_dir: Path, command: str):
        """Remember the finished relabeler, the output folder and the command line."""
        self.relabeler = relabeler
        self.output_dir = output_dir
        self.command = command

    def write(self) -> None:
        """Write every output file (only called after all blocking checks pass)."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for mfile in self.relabeler.files:
            (self.output_dir / mfile.name).write_text(self.relabeler.renamed_text[mfile.name],
                                                      encoding='utf-8', newline='')
            map_text = json.dumps(self.relabeler.maps[mfile.name], indent=2) + '\n'
            (self.output_dir / f'{mfile.stem}.map.json').write_text(map_text, encoding='utf-8')
        (self.output_dir / 'rename_report.md').write_text(self.report(), encoding='utf-8')

    def summary_lines(self) -> list[str]:
        """Return the short summary printed on stdout."""
        rel = self.relabeler
        distinct = rel.distinct_labels()
        total = sum(len(v) for v in distinct.values())
        tokens = sum(c['declaration'] + c['reference'] for c in rel.file_counts.values())
        comments = sum(c['comment'] for c in rel.file_counts.values())
        per_kind = ', '.join(f'{len(distinct[k])} {k}' for k in (FRAGMENT, BIMOLECULAR, WELL, BARRIER))
        return [
            f'relabel: {len(rel.files)} files, {tokens} label tokens + {comments} fake-well comment tokens rewritten',
            f'relabel: {total} distinct new labels ({per_kind})',
            f'relabel: {len(rel.alias_groups())} alias groups, {len(rel.reused_labels())} reused old labels, '
            f'0 collisions, {len(rel.diag.warnings)} warnings',
            f'relabel: wrote {len(rel.files)} .inp, {len(rel.files)} .map.json and rename_report.md to {self.output_dir}',
        ]

    def report(self) -> str:
        """Return the Markdown report."""
        rel = self.relabeler
        out: list[str] = ['# Structure-based relabelling of MESS inputs', '']
        self._run_section(out)
        out += ['## Summary', ''] + [f'- {line.removeprefix("relabel: ")}' for line in self.summary_lines()[:3]]
        out += ['', '| File | label tokens | comment tokens | changed lines | map entries |', '|---|---|---|---|---|']
        for mfile in rel.files:
            c = rel.file_counts[mfile.name]
            out.append(f'| {mfile.name} | {c["declaration"] + c["reference"]} | {c["comment"]} '
                       f'| {c["changed lines"]} | {len(rel.maps[mfile.name])} |')
        self._species_section(out)
        self._composite_section(out)
        self._alias_sections(out)
        self._warning_sections(out)
        self._checks_section(out)
        return '\n'.join(out) + '\n'

    def _run_section(self, out: list[str]) -> None:
        """Append how and with what the run was made."""
        elements = sorted({s for f in self.relabeler.files for frag in f.fragments
                           if frag.geometry for s in frag.geometry.symbols})
        radii = ', '.join(f'{e} {covalent_radii[atomic_numbers[e]]:.2f}' for e in elements)
        out += ['## Run', '',
                f'- Date: {datetime.datetime.now().isoformat(timespec="seconds")}',
                f'- Command: `{self.command}`',
                f'- Input: `{self.relabeler.input_dir}` (read only); output: `{self.output_dir}`',
                f'- Python {platform.python_version()}, numpy {np.__version__}, ase {ase.__version__}, '
                f'rdkit {rdkit.__version__}',
                f'- Bond rule: d <= {BOND_SCALE} x (r_cov,i + r_cov,j), `ase.data.covalent_radii` (angstrom): {radii}',
                '- Maps: `<stem>.map.json`, `{old: new}` for every label of the file (identity entries included), '
                'ordered fragments, bimoleculars, wells, barriers.', '']

    def _species_section(self, out: list[str]) -> None:
        """Append the fragment names with their SMILES cross-check."""
        out += ['', '## Species names (fragments)', '',
                'Every name is computed from the structure and equals the name rdkit gives the AutoMech SMILES '
                'comment (same condensed formula and Hill formula). The collision key of a species is the rdkit '
                'canonical isomeric SMILES, so stereoisomers sharing one name would stop the run.', '',
                '| Old label | New label | SMILES comment | canonical SMILES | Hill | Source | Files |',
                '|---|---|---|---|---|---|---|']
        for (old, new, smiles), row in sorted(self.relabeler.fragment_rows.items(), key=lambda kv: kv[0][1]):
            out.append(f'| `{old}` | `{new}` | `{smiles}` | `{row["canonical"]}` | {row["hill"]} | {row["source"]} '
                       f'| {len(row["files"])}: {", ".join(sorted(set(row["files"])))} |')

    def _composite_section(self, out: list[str]) -> None:
        """Append every bimolecular, fake-well and barrier label with its length."""
        rel = self.relabeler
        out += ['', '## Composite labels', '', '| New label | Kind | Length | Old labels (files) | Check |',
                '|---|---|---|---|---|']
        checks = {b.new_label: b.check for f in rel.files for b in f.barriers}
        for kind in (BIMOLECULAR, WELL, BARRIER):
            for new in rel.distinct_labels()[kind]:
                olds = defaultdict(list)
                for o in rel.occurrences:
                    if o.new == new:
                        olds[o.old].append(Path(o.file).stem)
                text = '; '.join(f'`{old}` ({", ".join(stems)})' for old, stems in olds.items())
                out.append(f'| `{new}` | {kind} | {len(new)} | {text} | {checks.get(new, "")} |')
        longest = [f'{kind} {max(map(len, rel.distinct_labels()[kind]))}'
                   for kind in (FRAGMENT, BIMOLECULAR, WELL, BARRIER) if rel.distinct_labels()[kind]]
        out += ['', 'Longest new label per kind (characters): ' + ', '.join(longest) + '.']

    def _alias_sections(self, out: list[str]) -> None:
        """Append aliases (merged old labels), reused old labels and collisions."""
        rel = self.relabeler
        out += ['', '## Aliases (several old labels, one structure, one new label)', '']
        aliases = rel.alias_groups()
        out += [f'- `{new}` <- ' + '; '.join(f'`{old}` ({", ".join(stems)})' for old, stems in olds.items())
                for new, olds in aliases.items()] or ['None.']
        out += ['', '## Reused old labels (one old label, different items in different files)', '']
        reused = rel.reused_labels()
        out += [f'- `{old}` -> ' + '; '.join(f'`{new}` ({", ".join(stems)})' for new, stems in news.items())
                for old, news in reused.items()] or ['None.']
        out += ['', '## Collisions', '', 'None (a collision stops the run before anything is written).']

    def _warning_sections(self, out: list[str]) -> None:
        """Append RMSD, bond-margin, KIN_DB and mess_io notes."""
        rel = self.relabeler
        out += ['', '## Geometry differences within one name (heavy-atom RMSD, not blocking)', '',
                f'Kabsch alignment, same-element heavy atoms permuted up to {MAX_PERMUTED_HEAVY_ATOMS} heavy atoms; '
                f'warning above {RMSD_WARNING_THRESHOLD} angstrom.', '',
                '| New label | geometries | distinct | max RMSD (angstrom) |', '|---|---|---|---|']
        for label, count, distinct, worst, mismatch in rel.rmsd_rows:
            note = ' (element mismatch)' if mismatch else ''
            out.append(f'| `{label}` | {count} | {distinct} | {worst:.4f}{note} |')
        out += ['', f'## Bond-threshold margins (pairs within {BOND_MARGIN_WINDOW} angstrom of the limit)', '']
        if rel.margin_rows:
            out += ['| Geometry of | Atoms | d (angstrom) | limit | d - limit | Files |', '|---|---|---|---|---|---|']
            for label, pair, distance, limit, stems in rel.margin_rows:
                out.append(f'| `{label}` | {pair} | {distance:.5f} | {limit:.5f} | {distance - limit:+.5f} '
                           f'| {", ".join(stems)} |')
        else:
            out.append('None.')
        out += ['', f'## KIN_DB name length (wells and bimoleculars > {KIN_DB_NAME_LIMIT} characters)', '']
        out += [f'- WARNING `{name}`: {length} characters' for name, length in rel.kin_db_rows] or [
            f'None (KiMecO `KIN_DB.batch_select` truncates names to {KIN_DB_NAME_LIMIT} characters on read).']
        saddle = [b.new_label for f in rel.files for b in f.barriers if not b.is_pst and 'F' in b.new_label]
        out += ['', '## mess_io note', '',
                'mess_io `reader/_pes.py` treats any Well/Barrier label containing an uppercase `F` as fake. '
                f'Every barrier name now contains `{NEW_FAKE_WELL_PREFIX}`, so the {len(saddle)} saddle points '
                '(formerly `ts_*`) are read as fake by `_pes.pes(read_fake=False)`; PST barriers were fake already. '
                'Accepted (spec round 2).']

    def _checks_section(self, out: list[str]) -> None:
        """Append the list of blocking checks that passed."""
        rel = self.relabeler
        c = rel.counts
        distinct = sum(len(v) for v in rel.distinct_labels().values())
        out += ['', '## Built-in checks (all passed)', '',
                f'- SMILES cross-check (rdkit): {c["smiles checks"]} fragment occurrences match their AutoMech comment.',
                f'- Atom fragments: element from Mass[amu] = SMILES element; PST 1-atom FragmentGeometry agrees '
                f'({c["atom pst checks"]} checks).',
                f'- Bimolecular `! [A + B]` comments equal the Fragment SMILES ({c["bimolecular comment checks"]}).',
                f'- Fake wells: old prefix FakeW-/FW-, suffix = Bimolecular of the file, comment = suffix, geometry '
                f'= the two fragments ({c["fake well checks"]}).',
                f'- PST barriers: FragmentGeometry names = Bimolecular fragments in order ({c["pst checks"]}).',
                f'- Saddle points: Hill formula = both endpoints ({c["ts checks"]}).',
                f'- Label rules on {distinct} distinct new labels; no collision (in-file, across kinds, '
                'structure keys across files); no reversed barrier or bimolecular.',
                '- Resolution, input and renamed files: every Barrier endpoint is a declared Well/Bimolecular; '
                'every PEDSpecies term is a declared Bimolecular and MESS substring matching reads it unchanged; '
                f'every renamed Well is {NEW_FAKE_WELL_PREFIX}<declared Bimolecular>.',
                '- Token coverage: every label token has a map entry; no renamed old label left outside comments.',
                f'- Inverse map: {len(rel.renamed_text)}/{len(rel.files)} renamed files give back the original '
                'byte for byte.']


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

class FormulaCommand:
    """``formula``: print the condensed formula of each .xyz file."""

    def __init__(self, paths: list[Path]):
        """Store the .xyz paths."""
        self.paths = paths

    def run(self) -> int:
        """Print ``<path>: <name>`` per file; return the exit code."""
        status = EXIT_OK
        for path in self.paths:
            try:
                geometry = read_xyz(path)
            except (OSError, InputFormatError) as error:
                print(f'{path}: error ({error})', file=sys.stderr)
                status = EXIT_USAGE
                continue
            try:
                print(f'{path}: {geometry.graph().name()}')
            except UnsupportedStructure as error:
                print(f'{path}: unsupported ({error})')
                if status == EXIT_OK:
                    status = EXIT_UNSUPPORTED
        return status


class RelabelCommand:
    """``relabel``: rename a folder of MESS inputs into another folder."""

    def __init__(self, input_dir: Path, output_dir: Path, force: bool, command: str):
        """Store the folders, the --force flag and the command line for the report."""
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.force = force
        self.command = command

    def _usage_problem(self) -> str | None:
        """Return why the folders cannot be used, or None."""
        if not self.input_dir.is_dir() or not any(self.input_dir.glob('*.inp')):
            return f'{self.input_dir} is not a folder with *.inp files'
        if self.output_dir.resolve() == self.input_dir.resolve():
            return 'OUTPUT_DIR must differ from INPUT_DIR (originals are never overwritten)'
        if self.output_dir.exists() and not self.output_dir.is_dir():
            return f'{self.output_dir} exists and is not a folder'
        if self.output_dir.is_dir() and any(self.output_dir.iterdir()) and not self.force:
            return f'{self.output_dir} is not empty (use --force to overwrite its files)'
        return None

    def run(self) -> int:
        """Run the relabelling; return the exit code."""
        problem = self._usage_problem()
        if problem:
            print(f'relabel: {problem}', file=sys.stderr)
            return EXIT_USAGE
        diagnostics = Diagnostics()
        relabeler = Relabeler(self.input_dir, diagnostics)
        try:
            relabeler.run()
        except InputFormatError as error:
            print(f'relabel: input format error: {error}', file=sys.stderr)
            return EXIT_USAGE
        except BlockingCheckFailed:
            diagnostics.print_all()
            print(f'relabel: {len(diagnostics.stops)} blocking problem(s); nothing written', file=sys.stderr)
            return EXIT_BLOCKING_CHECK
        writer = RelabelOutputWriter(relabeler, self.output_dir, self.command)
        writer.write()
        diagnostics.print_all()
        print('\n'.join(writer.summary_lines()))
        return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser (argparse exits with code 2 on misuse)."""
    parser = argparse.ArgumentParser(
        prog='relabel_mess.py',
        description='Structure-based (condensed-formula) names for xyz files and AutoMech MESS inputs.')
    commands = parser.add_subparsers(dest='command', required=True)
    formula = commands.add_parser('formula', help='print the condensed formula of .xyz files (angstrom)')
    formula.add_argument('xyz', nargs='+', type=Path, help='standard .xyz file(s)')
    relabel = commands.add_parser('relabel', help='rename every label of a folder of MESS inputs')
    relabel.add_argument('input_dir', type=Path, help='folder with the original *.inp files (read only)')
    relabel.add_argument('output_dir', type=Path, help='new or empty folder for the renamed copies')
    relabel.add_argument('--force', action='store_true', help='write into a non-empty OUTPUT_DIR')
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the chosen subcommand."""
    arguments = build_parser().parse_args(argv)
    if arguments.command == 'formula':
        return FormulaCommand(arguments.xyz).run()
    command = 'python ' + ' '.join([Path(sys.argv[0]).name] + (argv if argv is not None else sys.argv[1:]))
    return RelabelCommand(arguments.input_dir, arguments.output_dir, arguments.force, command).run()


if __name__ == '__main__':
    sys.exit(main())
