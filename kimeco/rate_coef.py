from genericpath import isfile
import time
from typing import Any

from kimeco.database.kin_db import KIN_DB
from kimeco.parameters import SOP
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.writers.mess import MessWriter
from kimeco.readers.mess_output import MessOutputReader
import os
import numpy as np
from kimeco.logger_config import KMOLogger


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
        self.tbl_map_by_pes: dict[int, dict[str, int]] = {}
        self.rc_by_pes: dict[int, np.ndarray] = {}

    def set_status(self,
                   table: str) -> None:
        status: JobStatus = self.q_sys.status(id=self.q_idx,
                                              jtype='kin')
        if (status == JobStatus.NOT_IN_QUEUE
           and all(os.path.isfile(output_name)
                   for output_name in self.output_names)
           and self.is_in_db(table=table)):
            self.status = JobStatus.FINISHED
        else:
            self.status = status

    def is_in_db(self,
                 table: str) -> bool:
        """Check if the rate coefficients of this object are in the db.


        Args:
            table (str): Generation's name

        Returns:
            bool: Wether data in db correspond to this object.
        """
        db_row_ids: list[int] = self.db.get_ids_from_kin_id(table=table,
                                                            kin_id=self.id)
        n_pairs: int = len(list(self.sop.reaction_iterator()))
        expected_rows: int = len(self.pres) * len(self.temp) * n_pairs
        return len(db_row_ids) == expected_rows

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

        Raises:
            NotImplementedError: Writter for this software doesn't exist yet
        """
        if self.software == 'mess':
            for output_slot, software_tpl in enumerate(self.software_tpls):
                mw = MessWriter(SOP=self.sop, tpl=software_tpl)
                mw.write(loc=self.loc,
                         filename=f'{self.name}P{output_slot:02d}.inp')
        else:
            raise NotImplementedError(
                "K constants calculation with this software not available yet")

    def recover_rslts(self
                      ) -> list[
                          tuple[int, Any, Any, int, int, str, str, float]]:
        """Wait for the results of the Kinetic constants calculations
        """
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
                while not os.stat(output_name).st_size > 0:
                    time.sleep(2)

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
        row_id = int(
            self.id * len(self.pres) * len(self.temp) * len(all_pairs)
        )
        for pidx, p in enumerate(self.pres):
            for tidx, t in enumerate(self.temp):
                for pes_id, from_name, to_name in all_pairs:
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
                        (row_id,
                         p,
                         t,
                         self.id,
                         pes_id,
                         from_name,
                         to_name,
                         k_value)
                    )
                    row_id += 1
        return rows

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
