from typing import Any
import os
import numpy as np
from numpy.typing import NDArray
from game.barrier import Barrier
from game.element import Element
from game.parameters import SOP
from game.core import CoreRun
from game.database.kin_db import KIN_DB
from game.database.sim_db import SIM_DB
from game.database.sop_db import SOP_DB
from game.scoring_f.scoring import Scoring
from game.Perturbators.perturbator import Perturbator


class Linear:
    def __init__(self,
                 elements: list[Element],
                 settings: dict[str, Any],
                 rc_tpl: list[str],
                 loc: str,
                 sf: Scoring,
                 pert: Perturbator,
                 ) -> None:

        self.settings: dict[str, Any] = settings
        self.name = 'SA'
        self.to_test = []
        self.selected = []
        self.elements: list[Element] = self.prepare_elements(
            elements=elements,
            sf=sf
            )
        # Create generation directory
        SA_dir: str = f'{loc}/{self.name}'
        sop_db = SOP_DB(sop=self.elements[0].sop,
                        name='SA_DB_SOP')
        kin_db = KIN_DB(sop=self.elements[0].sop,
                        name='SA_DB_KIN')
        sim_db = SIM_DB(sop=self.elements[0].sop,
                        name='SA_DB_SIM',
                        tbl_name=self.name)
        os.makedirs(SA_dir, exist_ok=True)
        os.chdir(SA_dir)
        self.core = CoreRun(
            elements=self.elements,
            settings=self.settings,
            rc_tpl=rc_tpl,
            loc=loc,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            sf=sf,
            pert=pert,
            name=self.name
        )

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

    def prepare_elements(self,
                         elements: list[Element],
                         sf: Scoring):

        base_sop: SOP = self.average(
                sop_list=[e.sop for e in elements])
        # List to hold the new SOP objects
        new_elements = [
            Element(sop=base_sop,
                    id=0,
                    sf=sf)
        ]

        # Get the parameters names and their current values
        pn: dict[str, Any] = base_sop.parameters_names

        # Iterate through the parameters
        el_id = 0
        for key in pn:
            # Check if the parameter should be modified
            if any(
               substring in key for substring in
               ['__score']):
                self.to_test.append(False)
                continue
            # Create a new SOP object with the modified parameter
            self.to_test.append(True)
            el_id += 1
            mol: str = key.split('__')[0]
            param: str = key.split('__')[1]
            lin_fact = self.settings['sensi_d']
            if param == 'e':
                if isinstance(base_sop.items[mol], Barrier):
                    modif = self.settings['std_b'] * lin_fact
                else:
                    modif = self.settings['std_e'] * lin_fact
            elif param.startswith('hr'):
                modif = self.settings['std_hr'] * lin_fact
            elif param.startswith('epsi'):
                modif = self.settings['std_epsi'] * lin_fact
            elif param.startswith('sigma'):
                modif = self.settings['std_sigma'] * lin_fact
            else:
                modif = self.settings[f'std_{param}'] * lin_fact
            new_sop = SOP.from_db_row(
                sop_tpl=base_sop,
                row=[v+modif if k == key else v for k, v in pn.items()])
            new_elements.append(
                Element(
                    sop=new_sop,
                    id=el_id,
                    sf=sf))
        return new_elements

    def run(self) -> None:
        self.core.run()
        zero: float = self.core.elements[0].score
        rslts: NDArray = np.absolute(
            [el.score - zero for el in self.core.elements[1:]]
            )
        tot = np.sum(rslts)
        params: list[str] = [
            k for i, k in enumerate(self.elements[0].sop.parameters_names)
            if self.to_test[i]]

        # Get the indices that would sort 'rslts' in decreasing order
        indices = sorted(
            range(len(rslts)),
            key=lambda i: rslts[i],
            reverse=True)

        # Reorder 'rslts' and 'params' using the sorted indices
        rslts_sorted: list[float] = [rslts[i] for i in indices]
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
        for idx in range(len(rslts)):
            cumul += rslts_sorted[idx]/tot
            txt_file += f'{params_sorted[idx]:19s}'
            txt_file += f' {cumul:-12.2f}'
            txt_file += f' {rslts_sorted[idx]/tot:-10.2f}'
            txt_file += f' {rslts_sorted[idx]:9.2e}'
            txt_file += '\n'

        with open(f'{self.name}.out', 'w') as f:
            f.write(txt_file)

