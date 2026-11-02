"""CI-safe tests of the prompt-rates collector (``kimeco.writers.prompt_collector``).

In prompt mode (``use_automech`` and ``prompt_reactions``) RateCo writes one
collector script per model; the collector reads the MESS outputs of the
model's PESs and writes the prompt-rates JSON (``k = BF * k1``). These tests
run the emitted script in-process (``runpy``) with mess_io and mechanalyzer
replaced in ``sys.modules`` by scripted stand-ins (same behaviour with or
without the ``automech`` extra). No MESS binary, no Slurm.

SOP: the real C4H8 fixtures ``tests/unit/data/c4h8_h_group/`` read in prompt
mode, hot PES first (``C4H7_hot``, ``H_C4H71-3``, ``H_C4H71-4``: hot pes 0,
PED pes 1 and 2, so slot != role), on the grid T = 298.5, 550 K and
P = 0.03, 1.01325 bar. Fixed channel set: 2 PED pairs x 4 C4H7 species = 8
channels (12 with ``2-H_C4H71-3`` added: 3 PED pairs).

Fixtures ``tests/unit/data/prompt_collector/`` (synthetic MESS rate outputs
on that bar grid, written once by a scratch script, no ``.py`` here):

* ``ped_h3_bar.out``: labels of ``H_C4H71-3`` (2 FakeW wells, 2
  bimoleculars); k1 ``CH2CHCH2CH3+H -> CH2CHCHCH3+H2`` = 1.11e-12,
  2.22e-12, ``***`` at (1.01325 bar, 298.5 K), 4.44e-12;
* ``ped_h4_bar.out``: labels of ``H_C4H71-4``; k1 ``CH2CHCH2CH3+H ->
  CH2CH2CHCH2+H2`` = 3.10e-12, -1.50e-20 (clamped to 0) at (0.03 bar, 550 K),
  3.30e-12, 3.40e-12;
* ``hot_bar.out``: labels of the C4H7 PES.

Every other cell holds a distinct positive value. ``_ped.out``, ``_ke.out``
and ``.log`` are one-line placeholders (the stand-ins parse nothing).
"""
from __future__ import annotations

import ast
import fnmatch
import json
import math
import os
import re
import runpy
import shutil
import sys
import types
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, cast

import numpy as np
import pandas as pd
import pytest

from kimeco.enums import FreqMode
from kimeco.logger_config import KMOLogger
from kimeco.q_sys import JobStatus
from kimeco.rate_coef import RateCo
from kimeco.readers.mess_input import MessInputReader
from kimeco.writers.prompt_collector import (
    PromptChannel, PromptCollector, PromptCollectorFiles,
    PromptCollectorWriter, PromptRatesError, PromptRatesFile,
    is_prompt_run, mess_written_temperature, ped_written_pressure)
from tests.unit.test_installation_extras_ci import import_or_skip
from tests.unit.test_mess_multi_pes_read_ci import SpyLog

UNIT = Path(__file__).resolve().parent
C4H8 = UNIT / 'data' / 'c4h8_h_group'
DATA = UNIT / 'data' / 'prompt_collector'
C4H7, H3, H4, H2B = ('C4H7_hot.inp', 'H_C4H71-3.inp', 'H_C4H71-4.inp',
                     '2-H_C4H71-3.inp')
SPECIES = ['CH2CHCH2CH3', 'CH3CHCHCH3', 'CH2CHCHCH3', 'CH2CH2CHCH2', 'H',
           'H2', 'CH2CHCHCH2', 'CH2CH2', 'CH2CH']
FILES3 = (C4H7, H3, H4)
OUTS = {C4H7: 'hot_bar.out', H3: 'ped_h3_bar.out', H4: 'ped_h4_bar.out'}
NAME, MODEL_ID = 'G0001E0007', 7
GRID_T = [298.5, 550.0]
GRID_P = [0.03, 1.01325]
H3_PAIR = ('CH2CHCH2CH3+H', 'CH2CHCHCH3+H2')
H4_PAIR = ('CH2CHCH2CH3+H', 'CH2CH2CHCH2+H2')
HOT_SPC = ['CH2CH2+CH2CH', 'CH2CH2CHCH2', 'CH2CHCHCH2+H', 'CH2CHCHCH3']
# k1 [p][t] of each PED pair as MessOutputReader gives it ('***' -> 0,
# negative -> 0 after the clamp)
K1 = {1: np.array([[1.11e-12, 2.22e-12], [0.0, 4.44e-12]]),
      2: np.array([[3.10e-12, 0.0], [3.30e-12, 3.40e-12]])}
HOT_OF = {1: 'CH2CHCHCH3', 2: 'CH2CH2CHCH2'}
# Scripted branching fractions {hot fragment: {(grid P, MESS-written T):
# [BF of HOT_SPC]}}. CH2CHCHCH3: CH2CH2+CH2CH below the 0.01 threshold
# everywhere (dropped), CH2CH2CHCH2 below it at one point only (kept) and
# 1e-31 (< 1e-30 cut) at another, thermalised BF exactly 1 at (0.03, 550).
BF = {
    'CH2CHCHCH3': {
        (0.03, 299.0): [0.005, 0.005, 0.1, 0.89],
        (0.03, 550.0): [0.0, 1e-31, 0.0, 1.0],
        (1.01325, 299.0): [0.005, 0.2, 0.1, 0.695],
        (1.01325, 550.0): [0.005, 0.2, 0.3, 0.495]},
    'CH2CH2CHCH2': {
        (0.03, 299.0): [0.3, 0.4, 0.2, 0.1],
        (0.03, 550.0): [0.25, 0.45, 0.2, 0.1],
        (1.01325, 299.0): [0.2, 0.5, 0.2, 0.1],
        (1.01325, 550.0): [0.1, 0.6, 0.2, 0.1]},
}
TOP_KEYS = {'format', 'version', 'kin_name', 'model_id', 'ped_model',
            'bf_threshold', 'pressure_unit', 'temperature_unit', 'k_unit',
            'pressures', 'temperatures', 'channels'}
RECORD_KEYS = {'ped_pes_id', 'hot_pes_id', 'ped_reactant', 'ped_product',
               'hot_fragment', 'hot_species', 'thermalised',
               'product_fragments', 'k'}


# ---------------------------------------------------------------------------
# Accessors of the prompt-rates JSON (one place to adapt if the schema moves)
# ---------------------------------------------------------------------------
def _grid(doc: dict) -> tuple[list[float], list[float]]:
    return doc['pressures'], doc['temperatures']


def _channels(doc: dict) -> list[dict]:
    return doc['channels']


def _k(record: dict, ip: int, it: int) -> float:
    return record['k'][ip][it]


def _record(doc: dict, ped_pes_id: int, hot_species: str) -> dict:
    hits = [r for r in _channels(doc) if r['ped_pes_id'] == ped_pes_id
            and r['hot_species'] == hot_species]
    assert len(hits) == 1, (ped_pes_id, hot_species, hits)
    return hits[0]


# ---------------------------------------------------------------------------
# SOP and collector set-up
# ---------------------------------------------------------------------------
def _read_sop(files: tuple[str, ...], root: Path = C4H8,
              prompt: bool = True) -> tuple[Any, list[Any], MessInputReader]:
    settings: dict[str, Any] = {
        'init_loc': str(root), 'mess_inputs': list(files), 'n_exp': 1,
        'score_sp': [], 'freq_mode': FreqMode.BATCH,
        'rc_temp': list(GRID_T), 'rc_pres': list(GRID_P),
        'pres_unit': 'bar', 'force_new_molecules': False,
        'prompt_reactions': prompt}
    reader = MessInputReader(settings=settings, mechanism_species=SPECIES,
                             klog=SpyLog(),  # type: ignore[arg-type]
                             postprocess=False)
    sop, tpls = reader.read()
    return sop, tpls, reader


@lru_cache(maxsize=None)
def _sop(files: tuple[str, ...] = FILES3) -> tuple[Any, tuple]:
    """Prompt-mode SOP of the fixture files (read once; tests only read
    it)."""
    sop, tpls, reader = _read_sop(files)
    assert reader._trigger_stop is False, reader.klog.errors  # type: ignore
    return sop, tuple(tuple(t) for t in tpls)


_DROP = object()  # BF override: mechanalyzer dropped this T row


class _Stubs:
    """Scripted mess_io / mechanalyzer stand-ins recording their calls.

    Tables use what MESS writes: PED tables indexed by floor(T + 0.5) with
    3-significant-digit pressure columns, hot tables by floor(T + 0.5) with
    the grid pressures. ``bf_tp_df_full`` returns the scripted ``BF`` on the
    index and columns of the PED table it gets, as mechanalyzer does.
    """

    def __init__(self, grid_p: list[float], grid_t: list[float]) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.grid_p: list[float] = list(grid_p)
        written_t = [float(math.floor(t + 0.5)) for t in grid_t]
        self.ped_temps: list[float] = written_t
        self.ped_pres: list[float] = [float(f'{p:.3g}') for p in grid_p]
        self.hot_temps: list[float] = list(written_t)
        self.hot_pres: list[float] = [float(f'{p:.6g}') for p in grid_p]
        self.energies: dict[str, float] = {}
        self.hot_species: dict[str, float] = {'CH2CHCHCH3': -45.63,
                                              'CH2CH2CHCH2': -28.82}
        self.raise_in: dict[str, BaseException] = {}
        self.bf_override: Callable[[str, float, float], Any] | None = None
        self.ped_cell_override: Callable[[float, float], Any] | None = None
        self.ped_missing = False
        self.dof_missing = False
        self.fne_tables: dict | None = None

    # -- helpers
    def _hit(self, name: str, detail: Any = None) -> None:
        self.calls.append((name, detail))
        if name in self.raise_in:
            raise self.raise_in[name]

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def bf(self, hot: str, temp: float, pres: float) -> Any:
        if self.bf_override is not None:
            value = self.bf_override(hot, temp, pres)
            if value is not None:
                return value
        return dict(zip(HOT_SPC, BF[hot][(pres, temp)]))

    @staticmethod
    def _pairs(inp: str) -> list[str]:
        pairs: list[str] = []
        for line in inp.splitlines():
            if line.split()[:1] == ['PEDSpecies']:
                pairs.extend(line.split()[1:])
        return pairs

    # -- mess_io.reader
    def ped_info(self, inp: str, ped_out: str, ke_out: str) -> tuple:
        pairs = self._pairs(inp)
        self._hit('ped_info', pairs)
        ped_dct: dict = {}
        energies: dict[str, float] = {}
        for pair in ([] if self.ped_missing else pairs):
            reac, prod = pair.split('=')
            table = pd.DataFrame(index=self.ped_temps,
                                 columns=self.ped_pres, dtype=object)
            for temp in self.ped_temps:
                for pres in self.ped_pres:
                    cell = (self.ped_cell_override(temp, pres)
                            if self.ped_cell_override else None)
                    table.at[temp, pres] = (
                        cell if cell is not None
                        else pd.Series([0.2, 0.5, 0.3],
                                       index=[1.0, 2.0, 3.0]))
            ped_dct[(tuple(reac.split('+')), tuple(prod.split('+')),
                     (None,))] = table
            energies[reac], energies[prod] = 0.0, -10.0
        energies.update(self.energies)
        return pairs, ped_dct, f'dos:{"|".join(pairs)}', energies

    def get_species(self, inp: str) -> dict:
        self._hit('get_species')
        return {name: '' for name in HOT_SPC}

    def get_hot_species(self, inp: str) -> dict:
        self._hit('get_hot_species')
        return dict(self.hot_species)

    def extract_hot_branching(self, log: str, hot_spc_en: dict,
                              species_lst: list, sp_labels: str = 'auto',
                              filter_out01: bool = False) -> dict:
        self._hit('extract_hot_branching', (sorted(hot_spc_en), sp_labels))
        tables = {}
        for hot in hot_spc_en:
            table = pd.DataFrame(index=self.hot_temps, columns=self.hot_pres,
                                 dtype=object)
            for temp in self.hot_temps:
                for pres in self.hot_pres:
                    table.at[temp, pres] = f'hot:{hot}'
            tables[hot] = table
        return tables

    def extract_fne(self, log: str, sp_labels: str = 'auto') -> dict:
        self._hit('extract_fne', sp_labels)
        if self.fne_tables is not None:
            return self.fne_tables
        tables = {}
        for hot in BF:
            table = pd.DataFrame(index=self.hot_temps, columns=self.hot_pres,
                                 dtype=object)
            for temp in self.hot_temps:
                for pres, grid_p in zip(self.hot_pres, self.grid_p):
                    table.at[temp, pres] = pd.Series(
                        self.bf(hot, temp, grid_p), dtype=float)
            tables[hot] = table
        return tables

    # -- mechanalyzer.calculator
    def calc_dof_dct(self, inp: str, ped_spc: list) -> dict:
        self._hit('calc_dof_dct', list(ped_spc))
        if self.dof_missing:
            return {}
        return {pair.split('=')[1]: f'dof:{pair.split("=")[1]}'
                for pair in ped_spc}

    def ped_frag1(self, ped_df, hotfrg, otherfrg, modeltype, dos_df=None,
                  dof_info=None):
        self._hit('ped_frag1', {
            'hot': hotfrg, 'other': otherfrg, 'model': modeltype,
            'dos': dos_df, 'dof': dof_info,
            'columns': list(ped_df.columns),
            'index': sorted(float(t) for t in ped_df.index)})
        out = ped_df.copy()
        out.attrs['hot'] = hotfrg
        return out

    def bf_tp_df_full(self, ped_df, hotbf_df):
        self._hit('bf_tp_df_full', {'hot_columns': list(hotbf_df.columns)})
        hot = ped_df.attrs['hot']
        table = pd.DataFrame(index=ped_df.index, columns=ped_df.columns,
                             dtype=object)
        dropped = []
        for temp in ped_df.index:
            for pres in ped_df.columns:
                value = self.bf(hot, float(temp), float(pres))
                if value is _DROP:
                    dropped.append(temp)
                elif isinstance(value, dict):
                    table.at[temp, pres] = pd.Series(value, dtype=float)
                else:
                    table.at[temp, pres] = value
        return table.drop(index=sorted(set(dropped)))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        hoten = types.ModuleType('mess_io.reader.hoten')
        hoten.get_hot_species = self.get_hot_species  # type: ignore
        hoten.extract_hot_branching = self.extract_hot_branching  # type: ignore
        hoten.extract_fne = self.extract_fne  # type: ignore
        reader = types.ModuleType('mess_io.reader')
        reader.ped_info = self.ped_info  # type: ignore[attr-defined]
        reader.get_species = self.get_species  # type: ignore[attr-defined]
        reader.hoten = hoten  # type: ignore[attr-defined]
        # hot_info / dct_species_fragments deliberately absent
        mess_io = types.ModuleType('mess_io')
        mess_io.reader = reader  # type: ignore[attr-defined]
        calc = types.ModuleType('mechanalyzer.calculator')
        modules = {'mess_io': mess_io, 'mess_io.reader': reader,
                   'mess_io.reader.hoten': hoten}
        for sub, funcs in (('bf', ('bf_tp_df_full',)),
                           ('ene_partition', ('ped_frag1',)),
                           ('nonboltz', ('calc_dof_dct',))):
            mod = types.ModuleType(f'mechanalyzer.calculator.{sub}')
            for func in funcs:
                setattr(mod, func, getattr(self, func))
            setattr(calc, sub, mod)
            modules[f'mechanalyzer.calculator.{sub}'] = mod
        mechanalyzer = types.ModuleType('mechanalyzer')
        mechanalyzer.calculator = calc  # type: ignore[attr-defined]
        modules['mechanalyzer'] = mechanalyzer
        modules['mechanalyzer.calculator'] = calc
        for name, module in modules.items():
            monkeypatch.setitem(sys.modules, name, module)


def _settings(**extra: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {
        'rc_software': 'mess', 'postprocess': False,
        'rc_temp': list(GRID_T), 'rc_pres': list(GRID_P),
        'use_automech': True, 'prompt_reactions': True,
        'prompt_ped_model': 'rovib_dos', 'prompt_bf_threshold': 0.01,
        'cpu_kin': 1, 'mem_kin': 500}
    settings.update(extra)
    return settings


def _populate(loc: Path, files: tuple[str, ...] = FILES3) -> None:
    """MESS inputs and outputs of every slot, as the drivers leave them."""
    loc.mkdir(parents=True, exist_ok=True)
    sop, _ = _sop(files)
    for slot, name in enumerate(files):
        stem = loc / f'{NAME}P{slot:02d}'
        shutil.copy(C4H8 / name, f'{stem}.inp')
        shutil.copy(DATA / OUTS[name], f'{stem}.out')
        data = sop.pes_file_data[slot]
        if data.ped_species:
            Path(f'{stem}_ped.out').write_text('ped placeholder\n')
            Path(f'{stem}_ke.out').write_text('ke placeholder\n')
        if data.hot_energies:
            Path(f'{stem}.log').write_text('log placeholder\n')


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
         sub_p: list[float] | None = None, sub_t: list[float] | None = None,
         **settings: Any) -> SimpleNamespace:
    """Collector written by the real writer from the 3-file SOP, its inputs
    in ``loc``, the stand-ins installed and an empty cwd."""
    sop, _ = _sop()
    loc = tmp_path / 'loc'
    _populate(loc)
    files = PromptCollectorFiles(loc=str(loc), kin_name=NAME)
    writer = PromptCollectorWriter(
        sop=sop, settings=_settings(**settings), kin_name=NAME,
        model_id=MODEL_ID, output_pes_ids=list(sop.pes_ids),
        reader_pres=list(GRID_P), reader_temp=list(GRID_T),
        sub_p=sub_p, sub_t=sub_t)
    writer.write(files)
    grid_p = sub_p if sub_p is not None else GRID_P
    grid_t = sub_t if sub_t is not None else GRID_T
    stubs = _Stubs(grid_p, grid_t)
    stubs.install(monkeypatch)
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.delenv('MPLBACKEND', raising=False)
    return SimpleNamespace(sop=sop, loc=loc, files=files, writer=writer,
                           stubs=stubs, cwd=cwd)


def _run(env: SimpleNamespace, capsys) -> tuple[Any, str, str]:
    """Run the emitted script as ``__main__``; (exit code, stdout, stderr)."""
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(env.files.script, run_name='__main__')
    out, err = capsys.readouterr()
    return exc.value.code, out, err


def _doc(env: SimpleNamespace) -> dict:
    return json.loads(Path(env.files.rates).read_text())


def _assert_failed(env: SimpleNamespace, code: Any, err: str,
                   *needles: str) -> None:
    assert code == 1, err
    assert not Path(env.files.rates).exists()
    assert not Path(env.files.rates_tmp).exists()
    assert f'PROMPT COLLECTOR FAILED (model {MODEL_ID}, {NAME}): ' in err
    for needle in needles:
        assert needle in err, (needle, err)


def _expected_k(ped_pes_id: int, species: str, threshold: float = 0.01
                ) -> np.ndarray:
    """k = BF * k1 under the documented rules, computed independently."""
    hot = HOT_OF[ped_pes_id]
    idx = HOT_SPC.index(species)
    bf = np.array([[BF[hot][(p, float(math.floor(t + 0.5)))][idx]
                    for t in GRID_T] for p in GRID_P])
    if not np.any(bf >= threshold):
        return np.zeros_like(bf)
    return np.where(bf >= 1e-30, bf * K1[ped_pes_id], 0.0)


# ===========================================================================
# Small helpers: MESS rounding rules, prompt mode, file names
# ===========================================================================
@pytest.mark.parametrize('temp, written', [
    (298.5, 299.0), (298.4, 298.0), (297.5, 298.0), (298.15, 298.0),
    (550.0, 550.0), (999.5, 1000.0)])
def test_mess_written_temperature_is_floor_t_plus_half(temp, written) -> None:
    """MESS writes (int)floor(T + 0.5): 298.5 -> 299 where Python's round()
    gives 298 (half to even)."""
    assert mess_written_temperature(temp) == written
    assert isinstance(mess_written_temperature(temp), float)


@pytest.mark.parametrize('pres, written', [
    (1.01325, 1.01), (1234.0, 1230.0), (0.00101, 0.00101), (0.1004, 0.1),
    (100.4, 100.0), (0.03, 0.03)])
def test_ped_written_pressure_keeps_three_significant_digits(pres,
                                                             written) -> None:
    assert ped_written_pressure(pres) == written


def test_is_prompt_run_needs_both_flags() -> None:
    assert is_prompt_run({'use_automech': True, 'prompt_reactions': True})
    for settings in ({}, {'use_automech': True},
                     {'prompt_reactions': True},
                     {'use_automech': False, 'prompt_reactions': True},
                     {'use_automech': True, 'prompt_reactions': False}):
        assert is_prompt_run(settings) is False, settings


def test_collector_file_names_match_no_kimeco_glob(tmp_path) -> None:
    """Every collector file starts with prompt_<kin name>: no kin glob
    ({name}P*, logs/{name}_*), SIM glob ({name}S*) or model-reset glob
    matches it; remove_rates deletes the JSON and its tmp, absent or not."""
    files = PromptCollectorFiles(loc=str(tmp_path), kin_name=NAME)
    assert files.stem == f'prompt_{NAME}'
    assert files.script == f'{tmp_path}/prompt_{NAME}.py'
    assert files.slurm == f'{tmp_path}/prompt_{NAME}.slurm'
    assert files.rates == f'{tmp_path}/prompt_{NAME}.json'
    assert files.rates_tmp == f'{tmp_path}/prompt_{NAME}.json.tmp'
    assert files.stdout == f'{tmp_path}/logs/prompt_{NAME}.stdout'
    assert files.stderr == f'{tmp_path}/logs/prompt_{NAME}.err'
    paths = [files.script, files.slurm, files.rates, files.rates_tmp,
             files.stdout, files.stderr]
    for pattern in (f'{NAME}P*', f'{NAME}S*', f'logs/{NAME}_*',
                    f'{NAME}S*.json', 'G0001E0007*'):
        for path in paths:
            rel = os.path.relpath(path, tmp_path)
            assert not fnmatch.fnmatch(rel, pattern), (rel, pattern)

    files.remove_rates()  # nothing there: no error
    Path(files.rates).write_text('{}')
    Path(files.rates_tmp).write_text('{')
    files.remove_rates()
    assert not Path(files.rates).exists()
    assert not Path(files.rates_tmp).exists()


# ===========================================================================
# Fixed channel set (PED label x hot-PES species reachable from it)
# ===========================================================================
def test_fixed_set_three_files_has_eight_channels_in_order() -> None:
    """C4H7 hot first + H_C4H71-3 + H_C4H71-4: 2 PED pairs x 4 C4H7
    species = 8 channels; PED pes sorted, species sorted, FakeW never a
    species, product fragments in mechanalyzer order, thermalised = the hot
    fragment itself; to_payload/from_payload round trip."""
    sop, _ = _sop()
    channels = PromptChannel.fixed_set(sop)
    got = [(c.ped_pes_id, c.hot_pes_id, c.ped_reactant, c.ped_product,
            c.hot_fragment, c.hot_species, c.thermalised,
            c.product_fragments) for c in channels]
    r = 'CH2CHCH2CH3+H'
    assert got == [
        (1, 0, r, 'CH2CHCHCH3+H2', 'CH2CHCHCH3', 'CH2CH2+CH2CH', False,
         ('H2', 'CH2CH2', 'CH2CH')),
        (1, 0, r, 'CH2CHCHCH3+H2', 'CH2CHCHCH3', 'CH2CH2CHCH2', False,
         ('H2', 'CH2CH2CHCH2')),
        (1, 0, r, 'CH2CHCHCH3+H2', 'CH2CHCHCH3', 'CH2CHCHCH2+H', False,
         ('H2', 'CH2CHCHCH2', 'H')),
        (1, 0, r, 'CH2CHCHCH3+H2', 'CH2CHCHCH3', 'CH2CHCHCH3', True,
         ('CH2CHCHCH3', 'H2')),
        (2, 0, r, 'CH2CH2CHCH2+H2', 'CH2CH2CHCH2', 'CH2CH2+CH2CH', False,
         ('H2', 'CH2CH2', 'CH2CH')),
        (2, 0, r, 'CH2CH2CHCH2+H2', 'CH2CH2CHCH2', 'CH2CH2CHCH2', True,
         ('CH2CH2CHCH2', 'H2')),
        (2, 0, r, 'CH2CH2CHCH2+H2', 'CH2CH2CHCH2', 'CH2CHCHCH2+H', False,
         ('H2', 'CH2CHCHCH2', 'H')),
        (2, 0, r, 'CH2CH2CHCH2+H2', 'CH2CH2CHCH2', 'CH2CHCHCH3', False,
         ('H2', 'CH2CHCHCH3')),
    ]
    for channel in channels:
        assert PromptChannel.from_payload(channel.to_payload()) == channel
        assert channel.to_payload()['thermalised'] is channel.thermalised


@pytest.mark.parametrize('order, ped_ids, hot_id', [
    ((C4H7, H3, H4, H2B), [1, 2, 3], 0),
    ((H3, H4, H2B, C4H7), [0, 1, 2], 3)], ids=['hot_first', 'hot_last'])
def test_fixed_set_four_files_has_twelve_channels(order, ped_ids,
                                                  hot_id) -> None:
    """With 2-H_C4H71-3 too: 3 PED pairs x 4 species = 12, in either file
    order; the CH2CHCHCH3+H2 product of two PED PESs gives two separate
    sets of records (nothing merged across PED PESs)."""
    sop, _ = _sop(order)
    channels = PromptChannel.fixed_set(sop)
    assert len(channels) == 12
    assert sorted({c.ped_pes_id for c in channels}) == ped_ids
    assert {c.hot_pes_id for c in channels} == {hot_id}
    assert [c.ped_pes_id for c in channels] == sorted(
        c.ped_pes_id for c in channels)
    therm = [c for c in channels if c.thermalised]
    assert [c.hot_species for c in therm] == [
        'CH2CHCHCH3', 'CH2CH2CHCH2', 'CH2CHCHCH3']


def test_fixed_set_skips_unlinked_ped_file(tmp_path) -> None:
    """2-H_C4H71-3 with the exact reversed pair CH2CHCHCH3+H2=CH3CHCHCH3+H
    (products hot nowhere): no channel for that PES, 8 channels left."""
    for name in (C4H7, H3, H4):
        shutil.copy(C4H8 / name, tmp_path / name)
    text = (C4H8 / H2B).read_text()
    old = 'CH3CHCHCH3+H=CH2CHCHCH3+H2'
    assert text.count(old) == 1
    (tmp_path / H2B).write_text(
        text.replace(old, 'CH2CHCHCH3+H2=CH3CHCHCH3+H'))
    sop, _, reader = _read_sop((C4H7, H3, H4, H2B), root=tmp_path)
    assert reader._trigger_stop is False, reader.klog.errors  # type: ignore
    channels = PromptChannel.fixed_set(sop)
    assert len(channels) == 8
    assert 3 not in {c.ped_pes_id for c in channels}


# ===========================================================================
# Collector writer and emitted script
# ===========================================================================
def _payload_of(script: str) -> dict:
    tree = ast.parse(Path(script).read_text())
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and [t.id for t in node.targets
                     if isinstance(t, ast.Name)] == ['PAYLOAD']):
            return ast.literal_eval(node.value)
    raise AssertionError('no PAYLOAD in the collector script')


def test_writer_payload_and_script(tmp_path, monkeypatch) -> None:
    """The script compiles and embeds the payload: per-PES stems (slot !=
    role: hot pes 0 is P00), exact grid floats, reader grid, prompt
    settings, table sizes and the 8 fixed channels; defaults rovib_dos /
    0.01 when the settings lack them, the settings' values otherwise."""
    env = _env(tmp_path, monkeypatch)
    text = Path(env.files.script).read_text()
    compile(text, env.files.script, 'exec')
    assert 'MPLBACKEND' in text
    payload = _payload_of(env.files.script)
    assert payload == env.writer.payload()
    assert payload['kin_name'] == NAME and payload['model_id'] == MODEL_ID
    assert payload['pes_stems'] == {0: f'{NAME}P00', 1: f'{NAME}P01',
                                    2: f'{NAME}P02'}
    assert payload['grid_pres'] == [0.03, 1.01325]
    assert payload['grid_temp'] == [298.5, 550.0]
    assert payload['reader_pres'] == GRID_P
    assert payload['reader_temp'] == GRID_T
    assert payload['ped_model'] == 'rovib_dos'
    assert payload['bf_threshold'] == 0.01
    assert payload['wells_names'] == list(env.sop.wells_names)
    assert payload['bimols_names'] == list(env.sop.bimols_names)
    assert payload['channels'] == [
        c.to_payload() for c in PromptChannel.fixed_set(env.sop)]
    assert len(payload['channels']) == 8

    bare = {k: v for k, v in _settings().items()
            if k not in ('prompt_ped_model', 'prompt_bf_threshold')}
    payload = PromptCollectorWriter(
        env.sop, bare, NAME, MODEL_ID, env.sop.pes_ids, GRID_P,
        GRID_T).payload()
    assert (payload['ped_model'], payload['bf_threshold']) == (
        'rovib_dos', 0.01)
    payload = PromptCollectorWriter(
        env.sop, _settings(prompt_ped_model='beta_phi1a',
                           prompt_bf_threshold=0), NAME, MODEL_ID,
        env.sop.pes_ids, GRID_P, GRID_T, sub_p=[1.01325],
        sub_t=[550.0]).payload()
    assert payload['ped_model'] == 'beta_phi1a'
    assert payload['bf_threshold'] == 0.0
    assert isinstance(payload['bf_threshold'], float)
    assert (payload['grid_pres'], payload['grid_temp']) == ([1.01325],
                                                            [550.0])
    assert PromptCollectorWriter.grid(env.sop) == (GRID_P, GRID_T)


def test_writer_refuses_inconsistent_inputs(tmp_path) -> None:
    """No prompt channel (H group alone, no hot PES) or a channel PES that
    is not an output of the model: PromptRatesError, no script written."""
    sop, _, _ = _read_sop((H3, H4), prompt=False)
    files = PromptCollectorFiles(loc=str(tmp_path), kin_name=NAME)
    with pytest.raises(PromptRatesError, match='no prompt channel'):
        PromptCollectorWriter(sop, _settings(), NAME, MODEL_ID, sop.pes_ids,
                              GRID_P, GRID_T).write(files)
    assert not Path(files.script).exists()

    sop, _ = _sop()
    with pytest.raises(PromptRatesError, match=r'outputs for PES \[1, 2\]'):
        PromptCollectorWriter(sop, _settings(), NAME, MODEL_ID, [1, 2],
                              GRID_P, GRID_T).write(files)
    assert not Path(files.script).exists()


def test_script_imports_without_automech(tmp_path, monkeypatch,
                                         capsys) -> None:
    """Loading the emitted script needs neither mess_io, mechanalyzer nor
    pandas (imported at run time only); run without them it exits 1 with
    a clear reason and writes nothing."""
    env = _env(tmp_path, monkeypatch)
    for name in ('mess_io', 'mess_io.reader', 'mechanalyzer',
                 'mechanalyzer.calculator'):
        monkeypatch.setitem(sys.modules, name, None)
    namespace = runpy.run_path(env.files.script, run_name='not_main')
    assert namespace['PAYLOAD']['kin_name'] == NAME
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, 'cannot import the collector dependencies')
    assert env.stubs.calls == []


# ===========================================================================
# Collector run on the stored fixture outputs (stand-ins for the deps)
# ===========================================================================
def test_collector_writes_expected_json(tmp_path, monkeypatch,
                                        capsys) -> None:
    """Exit 0; the JSON holds exactly the documented keys, the exact grid
    floats, the 8 fixed channels in order with k = BF * k1 (threshold
    zeros, 1e-30 cut, *** and negative k1 as 0); nothing else written in
    loc or cwd, no tmp left; mess_io read once per PES; ped_frag1 gets the
    hot fragment, the other fragment, the model, the DOS and the product
    DOF, on the PED table renamed to the exact grid; extract_fne unused."""
    env = _env(tmp_path, monkeypatch)
    before = sorted(p.name for p in env.loc.iterdir())
    code, out, err = _run(env, capsys)
    assert code == 0, err
    assert f'Prompt rates of model {MODEL_ID} written to' in out
    assert sorted(p.name for p in env.loc.iterdir()) == sorted(
        before + [Path(env.files.rates).name])
    assert list(env.cwd.iterdir()) == []
    assert os.environ.get('MPLBACKEND') == 'Agg'

    doc = _doc(env)
    assert set(doc) == TOP_KEYS
    assert (doc['format'], doc['version']) == ('kimeco-prompt-rates', 1)
    assert (doc['kin_name'], doc['model_id']) == (NAME, MODEL_ID)
    assert (doc['ped_model'], doc['bf_threshold']) == ('rovib_dos', 0.01)
    assert (doc['pressure_unit'], doc['temperature_unit'], doc['k_unit']) \
        == ('bar', 'K', 'cm3 molecule-1 s-1')
    assert _grid(doc) == ([0.03, 1.01325], [298.5, 550.0])
    expected = [c.to_payload() for c in PromptChannel.fixed_set(env.sop)]
    assert len(_channels(doc)) == 8
    for record, channel in zip(_channels(doc), expected):
        assert set(record) == RECORD_KEYS
        assert {k: v for k, v in record.items() if k != 'k'} == channel
        k = np.array(record['k'])
        assert k.shape == (2, 2)
        np.testing.assert_allclose(k, _expected_k(
            record['ped_pes_id'], record['hot_species']), rtol=1e-14,
            atol=0.0, err_msg=str(record))
    # threshold: below 0.01 everywhere -> all 0.0; 1e-31 -> 0.0 there
    assert _record(doc, 1, 'CH2CH2+CH2CH')['k'] == [[0.0, 0.0], [0.0, 0.0]]
    mid = _record(doc, 1, 'CH2CH2CHCH2')['k']
    assert mid[0][0] == pytest.approx(0.005 * 1.11e-12, rel=1e-14)
    assert mid[0][1] == 0.0

    names = env.stubs.names()
    assert names.count('ped_info') == 2
    assert names.count('calc_dof_dct') == 2
    assert names.count('extract_hot_branching') == 1
    assert 'extract_fne' not in names
    frag = [d for n, d in env.stubs.calls if n == 'ped_frag1']
    assert [(d['hot'], d['other'], d['model'], d['dof']) for d in frag] == [
        ('CH2CHCHCH3', 'H2', 'rovib_dos', 'dof:CH2CHCHCH3+H2'),
        ('CH2CH2CHCH2', 'H2', 'rovib_dos', 'dof:CH2CH2CHCH2+H2')]
    assert [d['dos'] for d in frag] == ['dos:CH2CHCH2CH3+H=CH2CHCHCH3+H2',
                                        'dos:CH2CHCH2CH3+H=CH2CH2CHCH2+H2']
    for d in frag:
        assert d['columns'] == GRID_P and d['index'] == [299.0, 550.0]
    hot = [d for n, d in env.stubs.calls if n == 'bf_tp_df_full']
    assert all(d['hot_columns'] == GRID_P for d in hot)
    assert [d for n, d in env.stubs.calls
            if n == 'extract_hot_branching'][0][1] == 'auto'


def test_collector_sub_grid_writes_only_missing_points(tmp_path, monkeypatch,
                                                       capsys) -> None:
    """kmopp sub-grid (1.01325 bar, 550 K) on the full reader grid: the
    JSON holds that point only, under the exact floats, k1 taken at its
    index in the full .out grid."""
    env = _env(tmp_path, monkeypatch, sub_p=[1.01325], sub_t=[550.0])
    code, _, err = _run(env, capsys)
    assert code == 0, err
    doc = _doc(env)
    assert _grid(doc) == ([1.01325], [550.0])
    therm = _record(doc, 1, 'CH2CHCHCH3')
    assert therm['k'] == [[pytest.approx(0.495 * 4.44e-12, rel=1e-14)]]
    # CH2CH2+CH2CH: 0.005 at the only written point -> dropped
    assert _record(doc, 1, 'CH2CH2+CH2CH')['k'] == [[0.0]]


def test_collector_fne_model_uses_extract_fne_only(tmp_path, monkeypatch,
                                                   capsys) -> None:
    """Model fne: branching fractions from extract_fne (read once per hot
    PES), ped_frag1 and bf_tp_df_full never called, same k as the table."""
    env = _env(tmp_path, monkeypatch, prompt_ped_model='fne')
    code, _, err = _run(env, capsys)
    assert code == 0, err
    names = env.stubs.names()
    assert names.count('extract_fne') == 1
    assert 'ped_frag1' not in names and 'bf_tp_df_full' not in names
    doc = _doc(env)
    assert doc['ped_model'] == 'fne'
    for record in _channels(doc):
        np.testing.assert_allclose(np.array(record['k']), _expected_k(
            record['ped_pes_id'], record['hot_species']), rtol=1e-14,
            atol=0.0)


def test_collector_endothermic_pair_uses_thermal_model(tmp_path, monkeypatch,
                                                       capsys) -> None:
    """A PED reactant below its product (endothermic abstraction) gets the
    'thermal' partition model, the other pair keeps the setting."""
    env = _env(tmp_path, monkeypatch)
    env.stubs.energies = {'CH2CHCHCH3+H2': 5.0}
    code, out, err = _run(env, capsys)
    assert code == 0, err
    models = [(d['hot'], d['model']) for n, d in env.stubs.calls
              if n == 'ped_frag1']
    assert models == [('CH2CHCHCH3', 'thermal'),
                      ('CH2CH2CHCH2', 'rovib_dos')]
    assert 'model thermal' in out


def test_collector_hot_log_pressure_tolerance(tmp_path, monkeypatch,
                                              capsys) -> None:
    """A .log pressure within 1e-4 relative of the grid (1.0132 for
    1.01325) is matched; a farther one (1.012) stops the collector."""
    env = _env(tmp_path, monkeypatch)
    env.stubs.hot_pres = [0.03, 1.0132]
    code, _, err = _run(env, capsys)
    assert code == 0, err

    Path(env.files.rates).unlink()
    env.stubs.hot_pres = [0.03, 1.012]
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, 'grid pressure 1.01325 bar matches')


def test_collector_nan_outside_k1_does_not_stop(tmp_path, monkeypatch,
                                                capsys) -> None:
    """A NaN in a PED .out cell other than k1 is not read by the collector
    (the existing RateCo NaN reset still applies to the model)."""
    env = _env(tmp_path, monkeypatch)
    out = env.loc / f'{NAME}P01.out'
    text = out.read_text()
    assert text.count('1.2000e+02') == 1
    out.write_text(text.replace('1.2000e+02', 'nan'))
    code, _, err = _run(env, capsys)
    assert code == 0, err


# ===========================================================================
# Unit round trip against the KIN rows (RateCo, real MessOutputReader)
# ===========================================================================
class _RecoverQueue:
    def pickUp(self, id: int, jtype: str) -> None:
        return None

    def status(self, id: int, jtype: str) -> JobStatus:
        return JobStatus.PICKED_UP


def _prompt_rateco(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                   **settings: Any) -> RateCo:
    sop, tpls = _sop()
    rc = RateCo(sop=sop, settings=_settings(**settings),
                software_tpls=[list(t) for t in tpls], id=MODEL_ID, q_idx=0,
                name=NAME, loc=str(tmp_path / 'G0001'),
                q_sys=cast(Any, _RecoverQueue()), db=cast(Any, None),
                klog=KMOLogger(filename=str(tmp_path / 'rc.log')))
    Path(rc.loc).mkdir(parents=True)

    def _driver(sop, pes_id, sub_p=None, sub_t=None, settings=None):
        return SimpleNamespace(
            write=lambda loc, filename: Path(loc, filename).write_text('#'))

    monkeypatch.setattr('kimeco.rate_coef.AutomechKinWriter', _driver)
    return rc


@pytest.mark.parametrize('threshold', [0.01, 0.0])
def test_prompt_channels_sum_to_kin_row(tmp_path, monkeypatch, capsys,
                                        threshold) -> None:
    """RateCo writes the collector, the collector runs on the stored
    outputs, RateCo checks the JSON and reads the KIN rows from the same
    .out files. Per PED PES and grid point: the channels sum to the KIN
    abstraction row times (1 - BF of the dropped species) (threshold 0:
    nothing dropped, exactly the row); BF = 1 gives the row itself; k / k1
    = BF (no NAVO, no bar/atm factor); *** and negative k1 give 0.0
    everywhere; one record per (PED PES, channel), CH2CHCHCH2+H under both
    PED PESs."""
    rc = _prompt_rateco(tmp_path, monkeypatch,
                        prompt_bf_threshold=threshold)
    rc.create_input()
    loc = Path(rc.loc)
    assert Path(rc.prompt_files.script).is_file()
    _populate(loc)
    stubs = _Stubs(GRID_P, GRID_T)
    stubs.install(monkeypatch)
    monkeypatch.chdir(tmp_path)
    env = SimpleNamespace(files=rc.prompt_files)
    code, _, err = _run(env, capsys)
    assert code == 0, err

    rows = rc.recover_rslts()
    kin = {(r[4], r[5], r[6], r[1], r[2]): r[7] for r in rows}
    doc = _doc(env)
    assert _grid(doc) == (GRID_P, GRID_T)
    for ped_pes_id, pair in ((1, H3_PAIR), (2, H4_PAIR)):
        hot = HOT_OF[ped_pes_id]
        records = [r for r in _channels(doc) if r['ped_pes_id'] == ped_pes_id]
        assert len(records) == 4
        assert [r['hot_species'] for r in records] == HOT_SPC
        for ip, p in enumerate(GRID_P):
            for it, t in enumerate(GRID_T):
                row = kin[(ped_pes_id, pair[0], pair[1], p, t)]
                assert row == K1[ped_pes_id][ip, it]
                bfs = BF[hot][(p, float(math.floor(t + 0.5)))]
                dropped = sum(
                    bf for spc, bf in zip(HOT_SPC, bfs)
                    if not any(BF[hot][key][HOT_SPC.index(spc)] >= threshold
                               for key in BF[hot])
                    or bf < 1e-30)
                total = sum(_k(r, ip, it) for r in records)
                assert total == pytest.approx(row * (1 - dropped),
                                              rel=1e-12, abs=0.0)
                therm = _record(doc, ped_pes_id, hot)
                if row:
                    assert _k(therm, ip, it) / row == pytest.approx(
                        bfs[HOT_SPC.index(hot)], rel=1e-12)
                else:
                    assert all(_k(r, ip, it) == 0.0 for r in records)
    # BF of the thermalised channel exactly 1 at (0.03 bar, 550 K)
    assert _k(_record(doc, 1, 'CH2CHCHCH3'), 0, 1) == \
        kin[(1, *H3_PAIR, 0.03, 550.0)] == 2.22e-12
    assert _k(_record(doc, 1, 'CH2CHCHCH2+H'), 0, 1) == 0.0
    low = _record(doc, 1, 'CH2CH2+CH2CH')['k']
    if threshold:
        assert low == [[0.0, 0.0], [0.0, 0.0]]
    else:
        assert low[0][0] == pytest.approx(0.005 * 1.11e-12, rel=1e-14)
    assert [r['ped_pes_id'] for r in _channels(doc)
            if r['hot_species'] == 'CH2CHCHCH2+H'] == [1, 2]

    # Step 4: the prompt KIN rows of the same recover_rslts call. One per
    # channel and cell (8 x 4), after the thermal rows; pes_id = PED PES,
    # from_name = PED reactant, to_name = products in mechanalyzer order +
    # '__prompt'; k = the record's k at the cell; the same products under
    # PED PES 1 and 2 are two rows, not a duplicate; band ids of model 7.
    import kimeco.rate_coef as rate_coef
    prompt = [r for r in rows if r[6].endswith('__prompt')]
    thermal = [r for r in rows if not r[6].endswith('__prompt')]
    assert rows == thermal + prompt
    assert len(prompt) == 8 * 4
    r = 'CH2CHCH2CH3+H'
    names = {1: ['H2+CH2CH2+CH2CH__prompt', 'H2+CH2CH2CHCH2__prompt',
                 'H2+CH2CHCHCH2+H__prompt', 'CH2CHCHCH3+H2__prompt'],
             2: ['H2+CH2CH2+CH2CH__prompt', 'CH2CH2CHCH2+H2__prompt',
                 'H2+CH2CHCHCH2+H__prompt', 'H2+CH2CHCHCH3__prompt']}
    assert [c.kin_row_to_name for c in PromptChannel.fixed_set(rc.sop)] == \
        names[1] + names[2]
    keys = [(row[4], row[5], row[6], row[1], row[2]) for row in rows]
    assert len(keys) == len(set(keys))
    assert {row[5] for row in prompt} == {r}
    n_cells, n_ch = len(GRID_P) * len(GRID_T), 8
    for ch_idx, record in enumerate(_channels(doc)):
        ped_pes_id = record['ped_pes_id']
        to_name = '+'.join(record['product_fragments']) + '__prompt'
        assert to_name == names[ped_pes_id][HOT_SPC.index(
            record['hot_species'])]
        for ip, p in enumerate(GRID_P):
            for it, t in enumerate(GRID_T):
                assert kin[(ped_pes_id, r, to_name, p, t)] == _k(record, ip, it)
                row_id = next(row[0] for row in prompt
                              if (row[4], row[6], row[1], row[2])
                              == (ped_pes_id, to_name, p, t))
                assert row_id == (rate_coef.PROMPT_KIN_ROWID_BASE
                                  + MODEL_ID * n_cells * n_ch
                                  + (ip * len(GRID_T) + it) * n_ch + ch_idx)
    low_rows = [row[7] for row in prompt
                if (row[4], row[6]) == (1, 'H2+CH2CH2+CH2CH__prompt')]
    assert len(low_rows) == 4
    if threshold:
        assert low_rows == [0.0] * 4


# ===========================================================================
# Stop paths: exit 1, no JSON, no tmp, the reason on stderr
# ===========================================================================
_INPUTS = [('ped_inp', 1, '.inp'), ('ped_out', 1, '.out'),
           ('ped_ped', 1, '_ped.out'), ('ped_ke', 1, '_ke.out'),
           ('hot_inp', 0, '.inp'), ('hot_log', 0, '.log'),
           ('hot_out', 0, '.out')]


@pytest.mark.parametrize('kind', ['missing', 'empty'])
@pytest.mark.parametrize('what, slot, suffix', _INPUTS,
                         ids=[i[0] for i in _INPUTS])
def test_collector_stops_on_missing_or_empty_input(tmp_path, monkeypatch,
                                                   capsys, what, slot,
                                                   suffix, kind) -> None:
    """Every needed file (every PES .out, PED .inp/_ped.out/_ke.out, hot
    .inp/.log) is checked before any mess_io or mechanalyzer call."""
    env = _env(tmp_path, monkeypatch)
    path = env.loc / f'{NAME}P{slot:02d}{suffix}'
    if kind == 'missing':
        path.unlink()
    else:
        path.write_text('')
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, f'{kind} {path}')
    assert env.stubs.calls == []


def test_collector_lists_every_missing_input_and_refuses_lumping(
        tmp_path, monkeypatch, capsys) -> None:
    env = _env(tmp_path, monkeypatch)
    (env.loc / f'{NAME}P02_ke.out').unlink()
    (env.loc / f'{NAME}P00.log').write_text('')
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, f'missing {env.loc}/{NAME}P02_ke.out',
                   f'empty {env.loc}/{NAME}P00.log')

    (env.loc / f'{NAME}P02_ke.out').write_text('ke\n')
    (env.loc / f'{NAME}P00.log').write_text('log\n')
    hot = env.loc / f'{NAME}P00.inp'
    hot.write_text(hot.read_text() + 'LumpingScheme A+B\n')
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, 'LumpingScheme')
    assert env.stubs.calls == []


@pytest.mark.parametrize('where, exc, needle, extra', [
    ('ped_frag1', SystemExit(), 'stopped with sys.exit(None)', {}),
    ('bf_tp_df_full', SystemExit(0), 'stopped with sys.exit(0)', {}),
    ('extract_hot_branching', SystemExit(), 'sys.exit(None)', {}),
    ('extract_fne', SystemExit(), 'sys.exit(None)',
     {'prompt_ped_model': 'fne'}),
    ('ped_info', IndexError('dos_rovib'), 'IndexError: dos_rovib', {}),
], ids=['ped_frag1_exit', 'bf_exit0', 'hot_reader_exit', 'fne_exit',
        'dos_index_error'])
def test_collector_stops_on_dependency_exit_or_error(tmp_path, monkeypatch,
                                                     capsys, where, exc,
                                                     needle, extra) -> None:
    """mechanalyzer / mess_io sys.exit() (status None or 0 satisfies
    afterok) and exceptions are failures."""
    env = _env(tmp_path, monkeypatch, **extra)
    env.stubs.raise_in[where] = exc
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, needle)
    assert where in env.stubs.names()


_POINT = ('CH2CHCHCH3', 299.0, 0.03)


def _override(value: Any) -> Callable[[str, float, float], Any]:
    def bf(hot: str, temp: float, pres: float) -> Any:
        return value if (hot, temp, pres) == _POINT else None
    return bf


def _bfs(*values: float) -> dict[str, float]:
    return dict(zip(HOT_SPC, values))


@pytest.mark.parametrize('value, needle', [
    (_DROP, 'no value at 0.03 bar, 298.5 K'),
    (float('nan'), 'is not a table of species'),
    (_bfs(0.005, float('nan'), 0.1, 0.89), 'not finite'),
    (_bfs(0.005, float('inf'), 0.1, 0.89), 'not finite'),
    (dict(list(_bfs(0.005, 0.005, 0.1, 0.89).items())[1:]),
     'expected the hot-PES species'),
    ({**_bfs(0.005, 0.005, 0.1, 0.88), 'FakeW-X': 0.01},
     'expected the hot-PES species'),
    (_bfs(0.005, 0.005, 0.1, 0.69), 'sum 0.79'),
    (_bfs(0.005, 0.005, 0.1, 0.89 + 2e-6), 'not 1'),
], ids=['row_dropped', 'nan_cell', 'nan_in_series', 'inf_in_series',
        'species_missing', 'species_extra', 'sum_0p8', 'sum_1p2e-6'])
def test_collector_stops_on_invalid_branching_fractions(
        tmp_path, monkeypatch, capsys, value, needle) -> None:
    env = _env(tmp_path, monkeypatch)
    env.stubs.bf_override = _override(value)
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, needle)


def test_collector_accepts_bf_sum_within_tolerance(tmp_path, monkeypatch,
                                                   capsys) -> None:
    env = _env(tmp_path, monkeypatch)
    env.stubs.bf_override = _override(_bfs(0.005, 0.005, 0.1, 0.89 + 1e-9))
    code, _, err = _run(env, capsys)
    assert code == 0, err


@pytest.mark.parametrize('token', ['nan', '-nan'])
def test_collector_stops_on_nan_k1(tmp_path, monkeypatch, capsys,
                                   token) -> None:
    env = _env(tmp_path, monkeypatch)
    out = env.loc / f'{NAME}P01.out'
    out.write_text(out.read_text().replace('1.11e-12', token))
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err,
                   f'k1 of {H3_PAIR[0]}={H3_PAIR[1]} in {out} is nan at '
                   '0.03 bar, 298.5 K')


def _set(attr: str, value: Any) -> Callable[[_Stubs], None]:
    return lambda stubs: setattr(stubs, attr, value)


@pytest.mark.parametrize('change, needle', [
    (_set('ped_temps', [298.0, 550.0]), 'holds the temperatures [298.0'),
    (_set('hot_temps', [299.0]), 'holds the temperatures [299.0]'),
    (_set('ped_pres', [0.03, 1.01, 0.1]), 'not on the grid'),
    (_set('ped_pres', [0.03]), 'grid pressure 1.01325 bar matches'),
    (_set('ped_missing', True), 'has no energy distribution for'),
    (_set('dof_missing', True), 'no degrees of freedom for CH2CHCHCH3+H2'),
    (_set('energies', {'CH2CHCHCH3+H2': None}), 'TypeError'),
    (_set('hot_species', {'CH2CH2CHCH2': -28.82}),
     'CH2CHCHCH3 is not a HotEnergies well'),
    (_set('ped_cell_override',
          lambda t, p: float('nan') if (t, p) == (550.0, 1.01) else None),
     'is not a valid distribution at 1.01325 bar, 550.0 K'),
], ids=['ped_T_python_round', 'hot_T_missing', 'ped_P_extra',
        'ped_P_missing', 'ped_label_missing', 'dof_missing',
        'energy_not_number', 'hot_fragment_not_hot', 'ped_cell_nan'])
def test_collector_stops_on_table_mismatch(tmp_path, monkeypatch, capsys,
                                           change, needle) -> None:
    """Grid matching before any mechanalyzer call (PED T must be
    floor(T + 0.5), not Python's round), and the per-pair lookups."""
    env = _env(tmp_path, monkeypatch)
    change(env.stubs)
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, needle)


def test_collector_stops_on_label_absent_from_out_or_fne(
        tmp_path, monkeypatch, capsys) -> None:
    """The PED product missing from its .out; the hot fragment missing
    from the fne table."""
    env = _env(tmp_path, monkeypatch)
    out = env.loc / f'{NAME}P01.out'
    out.write_text(out.read_text().replace('CH2CHCHCH3+H2', 'CH2CHCHCH3+HX'))
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err,
                   f'{out} has no rate coefficient of CH2CHCHCH3+H2')

    shutil.copy(DATA / OUTS[H3], out)
    payload = dict(env.writer.payload(), ped_model='fne')
    env.stubs.fne_tables = {}
    assert PromptCollector(payload, str(env.loc)).run() == 1
    assert 'has no fne branching fractions for CH2CHCHCH3' in \
        capsys.readouterr().err
    assert not Path(env.files.rates).exists()


def test_collector_empty_payload_and_energy_missing(tmp_path, monkeypatch,
                                                    capsys) -> None:
    env = _env(tmp_path, monkeypatch)
    payload = dict(env.writer.payload(), channels=[])
    assert PromptCollector(payload, str(env.loc)).run() == 1
    assert 'the payload holds no prompt channel' in capsys.readouterr().err

    original = env.stubs.ped_info

    def _no_product_energy(inp, ped_out, ke_out):
        spc, ped, dos, energies = original(inp, ped_out, ke_out)
        energies.pop('CH2CHCHCH3+H2', None)
        return spc, ped, dos, energies

    sys.modules['mess_io.reader'].ped_info = _no_product_energy  # type: ignore
    code, _, err = _run(env, capsys)
    _assert_failed(env, code, err, 'no energy for CH2CHCHCH3+H2')


def test_collector_failure_keeps_existing_json_removes_tmp(
        tmp_path, monkeypatch, capsys) -> None:
    """On failure only the tmp file goes; a JSON already there is left
    as is (RateCo deletes a stale one before writing the collector)."""
    env = _env(tmp_path, monkeypatch)
    Path(env.files.rates).write_text('old')
    Path(env.files.rates_tmp).write_text('partial')
    env.stubs.raise_in['ped_info'] = SystemExit()
    code, _, err = _run(env, capsys)
    assert code == 1, err
    assert Path(env.files.rates).read_text() == 'old'
    assert not Path(env.files.rates_tmp).exists()


def test_write_atomic_removes_tmp_on_error(tmp_path) -> None:
    files = PromptCollectorFiles(loc=str(tmp_path), kin_name=NAME)
    with pytest.raises(ValueError):
        PromptRatesFile.write_atomic({'k': float('nan')}, files)
    assert list(tmp_path.iterdir()) == []
    PromptRatesFile.write_atomic({'k': 1.0}, files)
    assert json.loads(Path(files.rates).read_text()) == {'k': 1.0}
    assert not Path(files.rates_tmp).exists()


# ===========================================================================
# PromptRatesFile.load_checked: what RateCo accepts
# ===========================================================================
def _valid_doc() -> tuple[dict, list[PromptChannel]]:
    sop, _ = _sop()
    channels = PromptChannel.fixed_set(sop)
    rates = [np.full((2, 2), 1e-12) for _ in channels]
    doc = PromptRatesFile.build(NAME, MODEL_ID, 'rovib_dos', 0.01, GRID_P,
                                GRID_T, channels, rates)
    return doc, channels


_INVALID = {
    'empty_file': (None, 'cannot be read as JSON'),
    'top_level_list': (lambda d: [d], 'not a JSON object'),
    'format': (lambda d: d.update(format='other'), "format 'other'"),
    'version': (lambda d: d.update(version=2), 'version 2'),
    'pressures_rounded': (lambda d: d.update(pressures=[0.03, 1.01]),
                          "'pressures' is [0.03, 1.01]"),
    'temperatures_int': (lambda d: d.update(temperatures=[299.0, 550.0]),
                         "'temperatures'"),
    'one_record_less': (lambda d: d['channels'].pop(),
                        '7 channel records, expected 8'),
    'no_channels_key': (lambda d: d.pop('channels'),
                        'None channel records, expected 8'),
    'identity_swapped': (lambda d: d['channels'].reverse(),
                         'channel record 0 has ped_pes_id 2'),
    'k_shape': (lambda d: d['channels'][3]['k'].pop(),
                "'k' of channel record 3 is not a [2][2] list"),
    'k_negative': (lambda d: d['channels'][0]['k'][1].__setitem__(0, -1e-20),
                   'holds -1e-20'),
    'k_nan': (lambda d: d['channels'][0]['k'][0].__setitem__(0, 'NaNTOKEN'),
              'holds nan'),
    'k_bool': (lambda d: d['channels'][0]['k'][0].__setitem__(0, True),
               'holds True'),
    'k_string': (lambda d: d['channels'][0]['k'][0].__setitem__(0, '1e-12'),
                 "holds '1e-12'"),
}


@pytest.mark.parametrize('case', sorted(_INVALID))
def test_load_checked_refuses_invalid_file(tmp_path, case) -> None:
    edit, needle = _INVALID[case]
    doc, channels = _valid_doc()
    path = tmp_path / 'prompt.json'
    if edit is None:
        path.write_text('')
    else:
        result = edit(doc)
        doc = result if case == 'top_level_list' else doc
        text = json.dumps(doc).replace('"NaNTOKEN"', 'NaN')
        path.write_text(text)
    with pytest.raises(PromptRatesError) as exc:
        PromptRatesFile.load_checked(str(path), channels, GRID_P, GRID_T)
    assert needle in str(exc.value), str(exc.value)
    assert str(path) in str(exc.value)


def test_load_checked_accepts_valid_file(tmp_path) -> None:
    doc, channels = _valid_doc()
    path = tmp_path / 'prompt.json'
    path.write_text(json.dumps(doc))
    assert PromptRatesFile.load_checked(str(path), channels, GRID_P,
                                        GRID_T) == doc


# ===========================================================================
# X1: real mess_io + mechanalyzer on stored MESS outputs (env automech only)
# ===========================================================================
# real/: H_C4H71-3 (ped.inp) and C4H7_hot (hot.inp) with PressureList[bar]
# 0.03 0.1, T 500 550 K, MicroEnerStep 1.0 (H_C4H71-3), run once with the
# env automech mess (2026-10-30, 7 s each); outputs kept untrimmed.
REAL = DATA / 'real'
REAL_T, REAL_P = [500.0, 550.0], [0.03, 0.1]
REAL_PAIR = ('CH2CHCH2CH3+H', 'CH2CHCHCH3+H2')


@pytest.mark.parametrize('threshold', [0.01, 0.0])
def test_collector_real_mechanalyzer(tmp_path, monkeypatch, capsys,
                                     threshold) -> None:
    """The emitted script with the real mess_io and mechanalyzer on real
    MESS outputs (bar in .out, ped.out and .log): exit 0, 4 finite
    records on the exact grid, thermalised k <= k1, the channels sum to
    k1 minus at most the 3 dropped species (threshold 0: exactly k1);
    nothing written to cwd. Skipped without the automech extra, fails
    under KIMECO_REQUIRE_EXTRAS=automech."""
    import_or_skip('automech', 'mess_io.reader')
    import_or_skip('automech', 'mechanalyzer.calculator.bf')
    monkeypatch.delenv('MPLBACKEND', raising=False)
    settings: dict[str, Any] = {
        'init_loc': str(REAL), 'mess_inputs': ['hot.inp', 'ped.inp'],
        'n_exp': 1, 'score_sp': [], 'freq_mode': FreqMode.BATCH,
        'rc_temp': list(REAL_T), 'rc_pres': list(REAL_P),
        'pres_unit': 'bar', 'force_new_molecules': False,
        'prompt_reactions': True}
    reader = MessInputReader(settings=settings, mechanism_species=SPECIES,
                             klog=SpyLog(),  # type: ignore[arg-type]
                             postprocess=False)
    sop, _ = reader.read()
    assert reader._trigger_stop is False
    loc = tmp_path / 'loc'
    loc.mkdir()
    for slot, stem in enumerate(('hot', 'ped')):
        for path in REAL.glob(f'{stem}*'):
            shutil.copy(path, loc / f'{NAME}P{slot:02d}{path.name[3:]}')
    files = PromptCollectorFiles(loc=str(loc), kin_name=NAME)
    PromptCollectorWriter(
        sop, _settings(prompt_bf_threshold=threshold), NAME, MODEL_ID,
        sop.pes_ids, REAL_P, REAL_T).write(files)
    cwd = tmp_path / 'cwd'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    code, _, err = _run(SimpleNamespace(files=files), capsys)
    assert code == 0, err
    assert list(cwd.iterdir()) == []
    doc = json.loads(Path(files.rates).read_text())
    assert _grid(doc) == (REAL_P, REAL_T)
    records = _channels(doc)
    assert [r['hot_species'] for r in records] == HOT_SPC
    from kimeco.readers.mess_output import MessOutputReader
    mor = MessOutputReader(
        filename=str(loc / f'{NAME}P01.out'),
        settings={'postprocess': False, 'rc_temp': REAL_T,
                  'rc_pres': REAL_P},
        sop=sop, klog=cast(Any, SpyLog()))
    mor.read()
    for ip in range(2):
        for it in range(2):
            k1 = mor.rc[ip, it, mor.tbl_map[REAL_PAIR[0]],
                        mor.tbl_map[REAL_PAIR[1]]]
            assert k1 > 0
            values = [_k(r, ip, it) for r in records]
            assert all(math.isfinite(v) and v >= 0 for v in values)
            assert _k(records[HOT_SPC.index('CH2CHCHCH3')], ip, it) <= k1
            assert sum(values) <= k1 * (1 + 1e-9)
            if threshold:
                assert sum(values) >= k1 * (1 - 3 * threshold)
            else:
                assert sum(values) == pytest.approx(k1, rel=1e-9)
