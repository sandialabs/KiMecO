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
        rows = self.sop_db.get_table('G0001')
        f_els = []
        for idx, row in enumerate(rows):
            f_els.append(
                Element(
                    sop=SOP.from_db_row(
                        sop_tpl=self.init_SOP,
                        row=np.asarray(row[1:]).tolist()
                    ),
                    id=idx,
                    gen=1))
        self.extrapolate_start = Extrapolate(
            elements=f_els,
            settings=self.settings,
            rc_tpl=self.input_tpl,
            sop_db=self.sop_db,
            kin_db=self.pp_db,
            sim_db=self.sim_db,
            sf=self.sf,
            pert=self.pert,
            klog=self.klog
        )
        elements = []
        # prev_elements = {}
        for idx, el in enumerate(self.goats.get_goat_for_gen(-1)):
            elements.append(Element(
                sop=el.sop,
                id=idx,
                gen=0,
                status=ElementStatus.SOP.value
            ))
            # prev_elements[idx] = el
        self.extrapolate = Extrapolate(
            elements=elements,
            settings=self.settings,
            rc_tpl=self.input_tpl,
            sop_db=self.sop_db,
            kin_db=self.pp_db,
            sim_db=self.sim_db,
            sf=self.sf,
            pert=self.pert,
            klog=self.klog
        )


def main() -> None:

    # Call the setup function to configure logging
    if len(sys.argv) != 2:
        print("""
    KIMECO needs various parameters to be set in a JSON input file.
    This JSON input file should be supplied as the first and only
    argument.

    Usage:  kmo path/to/JSON/input/file.json
    """)
        sys.exit()
    try:
        pp = PostProcess(
            input_file=sys.argv[1])
    except IndexError as e:
        print(e)
        print('To use KIMECO, supply the input file as argument.')
        sys.exit(-1)

    pp.initialize_workdir()
    pp.copy_necessary_files()
    pp.initialize_databases()
    pp.set_scoring_function()
    pp.set_perturbator()
    pp.load_goats()
    pp.set_postprocessing()
    pp.extrapolate_start.run()
    pp.extrapolate.run()
    