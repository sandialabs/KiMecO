"""Prompt-rates collector of one model (prompt reactions, automech path).

In prompt mode (``use_automech`` and ``prompt_reactions`` both true) the
rate coefficients of a model are computed by one Slurm array (one automech
MESS driver per PES) followed by one extra job, the **collector**. The
collector starts only once every PES job of the array ended with exit code 0
(``sbatch --dependency=afterok:<array id>``). It reads the MESS outputs of
the model's PESs and writes one **prompt-rates file**: the rate coefficient
``k = BF * k1`` of every prompt channel, where

- ``k1`` is the rate coefficient of the abstraction written by MESS in the
  rate output (``.out``) of the PES that holds the ``PEDSpecies`` entry,
  read with KiMecO's own ``MessOutputReader`` (same value and units as the
  KIN row of that abstraction);
- ``BF`` is the branching fraction of a species of the hot PES, computed by
  mechanalyzer from the product energy distribution (``_ped.out``,
  ``_ke.out``) and the hot-energy branching ratios (``.log``).

Vocabulary (one meaning each, used in every name below):

- **kin name**: ``RateCo.name``, e.g. ``G0001E0007`` (table + model name).
- **PED PES**: MESS input with a ``PEDSpecies`` line (abstraction PES).
- **hot PES**: MESS input with a ``HotEnergies`` block.
- **PED pair**: one ``PEDSpecies`` entry ``<reactant>=<product>``; both sides
  are bimolecular labels of the PED PES.
- **hot fragment**: the product fragment of a PED pair that is a
  ``HotEnergies`` well of the hot PES (mechanalyzer's ``frag1``).
- **prompt link**: (PED PES, PED pair, hot PES) with a hot fragment in that
  hot PES.
- **channel**: one record of the prompt-rates file, i.e. one prompt link and
  one species of the hot PES. The **thermalised channel** is the one whose
  species is the hot fragment itself (same reactant and product as the KIN
  abstraction row).
- **collector**: the per-model script that writes the prompt-rates file;
  **collector id**: its Slurm job id.

This module is imported by ``rate_coef``, ``q_sys`` and ``user_input``: at
module level it imports only the standard library and numpy. pandas,
mess_io, mechanalyzer and ``kimeco.readers.mess_output`` are imported by
``PromptCollector`` at run time, in the ``automech`` environment.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import traceback
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from kimeco.default_settings import default_settings

if TYPE_CHECKING:
    from kimeco.parameters import SOP


class PromptRatesError(Exception):
    """The prompt rate coefficients of a model could not be produced.

    Raised when the collector failed, was cancelled or was not submitted, or
    when the prompt-rates file is missing or invalid. KiMecO treats it as an
    input or setup error and stops the run (no model reset). The collector
    also raises it internally to report a failed check.
    """


def is_prompt_run(settings: dict[str, Any]) -> bool:
    """Tell whether the run computes prompt reactions.

    Prompt mode needs both the automech path and the prompt setting. RateCo
    and QueueingSystem both use this function, so they always agree.

    Args:
        settings (dict[str, Any]): run settings.

    Returns:
        bool: True when ``use_automech`` and ``prompt_reactions`` are true.
    """
    return (bool(settings.get('use_automech'))
            and bool(settings.get('prompt_reactions')))


def mess_written_temperature(temp: float) -> float:
    """Temperature as MESS writes it in ``ped.out`` and in the ``.log``.

    MESS writes ``(int)floor(T + 0.5)`` (MESS ``libmess/mess.cc``). This is
    not Python's ``round()``, which rounds a half to the even integer
    (``round(298.5) == 298`` while MESS writes 299).

    Args:
        temp (float): grid temperature in K.

    Returns:
        float: the integer temperature written by MESS, as a float.
    """
    return float(math.floor(temp + 0.5))


def ped_written_pressure(pres: float) -> float:
    """Pressure as MESS writes it in ``ped.out``.

    MESS writes the ``ped.out`` numbers with ``PedPrecision`` significant
    digits, 3 by default (MESS ``libmess/model.cc``); KiMecO keeps that
    default. For example 1.01325 bar is written 1.01.

    Args:
        pres (float): grid pressure in bar.

    Returns:
        float: the pressure written in ``ped.out``.
    """
    return float(f"{pres:.3g}")


class PromptCollectorFiles:
    """Names of the files of one model's collector.

    Every name starts with ``prompt_<kin name>``, so that no glob of KiMecO
    matches them: not the kin globs (``<kin name>P*``,
    ``logs/<kin name>_*``), not the SIM glob (``<kin name>S*``) and not the
    model-reset glob (``<table><model name>*``).

    Args:
        loc (str): folder of the model's kin files (``RateCo.loc``).
        kin_name (str): kin name of the model, e.g. ``G0001E0007``.
    """

    #: Prefix of every collector file name.
    prefix: str = 'prompt_'

    def __init__(self,
                 loc: str,
                 kin_name: str) -> None:
        self.loc: str = str(loc)
        self.kin_name: str = str(kin_name)

    @property
    def stem(self) -> str:
        """File name without extension, e.g. ``prompt_G0001E0007``."""
        return f"{self.prefix}{self.kin_name}"

    @property
    def script(self) -> str:
        """Path of the collector script (``.py``)."""
        return f"{self.loc}/{self.stem}.py"

    @property
    def slurm(self) -> str:
        """Path of the collector's Slurm submission file (``.slurm``)."""
        return f"{self.loc}/{self.stem}.slurm"

    @property
    def rates(self) -> str:
        """Path of the prompt-rates file (``.json``)."""
        return f"{self.loc}/{self.stem}.json"

    @property
    def rates_tmp(self) -> str:
        """Temporary file renamed into ``rates`` once completely written."""
        return f"{self.rates}.tmp"

    @property
    def stdout(self) -> str:
        """Standard output of the collector job (Slurm ``-o``)."""
        return f"{self.loc}/logs/{self.stem}.stdout"

    @property
    def stderr(self) -> str:
        """Standard error of the collector job (Slurm ``-e``)."""
        return f"{self.loc}/logs/{self.stem}.err"

    def remove_rates(self) -> None:
        """Delete the prompt-rates file and its temporary file, if present."""
        for path in (self.rates, self.rates_tmp):
            if os.path.exists(path):
                os.remove(path)


@dataclass(frozen=True)
class PromptLink:
    """One prompt link: a PED pair of a PED PES whose hot fragment is a
    ``HotEnergies`` well of a hot PES.

    Attributes:
        ped_pes_id: PES id (input file index) of the PED PES.
        hot_pes_id: PES id of the hot PES.
        ped_reactant: reactant side of the PED pair (bimolecular label).
        ped_product: product side of the PED pair (bimolecular label).
        hot_fragment: product fragment that is hot in the hot PES.
    """
    ped_pes_id: int
    hot_pes_id: int
    ped_reactant: str
    ped_product: str
    hot_fragment: str

    @property
    def ped_pair(self) -> str:
        """The PED pair as in ``PEDSpecies``: ``<reactant>=<product>``."""
        return f"{self.ped_reactant}={self.ped_product}"

    @property
    def product_fragments(self) -> tuple[str, ...]:
        """Fragments of the product side, in label order."""
        return tuple(self.ped_product.split('+'))

    @property
    def other_fragments(self) -> tuple[str, ...]:
        """Product fragments left once the hot fragment is removed (its
        first occurrence only), in label order."""
        others = list(self.product_fragments)
        others.remove(self.hot_fragment)
        return tuple(others)

    @property
    def ped_label(self) -> tuple[tuple[str, ...], tuple[str, ...], tuple]:
        """Key of the PED pair in mess_io's ``ped_info`` tables."""
        return (tuple(self.ped_reactant.split('+')),
                self.product_fragments,
                (None,))


#: Suffix of the KIN ``to_name`` of every prompt row (KIN row of one prompt
#: channel at one (P, T) point), e.g. ``H2+CH2CHCHCH2+H__prompt``. It starts
#: with the database separator ``__`` (``kimeco.database.kimeco_db.dbs``),
#: which no species label or fragment may contain, so a prompt row never has
#: the key of a thermal row. A literal, so that this module does not import
#: the database package (sqlalchemy).
PROMPT_TO_NAME_SUFFIX: str = '__prompt'


@dataclass(frozen=True)
class PromptChannel:
    """One channel of the prompt-rates file: a prompt link and one species
    of the hot PES.

    Attributes:
        ped_pes_id: PES id of the PED PES.
        hot_pes_id: PES id of the hot PES.
        ped_reactant: reactant of the PED pair (KIN ``from_name`` of the
            abstraction row).
        ped_product: product of the PED pair (KIN ``to_name`` of the
            abstraction row).
        hot_fragment: product fragment that is hot in the hot PES.
        hot_species: species of the hot PES formed by this channel (well or
            bimolecular label).
        product_fragments: final products of the channel, in mechanalyzer's
            order: the PED product fragments for the thermalised channel,
            else the other PED product fragment(s) then the fragment(s) of
            ``hot_species``.
    """
    ped_pes_id: int
    hot_pes_id: int
    ped_reactant: str
    ped_product: str
    hot_fragment: str
    hot_species: str
    product_fragments: tuple[str, ...]

    @property
    def thermalised(self) -> bool:
        """True when the species is the hot fragment itself (no prompt
        dissociation or isomerisation)."""
        return self.hot_species == self.hot_fragment

    @property
    def kin_row_to_name(self) -> str:
        """``to_name`` of the KIN rows of this channel.

        The final products joined with ``+`` in mechanalyzer's order (not
        sorted), then ``PROMPT_TO_NAME_SUFFIX``: ``CH2CHCHCH3+H2__prompt``
        for a thermalised channel (its PED product),
        ``H2+CH2CHCHCH2+H__prompt`` for a prompt dissociation. The other
        KIN columns of the row are ``pes_id = ped_pes_id`` and
        ``from_name = ped_reactant``.
        """
        return '+'.join(self.product_fragments) + PROMPT_TO_NAME_SUFFIX

    @property
    def link(self) -> PromptLink:
        """The prompt link this channel belongs to."""
        return PromptLink(ped_pes_id=self.ped_pes_id,
                          hot_pes_id=self.hot_pes_id,
                          ped_reactant=self.ped_reactant,
                          ped_product=self.ped_product,
                          hot_fragment=self.hot_fragment)

    def to_payload(self) -> dict[str, Any]:
        """Plain-Python form of the channel (collector payload and JSON
        record without ``k``)."""
        return {
            'ped_pes_id': int(self.ped_pes_id),
            'hot_pes_id': int(self.hot_pes_id),
            'ped_reactant': self.ped_reactant,
            'ped_product': self.ped_product,
            'hot_fragment': self.hot_fragment,
            'hot_species': self.hot_species,
            'thermalised': self.thermalised,
            'product_fragments': list(self.product_fragments),
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> PromptChannel:
        """Rebuild a channel from ``to_payload``'s dictionary.

        Args:
            data (dict[str, Any]): channel dictionary (``thermalised`` is
                ignored: it is derived).

        Returns:
            PromptChannel: the channel.
        """
        return cls(ped_pes_id=int(data['ped_pes_id']),
                   hot_pes_id=int(data['hot_pes_id']),
                   ped_reactant=str(data['ped_reactant']),
                   ped_product=str(data['ped_product']),
                   hot_fragment=str(data['hot_fragment']),
                   hot_species=str(data['hot_species']),
                   product_fragments=tuple(data['product_fragments']))

    @staticmethod
    def _hot_pes_species(sop: SOP,
                         hot_pes_id: int) -> list[tuple[str, tuple[str, ...]]]:
        """Species of a hot PES that receive a branching fraction.

        Non-dummy wells and bimoleculars of the PES, without the AutoMech
        fake wells (mess_io adds the branching fraction of ``FakeW-X`` to
        ``X``), sorted by label.

        Args:
            sop (SOP): set of parameters.
            hot_pes_id (int): PES id of the hot PES.

        Returns:
            list[tuple[str, tuple[str, ...]]]: (label, fragments) pairs; a
            well's fragments are its own label, a bimolecular's the names of
            its two fragments in SOP order.
        """
        species: list[tuple[str, tuple[str, ...]]] = []
        for well in sop.wells_in(hot_pes_id):
            if not well.dummy and 'FakeW' not in well.name:
                species.append((well.name, (well.name,)))
        for bimol in sop.bimols_in(hot_pes_id):
            if not bimol.dummy and 'FakeW' not in bimol.name:
                species.append(
                    (bimol.name, tuple(frag.name for frag in bimol.fragments)))
        return sorted(species)

    @classmethod
    def fixed_set(cls, sop: SOP) -> list[PromptChannel]:
        """The channels of every model of a run (fixed channel set).

        Built only from data that no perturbation changes
        (``SOP.pes_file_data`` and the wells and bimoleculars of each PES),
        so every model of a run has the same channels in the same order:
        PED PES (sorted ids), PED pair (``PEDSpecies`` order, duplicates
        dropped as mess_io does), hot PES (sorted ids), hot-PES species
        (sorted labels). A PED pair whose product has fewer than two
        fragments gives no channel (mechanalyzer skips it too).

        Args:
            sop (SOP): set of parameters read in prompt mode.

        Returns:
            list[PromptChannel]: the channels, possibly empty.

        Raises:
            PromptRatesError: a PED pair has two hot fragments in one hot
                PES (refused when the MESS inputs are read).
        """
        file_data = sorted(sop.pes_file_data.items())
        hot_files = [(fid, data.hot_energies) for fid, data in file_data
                     if data.hot_energies]
        channels: list[PromptChannel] = []
        for ped_pes_id, data in file_data:
            if not data.ped_species:
                continue
            seen_pairs: list[str] = []
            for pair in data.ped_species:
                if pair in seen_pairs:
                    continue
                seen_pairs.append(pair)
                sides = pair.split('=')
                if len(sides) != 2:
                    continue  # malformed: refused when the inputs are read
                reactant, product = sides
                product_frags = product.split('+')
                if len(product_frags) < 2:
                    continue
                for hot_pes_id, hot_energies in hot_files:
                    if hot_pes_id == ped_pes_id:
                        continue
                    hot_frags = [frag for frag in product_frags
                                 if frag in hot_energies]
                    if not hot_frags:
                        continue
                    if len(hot_frags) > 1:
                        raise PromptRatesError(
                            f"PEDSpecies entry '{pair}' of PES {ped_pes_id} "
                            "has two product fragments that are HotEnergies "
                            f"wells of PES {hot_pes_id}.")
                    link = PromptLink(ped_pes_id=ped_pes_id,
                                      hot_pes_id=hot_pes_id,
                                      ped_reactant=reactant,
                                      ped_product=product,
                                      hot_fragment=hot_frags[0])
                    for name, frags in cls._hot_pes_species(sop, hot_pes_id):
                        if name == link.hot_fragment:
                            products = link.product_fragments
                        else:
                            products = link.other_fragments + frags
                        channels.append(cls(
                            ped_pes_id=ped_pes_id,
                            hot_pes_id=hot_pes_id,
                            ped_reactant=reactant,
                            ped_product=product,
                            hot_fragment=link.hot_fragment,
                            hot_species=name,
                            product_fragments=products))
        return channels


#: Body of the emitted collector script. Only ``{payload}`` is substituted
#: (``str.format``): the body holds no other brace.
prompt_collector_tpl = '''\
"""Auto-generated KiMecO prompt-rates collector. Do not edit."""
import os
import sys

# No display on compute nodes (also exported by the .slurm file).
os.environ.setdefault("MPLBACKEND", "Agg")

from kimeco.writers.prompt_collector import PromptCollector  # noqa: E402

PAYLOAD = {payload}

if __name__ == "__main__":
    sys.exit(PromptCollector(
        PAYLOAD, os.path.dirname(os.path.abspath(__file__))).run())
'''


class PromptCollectorWriter:
    """Write the collector script of one model.

    The script embeds everything the collector needs (payload): the grid,
    the prompt settings, the file stem of each PES and the fixed channel
    set. The logic stays in this module (``PromptCollector``).

    Args:
        sop (SOP): the model's set of parameters.
        settings (dict[str, Any]): run settings (``prompt_ped_model``,
            ``prompt_bf_threshold``).
        kin_name (str): kin name of the model, e.g. ``G0001E0007``.
        model_id (int): model id.
        output_pes_ids (list[int]): PES id of each output slot (slot k
            writes ``<kin name>P<k>``), as ``RateCo.output_pes_ids``.
        reader_pres (list[float]): pressure grid (bar) of the
            ``MessOutputReader`` tables (``RateCo.pres``).
        reader_temp (list[float]): temperature grid (K) of the
            ``MessOutputReader`` tables (``RateCo.temp``).
        sub_p (list[float] | None): postprocessing sub-grid pressures, as
            given to the automech drivers; None for the full grid.
        sub_t (list[float] | None): postprocessing sub-grid temperatures;
            None for the full grid.
    """

    def __init__(self,
                 sop: SOP,
                 settings: dict[str, Any],
                 kin_name: str,
                 model_id: int,
                 output_pes_ids: list[int],
                 reader_pres: list[float],
                 reader_temp: list[float],
                 sub_p: list[float] | None = None,
                 sub_t: list[float] | None = None) -> None:
        self.sop: SOP = sop
        self.settings: dict[str, Any] = settings
        self.kin_name: str = kin_name
        self.model_id: int = int(model_id)
        self.output_pes_ids: list[int] = [int(pes_id)
                                          for pes_id in output_pes_ids]
        self.reader_pres: list[float] = [float(p) for p in reader_pres]
        self.reader_temp: list[float] = [float(t) for t in reader_temp]
        self.sub_p: list[float] | None = sub_p
        self.sub_t: list[float] | None = sub_t

    @staticmethod
    def grid(sop: SOP,
             sub_p: list[float] | None = None,
             sub_t: list[float] | None = None
             ) -> tuple[list[float], list[float]]:
        """The (P, T) grid written by the automech drivers of a model.

        Same rule as ``AutomechKinWriter``: the postprocessing sub-grid when
        given, else the SOP grid.

        Args:
            sop (SOP): set of parameters.
            sub_p (list[float] | None): sub-grid pressures or None.
            sub_t (list[float] | None): sub-grid temperatures or None.

        Returns:
            tuple[list[float], list[float]]: pressures (bar) and
            temperatures (K), as exact floats.
        """
        pres = sub_p if sub_p is not None else sop.pres
        temp = sub_t if sub_t is not None else sop.temp
        return [float(p) for p in pres], [float(t) for t in temp]

    def payload(self) -> dict[str, Any]:
        """Everything the collector needs, as plain Python values.

        Returns:
            dict[str, Any]: the payload embedded in the script.
        """
        grid_pres, grid_temp = self.grid(self.sop, self.sub_p, self.sub_t)
        return {
            'kin_name': self.kin_name,
            'model_id': self.model_id,
            'ped_model': str(self.settings.get(
                'prompt_ped_model', default_settings['prompt_ped_model'])),
            'bf_threshold': float(self.settings.get(
                'prompt_bf_threshold',
                default_settings['prompt_bf_threshold'])),
            # Points written by the drivers (and in the prompt-rates file)
            'grid_pres': grid_pres,
            'grid_temp': grid_temp,
            # Grid indexed by MessOutputReader (full rc or pp grid)
            'reader_pres': self.reader_pres,
            'reader_temp': self.reader_temp,
            # Size of the MessOutputReader tables, as in RateCo.recover_rslts
            'wells_names': list(self.sop.wells_names),
            'bimols_names': list(self.sop.bimols_names),
            # {PES id: file stem of its outputs}
            'pes_stems': {
                pes_id: f"{self.kin_name}P{slot:02d}"
                for slot, pes_id in enumerate(self.output_pes_ids)},
            'channels': [channel.to_payload()
                         for channel in PromptChannel.fixed_set(self.sop)],
        }

    def write(self, files: PromptCollectorFiles) -> None:
        """Write the collector script.

        Args:
            files (PromptCollectorFiles): file names of the model's
                collector.

        Raises:
            PromptRatesError: the fixed channel set is empty, or a channel
                names a PES that is not an output of the model.
        """
        payload = self.payload()
        if not payload['channels']:
            raise PromptRatesError(
                f"Model {self.model_id} ({self.kin_name}): no prompt channel "
                "could be built from the MESS inputs (no PEDSpecies product "
                "is a HotEnergies well of another input).")
        stems = payload['pes_stems']
        for channel in payload['channels']:
            for key in ('ped_pes_id', 'hot_pes_id'):
                if channel[key] not in stems:
                    raise PromptRatesError(
                        f"Model {self.model_id} ({self.kin_name}): prompt "
                        f"channel of PES {channel[key]} but the model writes "
                        f"outputs for PES {sorted(stems)} only.")
        with open(files.script, 'w') as handle:
            handle.write(prompt_collector_tpl.format(payload=repr(payload)))


class PromptRatesFile:
    """Format of the prompt-rates file (JSON) written by the collector.

    Top-level keys: ``format``, ``version``, ``kin_name``, ``model_id``,
    ``ped_model``, ``bf_threshold``, ``pressure_unit``, ``temperature_unit``,
    ``k_unit``, ``pressures``, ``temperatures`` and ``channels``. Each
    channel record holds the keys of ``PromptChannel.to_payload`` and ``k``,
    a ``[n_pressures][n_temperatures]`` list in the order of ``pressures``
    and ``temperatures``.
    """

    FORMAT: str = 'kimeco-prompt-rates'
    VERSION: int = 1
    PRESSURE_UNIT: str = 'bar'
    TEMPERATURE_UNIT: str = 'K'
    #: Every PED reactant is a bimolecular label (checked when the MESS
    #: inputs are read): same unit as the KIN row and the MESS ``.out``.
    K_UNIT: str = 'cm3 molecule-1 s-1'
    #: Record keys that identify a channel (checked in order by
    #: ``load_checked``).
    IDENTITY_KEYS: tuple[str, ...] = ('ped_pes_id', 'hot_pes_id',
                                      'ped_reactant', 'ped_product',
                                      'hot_species')

    @classmethod
    def build(cls,
              kin_name: str,
              model_id: int,
              ped_model: str,
              bf_threshold: float,
              pressures: list[float],
              temperatures: list[float],
              channels: list[PromptChannel],
              rates: list[np.ndarray]) -> dict[str, Any]:
        """Content of a prompt-rates file.

        Args:
            kin_name (str): kin name of the model.
            model_id (int): model id.
            ped_model (str): energy-partition model setting.
            bf_threshold (float): branching-fraction threshold setting.
            pressures (list[float]): written pressures (bar).
            temperatures (list[float]): written temperatures (K).
            channels (list[PromptChannel]): fixed channel set.
            rates (list[np.ndarray]): k of each channel, shape
                (n_pressures, n_temperatures).

        Returns:
            dict[str, Any]: the JSON content.
        """
        records: list[dict[str, Any]] = []
        for channel, k_values in zip(channels, rates):
            record = channel.to_payload()
            record['k'] = [[float(value) for value in row]
                           for row in np.asarray(k_values)]
            records.append(record)
        return {
            'format': cls.FORMAT,
            'version': cls.VERSION,
            'kin_name': kin_name,
            'model_id': int(model_id),
            'ped_model': ped_model,
            'bf_threshold': float(bf_threshold),
            'pressure_unit': cls.PRESSURE_UNIT,
            'temperature_unit': cls.TEMPERATURE_UNIT,
            'k_unit': cls.K_UNIT,
            'pressures': [float(p) for p in pressures],
            'temperatures': [float(t) for t in temperatures],
            'channels': records,
        }

    @staticmethod
    def write_atomic(content: dict[str, Any],
                     files: PromptCollectorFiles) -> None:
        """Write the prompt-rates file in one go.

        The content goes to the temporary file, is flushed to disk, then the
        temporary file is renamed into the final name, so a reader never
        sees a partial file. The temporary file is removed on error.

        Args:
            content (dict[str, Any]): JSON content (no NaN or infinity).
            files (PromptCollectorFiles): file names of the collector.
        """
        try:
            with open(files.rates_tmp, 'w') as handle:
                json.dump(content, handle, allow_nan=False, indent=1)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(files.rates_tmp, files.rates)
        except BaseException:
            if os.path.exists(files.rates_tmp):
                os.remove(files.rates_tmp)
            raise

    @staticmethod
    def _is_number(value: Any) -> bool:
        """True for an int or float that is not a bool."""
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @classmethod
    def load_checked(cls,
                     path: str,
                     channels: list[PromptChannel],
                     pressures: list[float],
                     temperatures: list[float]) -> dict[str, Any]:
        """Read a prompt-rates file and check it against the expected
        channels and grid.

        Args:
            path (str): path of the prompt-rates file.
            channels (list[PromptChannel]): expected fixed channel set.
            pressures (list[float]): expected pressures (exact floats).
            temperatures (list[float]): expected temperatures (exact floats).

        Returns:
            dict[str, Any]: the parsed content.

        Raises:
            PromptRatesError: the file is unreadable, has another format or
                version, another grid, other channels, a ``k`` of the wrong
                shape, or a value that is not a finite non-negative number.
        """
        def invalid(reason: str) -> PromptRatesError:
            return PromptRatesError(f"Invalid prompt-rates file {path}: "
                                    f"{reason}")

        try:
            with open(path, 'r') as handle:
                content = json.load(handle)
        except (OSError, ValueError) as exc:
            raise invalid(f"cannot be read as JSON ({exc}).") from exc
        if not isinstance(content, dict):
            raise invalid("the top level is not a JSON object.")
        if (content.get('format') != cls.FORMAT
                or content.get('version') != cls.VERSION):
            raise invalid(
                f"format {content.get('format')!r} version "
                f"{content.get('version')!r}, expected {cls.FORMAT!r} "
                f"version {cls.VERSION}.")
        for key, expected in (('pressures', pressures),
                              ('temperatures', temperatures)):
            expected = [float(value) for value in expected]
            if content.get(key) != expected:
                raise invalid(f"'{key}' is {content.get(key)!r}, expected "
                              f"{expected!r}.")
        records = content.get('channels')
        if not isinstance(records, list) or len(records) != len(channels):
            count = len(records) if isinstance(records, list) else None
            raise invalid(f"{count} channel records, expected "
                          f"{len(channels)}.")
        n_p, n_t = len(pressures), len(temperatures)
        for idx, (record, channel) in enumerate(zip(records, channels)):
            if not isinstance(record, dict):
                raise invalid(f"channel record {idx} is not an object.")
            expected_record = channel.to_payload()
            for key in cls.IDENTITY_KEYS:
                if record.get(key) != expected_record[key]:
                    raise invalid(
                        f"channel record {idx} has {key} "
                        f"{record.get(key)!r}, expected "
                        f"{expected_record[key]!r}.")
            k_values = record.get('k')
            if (not isinstance(k_values, list) or len(k_values) != n_p
                    or not all(isinstance(row, list) and len(row) == n_t
                               for row in k_values)):
                raise invalid(f"'k' of channel record {idx} is not a "
                              f"[{n_p}][{n_t}] list.")
            for row in k_values:
                for value in row:
                    if (not cls._is_number(value) or not math.isfinite(value)
                            or value < 0):
                        raise invalid(
                            f"'k' of channel record {idx} holds {value!r}, "
                            "not a finite non-negative number.")
        return content


class PromptCollector:
    """Run-time part of the collector: compute the prompt rate coefficients
    of one model and write its prompt-rates file.

    Runs in the ``automech`` environment, in the model's kin folder, after
    every PES job of the model ended (``afterok``). Nothing is written to
    the folder but the prompt-rates file.

    Args:
        payload (dict[str, Any]): payload written by
            ``PromptCollectorWriter``.
        workdir (str): folder of the model's kin files (the script's own
            folder, ``RateCo.loc``).
    """

    #: Branching fractions below this value give k = 0.0 (mechanalyzer's
    #: lower cut, ``bf_tp_df_todct``).
    BF_LOWER_CUT: float = 1e-30
    #: Largest accepted |sum of the branching fractions - 1| at a point.
    BF_SUM_TOLERANCE: float = 1e-6
    #: Relative tolerance between a grid pressure and the pressure of the
    #: ``.log`` (as ``MessOutputReader._safe_index``).
    LOG_PRESSURE_REL_TOL: float = 1e-4
    #: Relative tolerance between a 3-digit grid pressure and a ``ped.out``
    #: pressure (float parsing only).
    PED_PRESSURE_REL_TOL: float = 1e-9

    def __init__(self,
                 payload: dict[str, Any],
                 workdir: str) -> None:
        self.payload: dict[str, Any] = payload
        self.workdir: str = str(workdir)
        self.kin_name: str = str(payload['kin_name'])
        self.model_id: int = int(payload['model_id'])
        self.files: PromptCollectorFiles = PromptCollectorFiles(
            loc=self.workdir, kin_name=self.kin_name)
        self.ped_model: str = str(payload['ped_model'])
        self.bf_threshold: float = float(payload['bf_threshold'])
        self.grid_pres: list[float] = [float(p) for p in payload['grid_pres']]
        self.grid_temp: list[float] = [float(t) for t in payload['grid_temp']]
        self.reader_pres: list[float] = [float(p)
                                         for p in payload['reader_pres']]
        self.reader_temp: list[float] = [float(t)
                                         for t in payload['reader_temp']]
        self.pes_stems: dict[int, str] = {
            int(pes_id): str(stem)
            for pes_id, stem in payload['pes_stems'].items()}
        self.channels: list[PromptChannel] = [
            PromptChannel.from_payload(data) for data in payload['channels']]
        # Per-PES caches of what mess_io and mechanalyzer read
        self._k1_by_ped_pes: dict[int, dict[tuple[str, str], np.ndarray]] = {}
        self._ped_tables: dict[int, SimpleNamespace] = {}
        self._hot_tables: dict[int, SimpleNamespace] = {}
        self._deps: SimpleNamespace | None = None

    # ---- entry point ----

    def run(self) -> int:
        """Compute and write the prompt-rates file.

        Every failure (own check, exception, ``sys.exit()`` of mess_io or
        mechanalyzer, even with status 0) prints
        ``PROMPT COLLECTOR FAILED (model <id>, <kin name>): <reason>`` to
        stderr and writes no file.

        Returns:
            int: 0 when the prompt-rates file was written, else 1.
        """
        try:
            content = self._collect()
            PromptRatesFile.write_atomic(content, self.files)
        except PromptRatesError as exc:
            reason = str(exc)
        except SystemExit as exc:
            reason = (f"stopped with sys.exit({exc.code!r}); see the lines "
                      "printed above in the .stdout log")
        except Exception as exc:
            traceback.print_exc()
            reason = f"{type(exc).__name__}: {exc}"
        else:
            print(f"Prompt rates of model {self.model_id} written to "
                  f"{self.files.rates}", flush=True)
            return 0
        if os.path.exists(self.files.rates_tmp):
            os.remove(self.files.rates_tmp)
        sys.stdout.flush()
        print(f"PROMPT COLLECTOR FAILED (model {self.model_id}, "
              f"{self.kin_name}): {reason}", file=sys.stderr, flush=True)
        return 1

    def _collect(self) -> dict[str, Any]:
        """All the steps of the collector, without the final write.

        Returns:
            dict[str, Any]: content of the prompt-rates file.
        """
        self._check_input_files()
        self._deps = self._import_dependencies()
        rates_by_channel: dict[PromptChannel, np.ndarray] = {}
        for link in self._links():
            link_channels = [channel for channel in self.channels
                             if channel.link == link]
            k1 = self._k1(link)
            bf_table = self._branching_fractions(link)
            rates_by_channel.update(
                self._channel_rates(link, link_channels, k1, bf_table))
        rates = [rates_by_channel[channel] for channel in self.channels]
        for channel, k_values in zip(self.channels, rates):
            if not np.all(np.isfinite(k_values)) or np.any(k_values < 0):
                raise PromptRatesError(
                    f"channel {channel.ped_reactant} -> "
                    f"{'+'.join(channel.product_fragments)} has a rate "
                    "coefficient that is not a finite non-negative number.")
        return PromptRatesFile.build(
            kin_name=self.kin_name,
            model_id=self.model_id,
            ped_model=self.ped_model,
            bf_threshold=self.bf_threshold,
            pressures=self.grid_pres,
            temperatures=self.grid_temp,
            channels=self.channels,
            rates=rates)

    # ---- inputs ----

    def _path(self, pes_id: int, suffix: str) -> str:
        """Path of an output of one PES, e.g. ``<stem>_ped.out``.

        Args:
            pes_id (int): PES id.
            suffix (str): ``.inp``, ``.out``, ``.log``, ``_ped.out`` or
                ``_ke.out``.

        Returns:
            str: absolute path in the work folder.
        """
        return f"{self.workdir}/{self.pes_stems[pes_id]}{suffix}"

    @staticmethod
    def _read(path: str) -> str:
        """Text of a file."""
        with open(path, 'r') as handle:
            return handle.read()

    def _links(self) -> list[PromptLink]:
        """The prompt links of the channel set, in channel order."""
        links: list[PromptLink] = []
        for channel in self.channels:
            if channel.link not in links:
                links.append(channel.link)
        return links

    def _required_inputs(self) -> list[str]:
        """Files the collector needs, each once, in a stable order.

        Every PES rate output (a failed MESS run on any PES of the model
        stops the run); for each PED PES its input, PED output and
        microcanonical output; for each hot PES its input and log.
        """
        paths: list[str] = [self._path(pes_id, '.out')
                            for pes_id in sorted(self.pes_stems)]
        for link in self._links():
            for pes_id, suffix in ((link.ped_pes_id, '.inp'),
                                   (link.ped_pes_id, '_ped.out'),
                                   (link.ped_pes_id, '_ke.out'),
                                   (link.hot_pes_id, '.inp'),
                                   (link.hot_pes_id, '.log')):
                path = self._path(pes_id, suffix)
                if path not in paths:
                    paths.append(path)
        return paths

    def _check_input_files(self) -> None:
        """Check that every needed file exists and is not empty, before any
        mess_io or mechanalyzer call; refuse lumped hot-PES inputs.

        Raises:
            PromptRatesError: listing every missing or empty file, or a hot
                input that holds ``LumpingScheme``.
        """
        if not self.channels:
            raise PromptRatesError("the payload holds no prompt channel.")
        problems: list[str] = []
        for path in self._required_inputs():
            if not os.path.isfile(path):
                problems.append(f"missing {path}")
            elif os.stat(path).st_size == 0:
                problems.append(f"empty {path}")
        if problems:
            raise PromptRatesError(
                "MESS files of the model are missing or empty (a PES job "
                "failed): " + '; '.join(problems))
        for hot_pes_id in sorted({link.hot_pes_id for link in self._links()}):
            path = self._path(hot_pes_id, '.inp')
            if 'LumpingScheme' in self._read(path):
                raise PromptRatesError(
                    f"{path} lumps wells (LumpingScheme): mess_io cannot "
                    "read the species of a lumped hot PES.")

    @staticmethod
    def _import_dependencies() -> SimpleNamespace:
        """Import the run-time dependencies (``automech`` environment).

        Returns:
            SimpleNamespace: ``reader`` (mess_io.reader), ``bf``,
            ``ene_partition``, ``nonboltz`` (mechanalyzer.calculator),
            ``pandas`` and ``MessOutputReader``.

        Raises:
            PromptRatesError: a dependency cannot be imported.
        """
        try:
            import pandas
            from mess_io import reader
            from mechanalyzer.calculator import bf, ene_partition, nonboltz
            from kimeco.readers.mess_output import MessOutputReader
        except ImportError as exc:
            raise PromptRatesError(
                f"cannot import the collector dependencies ({exc}); run it "
                "from the environment that has mess_io and "
                "mechanalyzer.") from exc
        return SimpleNamespace(reader=reader, bf=bf,
                               ene_partition=ene_partition,
                               nonboltz=nonboltz, pandas=pandas,
                               MessOutputReader=MessOutputReader)

    # ---- k1 from the PED PES rate output ----

    def _k1(self, link: PromptLink) -> np.ndarray:
        """Rate coefficient k1 of a PED pair on the written grid.

        Read from the PED PES ``.out`` with ``MessOutputReader``, negative
        values set to 0.0 as ``RateCo.recover_rslts`` does, ``***`` read as
        0.0. Units: those of the ``.out`` and of the KIN row.

        Args:
            link (PromptLink): prompt link of the PED pair.

        Returns:
            np.ndarray: k1, shape (n_pressures, n_temperatures).

        Raises:
            PromptRatesError: the pair is not in the output, a grid point is
                not in the reader grid, or k1 is not finite.
        """
        if link.ped_pes_id not in self._k1_by_ped_pes:
            self._k1_by_ped_pes[link.ped_pes_id] = {}
        cache = self._k1_by_ped_pes[link.ped_pes_id]
        key = (link.ped_reactant, link.ped_product)
        if key in cache:
            return cache[key]
        reader = self._rate_output(link.ped_pes_id)
        path = self._path(link.ped_pes_id, '.out')
        for label in key:
            if label not in reader.tbl_map:
                raise PromptRatesError(
                    f"{path} has no rate coefficient of {label} (PED pair "
                    f"{link.ped_pair}).")
        i_from, i_to = reader.tbl_map[key[0]], reader.tbl_map[key[1]]
        k1 = np.zeros((len(self.grid_pres), len(self.grid_temp)))
        for ip, pres in enumerate(self.grid_pres):
            for it, temp in enumerate(self.grid_temp):
                if (pres not in self.reader_pres
                        or temp not in self.reader_temp):
                    raise PromptRatesError(
                        f"grid point ({pres} bar, {temp} K) is not in the "
                        "grid of the rate outputs.")
                value = float(reader.rc[self.reader_pres.index(pres),
                                        self.reader_temp.index(temp),
                                        i_from, i_to])
                if not math.isfinite(value):
                    raise PromptRatesError(
                        f"k1 of {link.ped_pair} in {path} is {value} at "
                        f"{pres} bar, {temp} K (master equation not "
                        "converged).")
                k1[ip, it] = value
        cache[key] = k1
        return k1

    def _rate_output(self, pes_id: int) -> Any:
        """``MessOutputReader`` of a PES rate output, read and clamped.

        Args:
            pes_id (int): PES id.

        Returns:
            MessOutputReader: the read output (``rc`` < 0 set to 0.0).
        """
        sop_sizes = SimpleNamespace(
            wells_names=list(self.payload['wells_names']),
            bimols_names=list(self.payload['bimols_names']))
        reader = self._deps.MessOutputReader(
            filename=self._path(pes_id, '.out'),
            settings={'postprocess': False,
                      'rc_temp': list(self.reader_temp),
                      'rc_pres': list(self.reader_pres)},
            sop=sop_sizes,
            klog=logging.getLogger('kimeco.prompt_collector'))
        reader.read()
        reader.rc[reader.rc < 0] = 0.0
        return reader

    # ---- tables read by mess_io ----

    def _ped_pes_tables(self, ped_pes_id: int) -> SimpleNamespace:
        """PED tables of a PED PES (read once).

        Returns:
            SimpleNamespace: ``ped`` ({PED label: DataFrame[T, P]}),
            ``dos`` (fragment densities of states), ``energies``
            ({MESS label: energy}) and ``dof`` ({product label: degrees of
            freedom}).
        """
        if ped_pes_id not in self._ped_tables:
            reader = self._deps.reader
            inp = self._read(self._path(ped_pes_id, '.inp'))
            ped_spc, ped_dct, dos_df, energy_dct = reader.ped_info(
                inp,
                self._read(self._path(ped_pes_id, '_ped.out')),
                self._read(self._path(ped_pes_id, '_ke.out')))
            dof_dct = self._deps.nonboltz.calc_dof_dct(inp, ped_spc)
            self._ped_tables[ped_pes_id] = SimpleNamespace(
                ped=ped_dct, dos=dos_df, energies=energy_dct, dof=dof_dct)
        return self._ped_tables[ped_pes_id]

    def _hot_pes_tables(self, hot_pes_id: int) -> SimpleNamespace:
        """Hot-energy tables of a hot PES (read once).

        Returns:
            SimpleNamespace: ``hot_species`` ({hot well: energy}),
            ``branching`` ({hot well: DataFrame[T, P]}), ``fne`` (None until
            ``_fne_table`` reads it), ``log`` (text of the ``.log``).
        """
        if hot_pes_id not in self._hot_tables:
            hoten = self._deps.reader.hoten
            inp = self._read(self._path(hot_pes_id, '.inp'))
            log = self._read(self._path(hot_pes_id, '.log'))
            species_blocks = self._deps.reader.get_species(inp)
            hot_spc_en = hoten.get_hot_species(inp)
            hoten_dct = hoten.extract_hot_branching(
                log, hot_spc_en, list(species_blocks), sp_labels='auto')
            self._hot_tables[hot_pes_id] = SimpleNamespace(
                hot_species=hot_spc_en, branching=hoten_dct, fne=None,
                log=log)
        return self._hot_tables[hot_pes_id]

    # ---- grid matching ----

    def _check_temperatures(self, table: Any, what: str) -> None:
        """Check that a table holds exactly the MESS-written grid
        temperatures.

        Args:
            table: DataFrame indexed by temperature.
            what (str): description of the table for messages.

        Raises:
            PromptRatesError: the temperatures differ, or two grid
                temperatures are written as the same integer.
        """
        expected = {mess_written_temperature(t) for t in self.grid_temp}
        found = {float(t) for t in table.index}
        if len(expected) != len(self.grid_temp) or found != expected:
            raise PromptRatesError(
                f"{what} holds the temperatures {sorted(found)} K; the grid "
                f"{self.grid_temp} K is written by MESS as "
                f"{sorted(expected)} K.")

    def _remap_pressures(self,
                         table: Any,
                         written: Callable[[float], float],
                         rel_tol: float,
                         what: str) -> Any:
        """Rename the pressure columns of a table to the exact grid floats.

        Each grid pressure, as MESS writes it (``written``), must match
        exactly one column, and every column one grid pressure.

        Args:
            table: DataFrame with one column per pressure.
            written (Callable[[float], float]): grid pressure -> pressure as
                written in the file.
            rel_tol (float): relative tolerance of the match.
            what (str): description of the table for messages.

        Returns:
            DataFrame: the table with the grid pressures as columns.

        Raises:
            PromptRatesError: a grid pressure matches no column or several,
                or a column matches no grid pressure.
        """
        columns = list(table.columns)
        mapping: dict[Any, float] = {}
        for pres in self.grid_pres:
            matches = [col for col in columns
                       if math.isclose(float(col), written(pres),
                                       rel_tol=rel_tol)]
            if len(matches) != 1 or matches[0] in mapping:
                raise PromptRatesError(
                    f"{what}: grid pressure {pres} bar matches the columns "
                    f"{matches} of {columns} (one expected).")
            mapping[matches[0]] = pres
        extra = [col for col in columns if col not in mapping]
        if extra:
            raise PromptRatesError(
                f"{what} holds pressures {extra} that are not on the grid "
                f"{self.grid_pres} bar.")
        return table.rename(columns=mapping)

    def _ped_table(self, link: PromptLink) -> Any:
        """PED table of a PED pair on the exact grid, checked.

        Raises:
            PromptRatesError: the pair has no PED, the grid differs, or a
                cell is not a non-empty distribution of finite values.
        """
        tables = self._ped_pes_tables(link.ped_pes_id)
        path = self._path(link.ped_pes_id, '_ped.out')
        if link.ped_label not in tables.ped:
            raise PromptRatesError(
                f"{path} has no energy distribution for {link.ped_pair} "
                f"(found {sorted(tables.ped)}).")
        what = f"PED of {link.ped_pair} in {path}"
        ped_df = self._remap_pressures(tables.ped[link.ped_label],
                                       ped_written_pressure,
                                       self.PED_PRESSURE_REL_TOL, what)
        self._check_temperatures(ped_df, what)
        series_type = self._deps.pandas.Series
        for pres in self.grid_pres:
            for temp in self.grid_temp:
                cell = ped_df.at[mess_written_temperature(temp), pres]
                if (not isinstance(cell, series_type) or cell.empty
                        or not np.all(np.isfinite(cell.to_numpy(float)))):
                    raise PromptRatesError(
                        f"{what} is not a valid distribution at {pres} bar, "
                        f"{temp} K.")
        return ped_df

    def _hot_table(self, link: PromptLink) -> Any:
        """Hot-energy branching table of the hot fragment on the exact
        grid.

        Raises:
            PromptRatesError: the hot fragment is not a hot well of the hot
                PES, or the grid differs.
        """
        tables = self._hot_pes_tables(link.hot_pes_id)
        path = self._path(link.hot_pes_id, '.log')
        if (link.hot_fragment not in tables.hot_species
                or link.hot_fragment not in tables.branching):
            raise PromptRatesError(
                f"{link.hot_fragment} is not a HotEnergies well of "
                f"{self._path(link.hot_pes_id, '.inp')}.")
        what = f"hot branching of {link.hot_fragment} in {path}"
        hot_df = self._remap_pressures(tables.branching[link.hot_fragment],
                                       float, self.LOG_PRESSURE_REL_TOL, what)
        self._check_temperatures(hot_df, what)
        return hot_df

    def _fne_table(self, link: PromptLink) -> Any:
        """Branching fractions of the ``fne`` model for the hot fragment, on
        the exact grid (``extract_fne`` runs only for this model).

        Raises:
            PromptRatesError: the log has no fne table for the hot fragment,
                or the grid differs.
        """
        tables = self._hot_pes_tables(link.hot_pes_id)
        if tables.fne is None:
            tables.fne = self._deps.reader.hoten.extract_fne(
                tables.log, sp_labels='auto')
        path = self._path(link.hot_pes_id, '.log')
        fne_df = tables.fne.get(link.hot_fragment)
        if fne_df is None:
            raise PromptRatesError(
                f"{path} has no fne branching fractions for "
                f"{link.hot_fragment}.")
        what = f"fne branching of {link.hot_fragment} in {path}"
        fne_df = self._remap_pressures(fne_df, float,
                                       self.LOG_PRESSURE_REL_TOL, what)
        self._check_temperatures(fne_df, what)
        return fne_df

    # ---- branching fractions and channel rates ----

    def _branching_fractions(self, link: PromptLink) -> Any:
        """Branching-fraction table of a prompt link (mechanalyzer).

        The energy-partition model is ``thermal`` when the PED reactant lies
        below the product (endothermic abstraction), else the
        ``prompt_ped_model`` setting, as in mechanalyzer.

        Returns:
            DataFrame: ``[T, P]`` table of Series indexed by hot-PES species.

        Raises:
            PromptRatesError: an energy or a degree-of-freedom entry of the
                PED pair is missing.
        """
        ped_df = self._ped_table(link)
        hot_df = self._hot_table(link)
        tables = self._ped_pes_tables(link.ped_pes_id)
        for label in (link.ped_reactant, link.ped_product):
            if label not in tables.energies:
                raise PromptRatesError(
                    f"no energy for {label} in "
                    f"{self._path(link.ped_pes_id, '.inp')}.")
        ene_bw = (tables.energies[link.ped_reactant]
                  - tables.energies[link.ped_product])
        model = 'thermal' if ene_bw < 0 else self.ped_model
        print(f"Prompt link {link.ped_pair} (PES {link.ped_pes_id}) -> "
              f"hot {link.hot_fragment} (PES {link.hot_pes_id}): "
              f"model {model}", flush=True)
        if model == 'fne':
            return self._fne_table(link)
        if link.ped_product not in tables.dof:
            raise PromptRatesError(
                f"no degrees of freedom for {link.ped_product} in "
                f"{self._path(link.ped_pes_id, '.inp')}.")
        ped_df_frag1 = self._deps.ene_partition.ped_frag1(
            ped_df, link.hot_fragment, link.other_fragments[0], model,
            dos_df=tables.dos, dof_info=tables.dof[link.ped_product])
        return self._deps.bf.bf_tp_df_full(ped_df_frag1, hot_df)

    def _branching_values(self,
                          link: PromptLink,
                          species: list[str],
                          bf_table: Any) -> dict[str, np.ndarray]:
        """Branching fraction of each hot-PES species at every grid point.

        Args:
            link (PromptLink): prompt link of the table.
            species (list[str]): hot-PES species of the link's channels.
            bf_table: ``[T, P]`` table of Series indexed by species.

        Returns:
            dict[str, np.ndarray]: {species: BF, shape (n_p, n_t)}.

        Raises:
            PromptRatesError: a grid point is missing, a cell is not a
                Series, its species differ from the channels', a value is
                not finite, or the fractions do not sum to 1.
        """
        series_type = self._deps.pandas.Series
        expected = set(species)
        values = {name: np.zeros((len(self.grid_pres), len(self.grid_temp)))
                  for name in species}
        what = f"branching fractions of {link.ped_pair} -> {link.hot_fragment}"
        for ip, pres in enumerate(self.grid_pres):
            for it, temp in enumerate(self.grid_temp):
                temp_written = mess_written_temperature(temp)
                if (pres not in bf_table.columns
                        or temp_written not in bf_table.index):
                    raise PromptRatesError(
                        f"{what}: no value at {pres} bar, {temp} K (row "
                        "dropped by mechanalyzer: NaN or empty distribution).")
                cell = bf_table.at[temp_written, pres]
                where = f"{what} at {pres} bar, {temp} K"
                if not isinstance(cell, series_type):
                    raise PromptRatesError(f"{where}: {cell!r} is not a "
                                           "table of species.")
                found = {str(name) for name in cell.index}
                if found != expected:
                    raise PromptRatesError(
                        f"{where}: species {sorted(found)}, expected the "
                        f"hot-PES species {sorted(expected)}.")
                fractions = cell.to_numpy(float)
                if not np.all(np.isfinite(fractions)):
                    raise PromptRatesError(f"{where}: not finite.")
                if abs(float(np.sum(fractions)) - 1.0) > self.BF_SUM_TOLERANCE:
                    raise PromptRatesError(
                        f"{where}: sum {float(np.sum(fractions))}, not 1.")
                for name in species:
                    values[name][ip, it] = float(cell[name])
        return values

    def _channel_rates(self,
                       link: PromptLink,
                       channels: list[PromptChannel],
                       k1: np.ndarray,
                       bf_table: Any) -> dict[PromptChannel, np.ndarray]:
        """Rate coefficients k = BF * k1 of the channels of a prompt link.

        A species is kept when its BF reaches ``bf_threshold`` at one grid
        point at least (mechanalyzer's rule); a species not kept gets 0.0
        everywhere. A BF below ``BF_LOWER_CUT`` gives 0.0 at that point.
        No upper cut: the thermalised channel is kept. The channels of a
        link sum to k1 minus the species not kept.

        Returns:
            dict[PromptChannel, np.ndarray]: {channel: k, shape (n_p, n_t)}.
        """
        bf_values = self._branching_values(
            link, [channel.hot_species for channel in channels], bf_table)
        rates: dict[PromptChannel, np.ndarray] = {}
        for channel in channels:
            fractions = bf_values[channel.hot_species]
            kept = bool(np.any(fractions >= self.bf_threshold))
            if kept:
                rates[channel] = np.where(fractions >= self.BF_LOWER_CUT,
                                          fractions * k1, 0.0)
            else:
                rates[channel] = np.zeros_like(k1)
        return rates
