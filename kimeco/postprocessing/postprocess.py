import sys
import os
import numpy as np
from kimeco._kimeco import KiMecO
from kimeco.database.kin_db import KIN_DB
import time
from kimeco.element import Element
from kimeco.enums import ElementStatus
from kimeco.goat import GOATs
from kimeco.parameters import SOP
from kimeco.postprocessing.extrapolate import Extrapolate


class PostProcess(KiMecO):
    def __init__(self,
                 input_file: str,
                 init_loc: str = os.getcwd(),
                 name: str = 'PostProcess') -> None:
        super().__init__(
            input_file=input_file,
            init_loc=init_loc,
            name=name)
        self.settings['postprocess'] = True

    def set_initial_sop(self,
                        postprocess=True) -> None:
        """Overide parent method to link postprocess conditions
        to the SOP
        """
        super().set_initial_sop(
            postprocess=postprocess
        )

    def initialize_databases(self) -> None:
        super().initialize_databases()
        start_time: float = time.time()
        self.pp_db = KIN_DB(sop=self.init_SOP,
                            name='PP_DB_KIN',
                            threads=self.settings['threads'],
                            path=self.settings['workdir'])
        kin_db_time: float = time.time() - start_time
        msg = 'Extrapolation_DB initialized:'
        self.klog.info(f"{msg:<65}{kin_db_time:>15.1f}")

    def load_goats(self) -> None:
        """Load the goat file from the run to create a
        GOATs object for postprocessing.
        """
        goat_file: str = f"{self.settings['workdir']}/goats.txt"
        # Always construct GOATs from the same goat.txt used previously
        self.goats: GOATs = GOATs.from_file(
            filename=goat_file,
            sop_db=self.sop_db,
            kin_db=self.kin_db,
            sim_db=self.sim_db,
        )

    def set_postprocessing(self) -> None:
        """Set parameters for postprocessing"""
        self.klog.info(f"{'Postprocessing parameters:':<65}")
        self.klog.info(
            f"{'Temperatures (K):':<65}{str(self.settings['pp_temp']):>15}")
        pu: str = f'{self.settings["pres_unit"]}'
        self.klog.info(
            f"{f'Pressures ({pu}):':<65}{str(self.settings['pp_pres']):>15}")
        # Loop over user-requested ensembles
        ensembles: list[str] = self.settings['pp_ensembles']

        for token in ensembles:
            name: str = token

            # Precompute token type flags
            cond_g: bool = token.startswith('G') and len(token) == 5 and \
                token[1:].isdigit()
            cond_nms: bool = token == 'NMS'
            cond_gt: bool = token.startswith('GT')
            cond_nm: bool = token.startswith('NM')

            # Generation table: G####
            if cond_g:
                elements: list[Element] = self.get_generation(token)
            # GOATs generation: GT####
            elif cond_gt:
                gen_id = int(token[2:])
                elements: list[Element] = []
                try:
                    goats_elements = self.goats.get_goat_for_gen(gen_id)
                except Exception as e:
                    self.klog.warning(f"Could not load GOATs for {token}: {e}")
                    continue
                for idx, el in enumerate(goats_elements):
                    elements.append(Element(
                        sop=el.sop,
                        id=idx,
                        gen=el.gen,
                        status=ElementStatus.SOP.value
                    ))
                if gen_id >= 0:
                    name = token
                else:
                    name = f"GT{len(self.goats) - 1:04d}"

            # NMSG Nelder-Mead Swarm Generation: NMSG####
            elif cond_nms:
                elements = []
                # Find the size of the ensemble
                nms_cond_g = self.settings['NMS_start'].startswith('G') and \
                    self.settings['NMS_start'][1:].isdigit()
                nms_cond_gt = self.settings['NMS_start'].startswith('GT') and \
                    self.settings['NMS_start'][2:].lstrip('-').isdigit()
                if nms_cond_g:
                    tot_elem: int = self.settings['n_elem']
                elif nms_cond_gt:
                    tot_elem = self.settings['goat_length']
                else:
                    raise NotImplementedError(
                        "NMS_start not recognized for NMSG postprocessing.")
                # Find all NMSG tables in the SOP DB
                NMS_gens: list[int] = [
                    int(tbl_name.split('NMSG')[-1])
                    for tbl_name in self.sop_db.tables
                    if tbl_name.startswith('NMSG')]
                if not NMS_gens:
                    raise ValueError(
                        "No NMSG tables found in SOP DB for postprocessing.")
                max_NMS_gen: int = max(NMS_gens)
                # Load elements from NMSG tables, starting from the
                # highest generation until all elements are found
                els2load: list[float] = [i for i in range(tot_elem)]
                for gen in range(max_NMS_gen, -1, -1):
                    table_name: str = f'NMSG{gen:04d}'
                    try:
                        rows = self.sop_db.get_table(table_name)
                    except Exception as e:
                        raise ValueError(
                            f"Could not read table {table_name}: {e}")
                    for idx, row in enumerate(rows):
                        el_id = int(row[0])
                        if el_id in els2load:
                            elements.append(
                                Element(
                                    sop=SOP.from_db_row(
                                        sop_tpl=self.init_SOP,
                                        row=np.asarray(row[1:]).tolist()
                                    ),
                                    id=el_id,
                                    gen=gen
                                )
                            )
                            els2load.pop(els2load.index(el_id))
                    if not els2load:
                        break
            # Nelder-Mead Generation: NM####
            elif cond_nm:
                elements = []
                gen_id = int(token[2:])
                # Find the size of the ensemble
                tot_elem: int = 1
                # Find all NM tables in the SOP DB
                NM_gens: list[int] = [
                    int(tbl_name.split('NM')[-1])
                    for tbl_name in self.sop_db.tables
                    if tbl_name.startswith('NM') and not tbl_name.startswith('NMSG')]
                if gen_id >= 0:
                    name = token
                else:
                    name = f"NM{len(NM_gens) - 1:04d}"
                if not NM_gens:
                    raise ValueError(
                        "No NM tables found in SOP DB for postprocessing.")
                elif name not in self.sop_db.tables:
                    raise ValueError(
                        f"Table {name} not found in SOP DB for postprocessing.")
                elements.append(
                    Element(
                        sop=SOP.from_db_row(
                            sop_tpl=self.init_SOP,
                            row=self.sop_db.get_table(name)[0][1:]),
                        id=0,
                        gen=gen_id
                    )
                )
            # Unknown token
            else:
                self.klog.warning(
                    f"Unknown pp_ensemble token '{token}', skipping.")
                continue

            # Run extrapolation for this ensemble
            if not elements:
                self.klog.warning(f"No elements found for {name}, skipping.")
                continue
            Extrapolate(
                elements=elements,
                settings=self.settings,
                rc_tpl=self.input_tpl,
                sop_db=self.sop_db,
                kin_db=self.pp_db,
                sim_db=self.sim_db,
                sf=self.sf,
                pert=self.pert,
                klog=self.klog,
                prefix=name
            ).run()

    def get_generation(self,
                       token: str) -> list[Element]:
        """Retrieve all elements from a generation table in the SOP DB."""
        elements: list[Element] = []
        try:
            rows = self.sop_db.get_table(token)
        except Exception as e:
            raise ValueError(
                f"Could not read table {token}: {e}")
        for idx, row in enumerate(rows):
            elements.append(
                Element(
                    sop=SOP.from_db_row(
                        sop_tpl=self.init_SOP,
                        row=np.asarray(row[1:]).tolist()
                    ),
                    id=idx,
                    gen=int(token[1:])


                )
            )
        return elements


def main() -> None:

    def _print_help() -> None:
        print(
            """
KiMecO PostProcess (kmopp)
Run postprocessing and extrapolation on a completed KiMecO run.

This command reads a JSON input file, loads existing run databases/GOAT
ensembles, and executes postprocessing ensembles configured with pp_* keys
(for example pp_ensembles, pp_temp, pp_pres).

Usage:
  kmopp INPUT_JSON

Arguments:
  INPUT_JSON    Path to the KiMecO JSON configuration file.

Options:
  -h, --help    Show this help message and exit.
""".strip()
        )

    if len(sys.argv) == 2 and sys.argv[1] in {'-h', '--help'}:
        _print_help()
        sys.exit(0)

    if len(sys.argv) != 2:
        _print_help()
        sys.exit(1)

    try:
        pp = PostProcess(
            input_file=sys.argv[1])
    except IndexError as e:
        print(e)
        print('To use KiMecO PostProcess, supply the input file as argument.')
        sys.exit(-1)

    pp.initialize_workdir()
    pp.copy_necessary_files()
    pp.initialize_databases()
    pp.set_scoring_function()
    pp.set_perturbator()
    pp.load_goats()
    pp.set_postprocessing()
    # Extrapolations are executed inside set_postprocessing()
