from genericpath import isfile
import time
from typing import Any

# PP_KIN_ROWID_BASE is re-exported for existing imports
from kimeco.database.kin_db import KIN_DB, PP_KIN_ROWID_BASE  # noqa: F401
from kimeco.parameters import SOP
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.writers.mess import MessWriter
from kimeco.writers.automech_kin import AutomechKinWriter
from kimeco.writers.prompt_collector import (
    PROMPT_TO_NAME_SUFFIX, PromptChannel, PromptCollectorFiles,
    PromptCollectorWriter, PromptRatesError, PromptRatesFile, is_prompt_run)
from kimeco.readers.mess_output import MessOutputReader
import os
import numpy as np
from kimeco.logger_config import KMOLogger

#: Seconds RateCo waits for the prompt-rates file once the collector left
#: the Slurm queue: NFS can hide a file just written on a compute node
#: (60 s is the default NFS attribute cache time, acdirmax).
PROMPT_RATES_WAIT_S: float = 60
#: Seconds between two checks for the prompt-rates file.
PROMPT_RATES_POLL_S: float = 2
#: First row id of the prompt rows of an optimisation run (prompt mode).
#: Ids of the thermal rows: below it (model ``id`` holds
#: ``id * n_p * n_t * n_pairs`` onwards); ids of model ``id``'s prompt rows:
#: ``PROMPT_KIN_ROWID_BASE + id * n_p * n_t * n_channels`` onwards; ids of
#: postprocessing rows: ``PP_KIN_ROWID_BASE`` onwards (``KIN_DB.pp_row_ids``).
PROMPT_KIN_ROWID_BASE: int = PP_KIN_ROWID_BASE // 2   # 5 * 10**11


class RateCo:
    """Wrapper around different calculators
    for kinetic constants calculation.
    """
    def __init__(self,
                 sop: SOP,
                 settings: dict,
                 software_tpls: list[list[str]],
                 id: int,
                 q_idx: int,
                 name: str,
                 loc: str,
                 q_sys: QueueingSystem,
                 db: KIN_DB,
                 klog: KMOLogger
                 ) -> None:
        self.klog: KMOLogger = klog
        self.status: JobStatus = JobStatus.NOT_IN_QUEUE
        self.id: int = id
        self.sop: SOP = sop
        self.software: str = settings['rc_software'].casefold()
        self.software_tpls: list[list[str]] = software_tpls
        self.output_pes_ids: list[int] = list(self.sop.pes_ids)
        if len(self.software_tpls) != len(self.output_pes_ids):
            raise ValueError(
                'MESS template count does not match SOP PES count: '
                f'{len(self.software_tpls)} templates for '
                f'{len(self.output_pes_ids)} PES IDs.'
            )
        self.name: str = name
        self.settings: dict[str, Any] = settings
        if self.settings['postprocess']:
            self.pres = self.settings['pp_pres']
            self.temp = self.settings['pp_temp']
        else:
            self.pres = self.settings['rc_pres']
            self.temp = self.settings['rc_temp']
        self.loc: str = loc + f'/{(self.id)//50:02d}'
        self.q_sys: QueueingSystem = q_sys
        self.db: KIN_DB = db
        # Modulable if something else than mess is used.
        if self.software == 'mess':
            self.output_names: list[str] = [
                f"{self.loc}/{self.name}P{output_slot:02d}.out"
                for output_slot in range(len(self.software_tpls))
            ]
        else:
            self.output_names: list[str] = [
                f"{self.loc}/{self.name}P{output_slot:02d}.out"
                for output_slot in range(len(self.software_tpls))
            ]
        self.q_idx: int = q_idx
        # Prompt mode (use_automech and prompt_reactions): a collector job
        # writes the prompt-rates file of the model (prompt_files.rates).
        self.prompt_reactions: bool = is_prompt_run(settings)
        self.prompt_files: PromptCollectorFiles = PromptCollectorFiles(
            loc=self.loc, kin_name=self.name)
        self.tbl_map_by_pes: dict[int, dict[str, int]] = {}
        self.rc_by_pes: dict[int, np.ndarray] = {}
        # (P,T) cells not yet persisted for this object (postprocessing).
        self.missing_grid: list[tuple[float, float]] = []
        # Generation table that missing_grid was evaluated on.
        self.table: str | None = None

    def set_status(self,
                   table: str) -> None:
        """Set the status of the rate coefficients calculation.

        A job not in the queue whose outputs exist and whose rates are all
        in the database is FINISHED (restart). In prompt mode this also
        needs the prompt-rates file, and a collector whose sbatch failed
        stops the run.

        Args:
            table (str): Generation's name

        Raises:
            PromptRatesError: prompt mode, the collector of this model could
                not be submitted.
        """
        status: JobStatus = self.q_sys.status(id=self.q_idx,
                                              jtype='kin')
        if (self.prompt_reactions
                and self.q_sys.collector_submit_failed(self.q_idx)):
            raise PromptRatesError(
                f"The prompt collector of {self.name} (model {self.id}) "
                "could not be submitted (sbatch failed, see the error "
                "above). Its PES jobs may still run: check squeue for the "
                "jobs of this run before restarting.")
        # Always evaluate is_in_db so self.missing_grid is populated even
        # before the output files exist (needed for per-(P,T) skipping).
        full_grid_present: bool = self.is_in_db(table=table)
        if (status == JobStatus.NOT_IN_QUEUE
           and all(os.path.isfile(output_name)
                   for output_name in self.output_names)
           and full_grid_present
           and (not self.prompt_reactions
                or os.path.isfile(self.prompt_files.rates))):
            self.status = JobStatus.FINISHED
        else:
            self.status = status

    def is_in_db(self,
                 table: str) -> bool:
        """Check if the rate coefficients of this object are in the db and
        record the still-missing (P,T) cells in ``self.missing_grid``.

        A (P,T) cell is present when it holds ``n_pairs`` thermal rows (one
        per pair of ``sop.reaction_iterator()``) and, in prompt mode, also
        one prompt row per channel of the fixed set. Prompt rows (``to_name``
        ending with ``PROMPT_TO_NAME_SUFFIX``) never count as thermal rows,
        in either mode.

        Args:
            table (str): Generation's name

        Returns:
            bool: True when every (P,T) cell is present (normal-run parity).
        """
        self.table = table
        rows = self.db.get_rates_for_kin_id(table=table,
                                            kin_id=self.id)
        n_pairs: int = len(list(self.sop.reaction_iterator()))
        # Prompt rows needed per cell: none outside prompt mode.
        n_channels: int = (len(PromptChannel.fixed_set(self.sop))
                           if self.prompt_reactions else 0)
        # Number of stored rows per rounded (P,T) cell, thermal and prompt
        # rows counted apart.
        thermal_counts: dict[tuple[float, float], int] = {}
        prompt_counts: dict[tuple[float, float], int] = {}
        for p, t, _pes_id, _from_name, to_name, *_ in rows:
            key = (round(p, 5), round(t, 5))
            if str(to_name).endswith(PROMPT_TO_NAME_SUFFIX):
                prompt_counts[key] = prompt_counts.get(key, 0) + 1
            else:
                thermal_counts[key] = thermal_counts.get(key, 0) + 1
        present: set[tuple[float, float]] = {
            key for key, count in thermal_counts.items()
            if count >= n_pairs and prompt_counts.get(key, 0) >= n_channels
        }
        self.missing_grid = [
            (p, t)
            for p in self.pres
            for t in self.temp
            if (round(p, 5), round(t, 5)) not in present
        ]
        return len(self.missing_grid) == 0

    def q_up(self) -> None:
        """Generate and submit a Kinetic
        Constants calculation
        """
        if self.status in {
           JobStatus.NOT_IN_QUEUE,
           JobStatus.FAILED}:
            cpu: int = self.settings['cpu_kin']
            mem: int = self.settings['mem_kin']
            self.create_input()
            self.q_sys.add_to_q(
                name=self.name,
                idx=self.q_idx,
                location=self.loc,
                jtype='kin',
                ressources=(cpu, mem),
                n_pes=len(self.software_tpls)
                                )

    def create_input(self) -> None:
        """Create an input for the selected solftware.

        In prompt mode the collector script is written too, after the
        prompt-rates file of an earlier submission was deleted.

        Raises:
            NotImplementedError: Writter for this software doesn't exist yet
        """
        if self.software == 'mess':
            sub_p, sub_t = self._sub_grid()
            if self.settings.get('use_automech', False):
                if self.prompt_reactions:
                    # Stale file of an earlier submission (e.g. reset model)
                    self.prompt_files.remove_rates()
                for output_slot in range(len(self.software_tpls)):
                    aw = AutomechKinWriter(
                        sop=self.sop,
                        pes_id=self.output_pes_ids[output_slot],
                        sub_p=sub_p,
                        sub_t=sub_t,
                        settings=self.settings)
                    aw.write(loc=self.loc,
                             filename=f'{self.name}P{output_slot:02d}.py')
                if self.prompt_reactions:
                    PromptCollectorWriter(
                        sop=self.sop,
                        settings=self.settings,
                        kin_name=self.name,
                        model_id=self.id,
                        output_pes_ids=self.output_pes_ids,
                        reader_pres=self.pres,
                        reader_temp=self.temp,
                        sub_p=sub_p,
                        sub_t=sub_t).write(self.prompt_files)
            else:
                for output_slot, software_tpl in enumerate(self.software_tpls):
                    mw = MessWriter(SOP=self.sop, tpl=software_tpl,
                                    pres=sub_p, temp=sub_t)
                    mw.write(loc=self.loc,
                             filename=f'{self.name}P{output_slot:02d}.inp')
        else:
            raise NotImplementedError(
                "K constants calculation with this software not available yet")

    def _sub_grid(self) -> tuple[list[float] | None, list[float] | None]:
        """Postprocessing sub-grid of the (P, T) cells still missing from
        the database.

        Returns:
            tuple[list[float] | None, list[float] | None]: sorted pressures
            and temperatures of ``missing_grid`` in postprocessing, else
            (None, None) for the full grid.
        """
        sub_p: list[float] | None = None
        sub_t: list[float] | None = None
        if self.settings['postprocess'] and self.missing_grid:
            sub_p = sorted({p for p, _ in self.missing_grid})
            sub_t = sorted({t for _, t in self.missing_grid})
        return sub_p, sub_t

    def _check_prompt_rates(self) -> dict[str, Any]:
        """Check the prompt-rates file written by the collector (prompt
        mode).

        Waits up to ``PROMPT_RATES_WAIT_S`` for the file (NFS), then checks
        it against the fixed channel set and the grid of the drivers.

        Returns:
            dict[str, Any]: the checked content (records in fixed-set order,
            grid of the drivers).

        Raises:
            PromptRatesError: the file is missing or invalid.
        """
        path: str = self.prompt_files.rates
        waited: float = 0.0
        while not os.path.isfile(path) and waited < PROMPT_RATES_WAIT_S:
            time.sleep(PROMPT_RATES_POLL_S)
            waited += PROMPT_RATES_POLL_S
        if not os.path.isfile(path):
            raise PromptRatesError(
                f"No prompt-rates file {path} for {self.name} (model "
                f"{self.id}): the collector failed, was cancelled by Slurm "
                "because a PES job exited with an error "
                "(--kill-on-invalid-dep), or never ran. See "
                f"{self.prompt_files.stderr} and {self.prompt_files.stdout}.")
        pressures, temperatures = PromptCollectorWriter.grid(
            self.sop, *self._sub_grid())
        return PromptRatesFile.load_checked(
            path=path,
            channels=PromptChannel.fixed_set(self.sop),
            pressures=pressures,
            temperatures=temperatures)

    def recover_rslts(self
                      ) -> list[
                          tuple[int, Any, Any, int, int, str, str, float]]:
        """Wait for the results of the Kinetic constants calculations

        In prompt mode the prompt-rates file is checked first: a missing or
        invalid file stops the run (PromptRatesError). The returned rows are
        then the thermal rows, followed by the prompt rows (one per channel
        of the fixed set and (P,T) cell, see ``_prompt_rows``).
        """
        # Checked content of the prompt-rates file (prompt mode only).
        prompt_content: dict[str, Any] | None = None
        if self.prompt_reactions:
            prompt_content = self._check_prompt_rates()
        rows: list[tuple[int, Any, Any, int, int, str, str, float]] = []
        outputs: dict[int, MessOutputReader] = {}
        for output_slot, output_name in enumerate(self.output_names):
            pes_id = self.output_pes_ids[output_slot]
            i = 0
            while not isfile(output_name):
                time.sleep(2)
                if i == 10:
                    self.klog.info(f'{output_name} not found after 20s.')
                    i = 0
                    return rows
                i += 1
            else:
                retry = 0
                while not os.stat(output_name).st_size > 0:
                    time.sleep(6)
                    retry += 1
                    if retry == 20:
                        self.klog.error(
                            f'{output_name} is empty after 2 minutes.')
                        raise FileNotFoundError(
                            f'{output_name} is empty after 2 minutes.')

            if self.software == 'mess':
                mor = MessOutputReader(filename=output_name,
                                       settings=self.settings,
                                       sop=self.sop,
                                       klog=self.klog)
                mor.read()
                mor.rc[mor.rc < 0] = 0.0
                outputs[pes_id] = mor
            else:
                raise NotImplementedError('Unknown master equation software.')

        self.q_sys.pickUp(id=self.q_idx,
                          jtype='kin')
        if (self.q_sys.status(id=self.q_idx, jtype='kin')
           == JobStatus.FAILED):
            self.klog.info(f'Resetting KIN job {self.id}')
            self.status = JobStatus.FAILED

        for mor in outputs.values():
            if np.isnan(mor.rc).any():
                self.status = JobStatus.FAILED
                self.klog.warning(
                    f'Resetting model {self.id}: '
                    'NaN detected in rate coefficients.'
                )
                self.klog.warning(
                    'The master equation likely didn\'t converge properly.')

        self.tbl_map_by_pes = {
            pes_id: dict(mor.tbl_map)
            for pes_id, mor in outputs.items()
        }
        self.rc_by_pes = {
            pes_id: np.array(mor.rc, copy=True)
            for pes_id, mor in outputs.items()
        }

        all_pairs: list[tuple[int, str, str]] = list(
            self.sop.reaction_iterator()
        )
        n_p: int = len(self.pres)
        n_t: int = len(self.temp)
        n_pairs: int = len(all_pairs)
        # In postprocessing, only the missing (P,T) cells are recomputed and
        # appended; present cells stay untouched.
        partial: bool = bool(
            self.settings['postprocess'] and self.missing_grid)
        if partial:
            missing: set[tuple[float, float]] = {
                (round(p, 5), round(t, 5)) for p, t in self.missing_grid
            }
        else:
            missing = set()
        base_id: int = int(self.id * n_p * n_t * n_pairs)
        for pidx, p in enumerate(self.pres):
            for tidx, t in enumerate(self.temp):
                if partial and (round(p, 5), round(t, 5)) not in missing:
                    continue
                cell_base: int = base_id + (pidx * n_t + tidx) * n_pairs
                for pair_idx, (pes_id, from_name, to_name) in enumerate(
                        all_pairs):
                    k_value: float = 0.0
                    if pes_id in outputs:
                        mor = outputs[pes_id]
                        if (from_name in mor.tbl_map and
                                to_name in mor.tbl_map and
                                mor.tbl_map != {}):
                            from_idx: int = mor.tbl_map[from_name]
                            to_idx: int = mor.tbl_map[to_name]
                            k_value = float(
                                mor.rc[pidx, tidx, from_idx, to_idx]
                            )
                    rows.append(
                        (cell_base + pair_idx,
                         p,
                         t,
                         self.id,
                         pes_id,
                         from_name,
                         to_name,
                         k_value)
                    )
        if prompt_content is not None:
            # Appended after the thermal rows: a missing .out above still
            # returns [] and the thermal rows keep their ids and order. In
            # postprocessing the single pp_row_ids call below gives the
            # prompt rows their ids too.
            rows.extend(self._prompt_rows(content=prompt_content,
                                          n_pairs=n_pairs,
                                          partial=partial,
                                          missing=missing))
        if partial and rows:
            # The table may already hold rows of an earlier postprocessing
            # on another (P,T) grid: ids derived from this grid's layout
            # would overwrite them, so the database allocates the ids.
            if self.table is None:
                raise RuntimeError(
                    'is_in_db() must run before recover_rslts() '
                    'in postprocessing.')
            ids: list[int] = self.db.pp_row_ids(
                table=self.table,
                kin_id=self.id,
                keys=[(row[1], row[2], row[4], row[5], row[6])
                      for row in rows])
            rows = [(row_id, *row[1:]) for row_id, row in zip(ids, rows)]
        return rows

    def _prompt_rows(self,
                     content: dict[str, Any],
                     n_pairs: int,
                     partial: bool,
                     missing: set[tuple[float, float]]
                     ) -> list[
                         tuple[int, Any, Any, int, int, str, str, float]]:
        """KIN rows of the prompt channels of this model (prompt mode).

        A prompt row is the KIN row of one channel of the fixed set at one
        (P,T) cell: ``(id, P, T, kin_id, pes_id, from_name, to_name, k)``
        with ``pes_id = ped_pes_id``, ``from_name = ped_reactant`` and
        ``to_name = kin_row_to_name`` (taken from the fixed set, never from
        the file). P and T are the exact values of ``self.pres`` and
        ``self.temp``, as in the thermal rows; k is read from the file at
        the same P and T values, in KIN units. Channels whose k is zero are
        stored too. Rows come cell by cell (``self.pres`` then
        ``self.temp`` order), in fixed-set order within a cell.

        Row ids of an optimisation run (the prompt band):
        ``PROMPT_KIN_ROWID_BASE + id * n_p * n_t * n_channels
        + (pidx * n_t + tidx) * n_channels + ch_idx``, ``ch_idx`` being the
        index of the channel in the fixed set. In postprocessing only the
        missing cells are built and ``recover_rslts`` replaces these ids by
        those of ``KIN_DB.pp_row_ids``.

        Args:
            content (dict[str, Any]): checked content of the prompt-rates
                file (``_check_prompt_rates``): record ``i`` of
                ``content['channels']`` belongs to channel ``i`` of the
                fixed set.
            n_pairs (int): number of thermal pairs (thermal rows per cell).
            partial (bool): postprocessing of the missing cells only.
            missing (set[tuple[float, float]]): rounded (P,T) cells still
                missing from the database (postprocessing).

        Returns:
            list[tuple[int, Any, Any, int, int, str, str, float]]: the
            prompt rows.

        Raises:
            PromptRatesError: two channels give the same KIN row key, the
                row ids would leave their band (optimisation run), or a
                grid value is absent from the file.
        """
        channels: list[PromptChannel] = PromptChannel.fixed_set(self.sop)
        records: list[dict[str, Any]] = content['channels']
        self._check_prompt_row_keys(channels)
        n_channels: int = len(channels)
        if not partial:
            self._check_prompt_row_ids(n_pairs=n_pairs,
                                       n_channels=n_channels)
        # Position of each pressure / temperature value in the k tables of
        # the file: full grid in an optimisation run, sorted sub-grid
        # rectangle of missing_grid in postprocessing.
        file_pidx: dict[float, int] = {
            float(p): idx for idx, p in enumerate(content['pressures'])}
        file_tidx: dict[float, int] = {
            float(t): idx for idx, t in enumerate(content['temperatures'])}
        n_p: int = len(self.pres)
        n_t: int = len(self.temp)
        # First prompt row id of this model.
        model_base: int = int(PROMPT_KIN_ROWID_BASE
                              + self.id * n_p * n_t * n_channels)
        rows: list[tuple[int, Any, Any, int, int, str, str, float]] = []
        for pidx, p in enumerate(self.pres):
            for tidx, t in enumerate(self.temp):
                if partial and (round(p, 5), round(t, 5)) not in missing:
                    continue
                if p not in file_pidx or t not in file_tidx:
                    raise PromptRatesError(
                        f"The prompt-rates file {self.prompt_files.rates} of "
                        f"{self.name} (model {self.id}) has no k at "
                        f"P = {p} bar, T = {t} K.")
                cell_base: int = model_base + (pidx * n_t + tidx) * n_channels
                for ch_idx, (channel, record) in enumerate(
                        zip(channels, records)):
                    rows.append(
                        (cell_base + ch_idx,
                         p,
                         t,
                         self.id,
                         channel.ped_pes_id,
                         channel.ped_reactant,
                         channel.kin_row_to_name,
                         float(record['k'][file_pidx[p]][file_tidx[t]]))
                    )
        return rows

    def _check_prompt_row_keys(self,
                               channels: list[PromptChannel]) -> None:
        """Stop when two prompt channels would give the same KIN row.

        KiMecO stores one KIN row per (PES, from_name, to_name) at a (P,T)
        cell and does not sum prompt channels. Two channels clash when they
        share ``ped_pes_id``, ``ped_reactant`` and ``kin_row_to_name``: for
        example a PED pair whose hot fragment is a ``HotEnergies`` well of
        two hot PESs (both thermalised channels give
        ``<ped_product>__prompt``). The same products in another order give
        another to_name, hence no clash.

        Args:
            channels (list[PromptChannel]): the fixed channel set.

        Raises:
            PromptRatesError: some channels clash; the message lists every
                clashing key with its channels.
        """
        # Channels of each KIN row key (pes_id, from_name, to_name).
        channels_by_key: dict[tuple[int, str, str], list[PromptChannel]] = {}
        for channel in channels:
            key = (channel.ped_pes_id, channel.ped_reactant,
                   channel.kin_row_to_name)
            channels_by_key.setdefault(key, []).append(channel)
        clashes: list[str] = []
        for (pes_id, from_name, to_name), same_key in channels_by_key.items():
            if len(same_key) < 2:
                continue
            sources = '; '.join(
                f"hot PES {channel.hot_pes_id}, PED pair "
                f"{channel.link.ped_pair}, hot species {channel.hot_species}"
                for channel in same_key)
            clashes.append(f"PES {pes_id}, from_name {from_name}, "
                           f"to_name {to_name} ({sources})")
        if clashes:
            raise PromptRatesError(
                f"{self.name} (model {self.id}): several prompt channels give "
                "the same KIN row. KiMecO stores one KIN row per (PES, "
                "from_name, to_name) and does not sum prompt channels. "
                "Clashing rows: " + ' | '.join(clashes) + '.')

    def _check_prompt_row_ids(self,
                              n_pairs: int,
                              n_channels: int) -> None:
        """Stop when the KIN row ids of this model would leave their band
        (prompt mode, optimisation run).

        Thermal ids must stay below ``PROMPT_KIN_ROWID_BASE`` and prompt ids
        below ``PP_KIN_ROWID_BASE`` (an end equal to its limit passes: the
        last id is the end minus one). Both ends grow with the model id, so
        when every model of a table passes, every thermal id is below every
        prompt id, every prompt id is below the postprocessing ids, and the
        prompt blocks of two models do not overlap.

        Args:
            n_pairs (int): thermal rows per (P,T) cell.
            n_channels (int): prompt rows per (P,T) cell.

        Raises:
            PromptRatesError: one of the two blocks of this model would pass
                its limit.
        """
        n_cells: int = len(self.pres) * len(self.temp)
        model_id: int = int(self.id)
        # First id after this model's thermal block, then its prompt block.
        thermal_end: int = (model_id + 1) * n_cells * n_pairs
        prompt_end: int = (PROMPT_KIN_ROWID_BASE
                           + (model_id + 1) * n_cells * n_channels)
        if (thermal_end > PROMPT_KIN_ROWID_BASE
                or prompt_end > PP_KIN_ROWID_BASE):
            raise PromptRatesError(
                f"{self.name} (model {self.id}): too many models x (P, T) "
                "points x reactions for the KIN row ids of prompt mode. "
                f"Thermal ids [{thermal_end - n_cells * n_pairs}, "
                f"{thermal_end}) must end at or below "
                f"{PROMPT_KIN_ROWID_BASE}; prompt ids "
                f"[{prompt_end - n_cells * n_channels}, {prompt_end}) must "
                f"end at or below {PP_KIN_ROWID_BASE}.")

    def load_rates_from_db(self,
                           table: str) -> None:
        """Rebuild PES-scoped rate arrays from persisted KIN_DB rows."""
        rows = self.db.get_rates_for_kin_id(table=table,
                                            kin_id=self.id)
        self.tbl_map_by_pes = {}
        self.rc_by_pes = {}
        for pes_id in self.sop.pes_ids:
            species_names = self.sop.species_names_in_pes(pes_id)
            tbl_map = {
                name: idx
                for idx, name in enumerate(species_names)
            }
            rc = np.zeros((
                len(self.pres),
                len(self.temp),
                len(species_names),
                len(species_names),
            ))
            self.tbl_map_by_pes[pes_id] = tbl_map
            self.rc_by_pes[pes_id] = rc

        for p, t, pes_id, from_name, to_name, k_value in rows:
            if pes_id not in self.rc_by_pes:
                continue
            if p not in self.pres or t not in self.temp:
                continue
            tbl_map = self.tbl_map_by_pes[pes_id]
            if from_name not in tbl_map or to_name not in tbl_map:
                continue
            p_idx = self.pres.index(p)
            t_idx = self.temp.index(t)
            from_idx = tbl_map[from_name]
            to_idx = tbl_map[to_name]
            self.rc_by_pes[pes_id][p_idx, t_idx, from_idx, to_idx] = k_value
