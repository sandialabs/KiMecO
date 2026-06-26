import sys
import os
import json
import numpy as np
from kimeco._kimeco import KiMecO
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
import time
from kimeco.model import Model
from kimeco.enums import ModelStatus
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
        self.prepare_postprocess_settings()

    def prepare_postprocess_settings(self) -> None:
        """Route the postprocessing experiments through the standard
        simulation pipeline.

        pp_experiments are validated and built as TimeProfile objects during
        input parsing. Here they replace the regular experiment list so the
        queueing system, SIM and profile recovery all operate on the pp
        conditions (one array task per unique cantera template).
        """
        pp_experiments = self.settings.get('pp_experiments', [])
        if not pp_experiments:
            raise ValueError(
                'pp_experiments should define at least one experiment '
                'for postprocessing.'
            )

        self.settings['experiments'] = pp_experiments
        self.settings['n_exp'] = len(pp_experiments)

    def copy_necessary_files(self) -> None:
        """Copy run files and emit a postprocess-flagged input file.

        The per-experiment simulation subprocesses rebuild a plain ``KiMecO``
        from the input file. Pointing them at a flagged copy makes them run in
        postprocess mode (pp_experiments conditions and the pp_* rate grid)
        without requiring any change to the user's cantera template.
        """
        super().copy_necessary_files()
        self._write_postprocess_input()

    def _write_postprocess_input(self) -> None:
        """Write a copy of the input JSON with ``postprocess`` enabled and
        redirect the simulation scripts to it.
        """
        input_file: str = self.settings['input_file']
        if os.path.isabs(input_file):
            original_input: str = input_file
        else:
            original_input = self.settings['init_loc'] + input_file
        with open(original_input, 'r') as f:
            raw_input = json.load(f)
        raw_input['postprocess'] = True
        flagged_input: str = os.path.join(
            self.settings['workdir'], '_kmopp_input.json')
        with open(flagged_input, 'w') as f:
            json.dump(raw_input, f)
        self.settings['input_file'] = flagged_input

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
        start_time = time.time()
        self.pp_sim_db = SIM_DB(
            name='PP_DB_SIM',
            threads=self.settings['threads'],
            path=self.settings['workdir'])
        sim_db_time: float = time.time() - start_time
        msg = 'Extrapolation_SIM_DB initialized:'
        self.klog.info(f"{msg:<65}{sim_db_time:>15.1f}")

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
            sf=self.sf,
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
                models: list[Model] = self.get_generation(token)
            # GOATs generation: GT####
            elif cond_gt:
                gen_id = int(token[2:])
                models: list[Model] = []
                try:
                    goats_models = self.goats.get_goat_for_gen(gen_id)
                except Exception as e:
                    self.klog.warning(f"Could not load GOATs for {token}: {e}")
                    continue
                for idx, mdl in enumerate(goats_models):
                    models.append(Model(
                        sop=mdl.sop,
                        id=idx,
                        gen=mdl.gen,
                        status=ModelStatus.SOP.value
                    ))
                if gen_id >= 0:
                    name = token
                else:
                    name = f"GT{len(self.goats) - 1:04d}"

            # NMSG Nelder-Mead Swarm Generation: NMSG####
            elif cond_nms:
                models = []
                # Find the size of the ensemble
                nms_cond_g = self.settings['NMS_start'].startswith('G') and \
                    self.settings['NMS_start'][1:].isdigit()
                nms_cond_gt = self.settings['NMS_start'].startswith('GT') and \
                    self.settings['NMS_start'][2:].lstrip('-').isdigit()
                if nms_cond_g:
                    tot_mdl: int = self.settings['n_mdl']
                elif nms_cond_gt:
                    tot_mdl = self.settings['goat_length']
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
                # Load models from NMSG tables, starting from the
                # highest generation until all models are found
                els2load: list[float] = [i for i in range(tot_mdl)]
                for gen in range(max_NMS_gen, -1, -1):
                    table_name: str = f'NMSG{gen:04d}'
                    try:
                        rows = self.sop_db.get_table(table_name)
                    except Exception as e:
                        raise ValueError(
                            f"Could not read table {table_name}: {e}")
                    for idx, row in enumerate(rows):
                        mdl_id = int(row[0])
                        if mdl_id in els2load:
                            models.append(
                                Model(
                                    sop=SOP.from_db_row(
                                        sop_tpl=self.init_SOP,
                                        row=np.asarray(row[1:]).tolist()
                                    ),
                                    id=mdl_id,
                                    gen=gen
                                )
                            )
                            els2load.pop(els2load.index(mdl_id))
                    if not els2load:
                        break
            # Nelder-Mead Generation: NM####
            elif cond_nm:
                models = []
                gen_id = int(token[2:])
                # Find the size of the ensemble
                tot_mdl: int = 1
                # Find all NM tables in the SOP DB
                NM_gens: list[int] = [
                    int(tbl_name.split('NM')[-1])
                    for tbl_name in self.sop_db.tables
                    if (tbl_name.startswith('NM') and
                        not tbl_name.startswith('NMSG'))]
                if gen_id >= 0:
                    name = token
                else:
                    name = f"NM{len(NM_gens) - 1:04d}"
                if not NM_gens:
                    raise ValueError(
                        "No NM tables found in SOP DB for postprocessing.")
                elif name not in self.sop_db.tables:
                    raise ValueError(
                        f"Table {name} not found in SOP DB for "
                        "postprocessing."
                    )
                models.append(
                    Model(
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
            if not models:
                self.klog.warning(f"No models found for {name}, skipping.")
                continue
            Extrapolate(
                models=models,
                settings=self.settings,
                rc_tpls=self.input_tpls,
                sop_db=self.sop_db,
                kin_db=self.pp_db,
                sim_db=self.pp_sim_db,
                sf=self.sf,
                pert=self.pert,
                klog=self.klog,
                prefix=name
            ).run()

    def get_generation(self,
                       token: str) -> list[Model]:
        """Retrieve all models from a generation table in the SOP DB."""
        models: list[Model] = []
        try:
            rows = self.sop_db.get_table(token)
        except Exception as e:
            raise ValueError(
                f"Could not read table {token}: {e}")
        for idx, row in enumerate(rows):
            models.append(
                Model(
                    sop=SOP.from_db_row(
                        sop_tpl=self.init_SOP,
                        row=np.asarray(row[1:]).tolist()
                    ),
                    id=idx,
                    gen=int(token[1:])


                )
            )
        return models


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
