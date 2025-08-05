from kimeco.enums import Distrib, Ptype
from typing import Any
import os
import shutil
import numpy as np
from numpy.typing import NDArray
from kimeco.element import Element
from kimeco.parameters import SOP
from kimeco.core import CoreRun
from kimeco.database.kimeco_db import dbs
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
from logging import Logger


class Linear:
    def __init__(self,
                 elements: list[Element],
                 settings: dict[str, Any],
                 rc_tpl: list[str],
                 loc: str,
                 sf: Scoring,
                 pert: Perturbator,
                 klog: Logger
                 ) -> None:

        self.klog: Logger = klog
        self.settings: dict[str, Any] = settings
        self.name = 'SA'
        self.to_test = []
        self.selected = []
        self.lin_fact: float = self.settings['sensi_d']
        self.pert: Perturbator = pert
        self.elements: list[Element] = self.prepare_elements(
            elements=elements
            )
        n_param: int = len(elements[0].sop.parameters_names)
        # Create generation directory
        SA_dir: str = f'{loc}/{self.name}'
        self.sop_db = SOP_DB(sop=self.elements[0].sop,
                             name='SA_DB_SOP')
        self.kin_db = KIN_DB(sop=self.elements[0].sop,
                             name='SA_DB_KIN')
        self.sim_db = SIM_DB(sop=self.elements[0].sop,
                             name='SA_DB_SIM',
                             tbl_name=self.name)
        os.makedirs(SA_dir + '/logs', exist_ok=True)
        for subfolder in range((2*n_param+1)//50+1):
            os.makedirs(SA_dir + f'/{subfolder:02d}' + '/logs', exist_ok=True)
            # Copy files necessary for MESS calculation
            for file in self.elements[0].sop.files2copy:
                shutil.copyfile(f'{loc}/{file}',
                                f'{SA_dir}/{subfolder:02d}/{file}')
        os.chdir(SA_dir)
        self.core = CoreRun(
            elements=self.elements,
            settings=self.settings,
            rc_tpl=rc_tpl,
            loc=loc,
            sop_db=self.sop_db,
            kin_db=self.kin_db,
            sim_db=self.sim_db,
            sf=sf,
            pert=pert,
            name=self.name,
            klog=self.klog
        )
        # Clean the SIM database
        if not self.core.finished and self.sim_db.table_exists(self.name):
            self.sim_db.wipe_table(self.name)

    def average(self,
                sop_list: list[SOP]) -> SOP:

        # Use the first SOP as a template
        sop_template: SOP = sop_list[0]

        # Get the parameter names and initialize a dictionary to hold the sums
        parameter_names: dict[str, Any] = sop_template.parameters_names
        sums: dict[str, float] = {key: 0.0 for key in parameter_names.keys()}

        # Count the number of SOP objects for averaging
        count: int = len(sop_list)

        # Sum the parameters from each SOP object
        for sop in sop_list:
            for key in sums.keys():
                sums[key] += sop.parameters_names[key]

        # Calculate the average for each parameter
        averages: dict[str, float] = {
            key: value / count for key, value in sums.items()
            }

        # Create a new SOP object using the from_db_row method
        return SOP.from_db_row(sop_template, list(averages.values()))

    def calculate_dstep(self,
                        uc: float,
                        param: str,
                        side: int) -> float:
        """Calculate the size of the derivative
        step depending on the type of parameter.

        Args:
            val (float): value of the parameter
            param (str): full name of the parameter
            side (int): side of the derivative

        Returns:
            float: derivative step
        """
        # Recognise type of parameter
        for ptype in Ptype:
            if ptype.value in param:
                break
        scale: float = self.pert.get_scale(
                ptype=ptype.value,
                param=param
            )
        # Assymetric derivative for lognormal distribution
        if self.pert.distribs[ptype] == Distrib.LOGNORMAL and side == -1:
            dstep: float = scale/uc
        else:
            dstep = scale
        return dstep * self.lin_fact

    def prepare_elements(self,
                         elements: list[Element]) -> list[Element]:

        base_sop: SOP = self.average(
                sop_list=[e.sop for e in elements])
        # List to hold the new SOP objects
        new_elements: list[Element] = [
            Element(sop=base_sop,
                    id=0)
        ]

        # Get the parameters names and their current values
        pn: dict[str, Any] = base_sop.parameters_names

        el_id = 0
        # direction of the derivative
        for side in [1, -1]:
            # Iterate through the parameters
            for key in pn:
                # Check if the parameter should be modified
                if any(
                    substring in key for substring in
                    [f'{dbs}{Ptype.SCORE.value}']):
                    self.to_test.append(False)
                    continue
                # Create a new SOP object with the modified parameter
                self.to_test.append(True)
                el_id += 1
                # Get the uncertainty of the parameter
                uc: float = elements[0].sop.uncertainties[key]
                dstep: float = self.calculate_dstep(
                    uc=uc,
                    param=key,
                    side=side
                )
                new_sop = SOP.from_db_row(
                    sop_tpl=base_sop,
                    row=[v+(dstep*side) if k == key else v
                         for k, v in pn.items()])
                new_elements.append(
                    Element(
                        sop=new_sop,
                        id=el_id))
        return new_elements

    def run(self) -> None:
        self.core.run()
        zero: float = self.core.elements[0].score
        rslts: NDArray = np.absolute(
            [el.score - zero for el in self.core.elements[1:]]
            )
        half = int(len(rslts)/2)
        highest = [
            num
            if num > rslts[idx + half]
            else rslts[idx + half]
            for idx, num in enumerate(rslts[:half])]
        tot = np.sum(highest)
        params: list[str] = [
            k for i, k in enumerate(self.elements[0].sop.parameters_names)
            if self.to_test[i]]

        # Get the indices that would sort 'rslts' in decreasing order
        indices: list[int] = sorted(
            range(len(highest)),
            key=lambda i: highest[i],
            reverse=True)

        # Reorder 'rslts' and 'params' using the sorted indices
        rslts_sorted: list[float] = [highest[i] for i in indices]
        self.rs: list[float] = rslts_sorted
        params_sorted: list[str] = [params[i] for i in indices]
        self.ps: list[str] = params_sorted

        cumul = 0
        for i in range(len(params_sorted)):
            self.selected.append(self.ps[i])
            cumul += self.rs[i]/tot
            if cumul > self.settings['cumul_sensi']:
                break

        txt_file = 'Parameters names:   Cum. Percent    Percent      Value\n'
        cumul = 0
        for idx in range(len(rslts_sorted)):
            cumul += rslts_sorted[idx]/tot
            txt_file += f'{params_sorted[idx]:19s}'
            txt_file += f' {cumul:-12.2f}'
            txt_file += f' {rslts_sorted[idx]/tot:-10.2f}'
            txt_file += f' {rslts_sorted[idx]:9.2e}'
            txt_file += '\n'

        with open(f'{self.name}.out', 'w') as f:
            f.write(txt_file)

    def save_initial_element(self,
                             sop_db: SOP_DB,
                             kin_db: KIN_DB,
                             sim_db: SIM_DB) -> None:
        """Save the initial unperturbed element of the sensitivity analysis
        in G0000 table of each database.

        Args:
            sop_db (SOP_DB): Main run sop database
            kin_db (KIN_DB): Main run kin database
            sim_db (SIM_DB): Main run sim database
        """
        initial_element: Element = self.core.elements[0]
        initial_element.save_kin(db=kin_db, table='G0000')
        for sim_num in range(len(initial_element.sim.simulations)):
            initial_element.save_sim(db=sim_db,
                                     table='G0000',
                                     sim_num=sim_num)
        initial_element.prepare_upsert(db=sop_db, table='G0000')
        sop_db.batch_upsert()
        kin_db.batch_upsert()
        sim_db.batch_upsert()
