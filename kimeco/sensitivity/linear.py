from kimeco.enums import Distrib, Ptype, RestartType
from typing import Any
import numpy as np
from numpy.typing import NDArray
from kimeco.element import Element, ElementStatus
from kimeco.parameters import SOP
from kimeco.core import CoreRun
from kimeco.database.kimeco_db import dbs
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.logger_config import KMOLogger


class Linear(CoreRun):
    __id = 0

    @classmethod
    def total(cls) -> int:
        """Return the total number of
        Linear sensitivity analysis instances."""
        return cls.__id

    @classmethod
    def reset(cls) -> None:
        """Return the total number of
        Linear sensitivity analysis instances."""
        cls.__id = 0

    def __init__(self,
                 elements: list[Element],
                 settings: dict[str, Any],
                 rc_tpls: list[list[str]],
                 sf: Scoring,
                 klog: KMOLogger,
                 pert: Perturbator | None = None,
                 restart: bool = True
                 ) -> None:
        self.id: int = Linear.__id
        Linear.__id += 1
        self.klog: KMOLogger = klog
        self.settings: dict[str, Any] = settings
        self.prefix = 'SA'
        self.name: str = f'{self.prefix}{self.id:04d}'
        self.to_test: list[bool] = []
        self.selected: list[str] = []
        self.sop_tpl: SOP = self.average([el.sop for el in elements])
        self.lin_fact: float = self.settings['sensi_d']
        self.pert: Perturbator | None = pert
        self.sop_db = SOP_DB(sop=self.sop_tpl,
                             name=f'{self.prefix}_DB_SOP',
                             path=self.settings['workdir'],
                             klog=self.klog)
        self.kin_db = KIN_DB(sop=self.sop_tpl,
                             name=f'{self.prefix}_DB_KIN',
                             path=self.settings['workdir'])
        self.sim_db = SIM_DB(sop=self.sop_tpl,
                             name=f'{self.prefix}_DB_SIM',
                             path=self.settings['workdir'])
        if self.SA_is_in_db() and restart:
            self.klog.debug('SA is in DB. Reading results.')
            self.elements = self.get_elements_from_db()
            self.elements_from_db = True
        else:
            if self.settings['restart'] == RestartType.RESCORE:
                self.klog.warning(
                    'Rescoring only but SA not in DB.')
            self.elements: list[Element] = self.prepare_elements(
                elements=elements
                )
            self.elements_from_db = False
        super().__init__(
            elements=self.elements,
            settings=self.settings,
            rc_tpls=rc_tpls,
            sop_db=self.sop_db,
            kin_db=self.kin_db,
            sim_db=self.sim_db,
            sf=sf,
            pert=pert,
            prefix=self.prefix,
            klog=self.klog)
        # Clean the SIM database
        if self.sim_db.table_exists(self.name) and not self.finished:
            if not self.settings['restart'] == RestartType.RESCORE:
                self.sim_db.wipe_table(self.name)

        if self.id % 10 == 0:
            self.sop_db.defragmentate()
            self.kin_db.defragmentate()
            self.sim_db.defragmentate()
        self.klog.info(
            f'{self.name} initialized with {len(self.elements)} elements.'
            )

    def same_f_el_in_db(self) -> bool:
        try:
            db_row: list[float] = self.sop_db.get_sop_row(
                table=self.name,
                id=0)[1:]
        except Exception as e:
            self.klog.debug(str(e))
            return False

        db_sop: SOP = SOP.from_db_row(
            sop_tpl=self.sop_tpl,
            row=db_row
        )
        same_p: list[bool] = [
            True if ('score' in p and 'score' in q)
            else
            (p == q and
                round(db_sop.parameters_names[p], 6) ==
                round(self.sop_tpl.parameters_names[q], 6))
            for p, q in
            zip(db_sop.parameters_names,
                self.sop_tpl.parameters_names)
        ]
        return all(same_p)

    def SA_is_in_db(self) -> bool:
        """Check if a generation is finished.

        Args:
            gen_id (int): Generation id

        Returns:
            bool: Wether it is finished
        """
        if self.sop_db.table_exists(self.name) and\
           self.kin_db.table_exists(self.name) and\
           self.sim_db.table_exists(self.name):
            sop_ids = set(self.sop_db.get_column(
                table=self.name,
                column_name='id'))
            kin_ids = set(self.kin_db.get_column(
                table=self.name,
                column_name='kin_id'))
            tmp = np.array(self.sim_db.get_column(
                table=self.name,
                column_name='sim_id'))//len(self.settings['exp_profiles'])
            sim_ids = set(tmp.tolist())
            if sop_ids == kin_ids == sim_ids:
                return self.same_f_el_in_db()
            else:
                return False
        else:
            return False

    def get_elements_from_db(self) -> list[Element]:
        """Restaure the elements from the SA from the DB

        Returns:
            list[Element]: Elements with a score and DONE status
        """
        next_elements = []
        sop_ids: list[Any] = self.sop_db.get_column(
            table=self.name,
            column_name='id')
        # Only valid for 2-step derivative plus central element
        for side in [1, -1]:
            # Iterate through the parameters
            for key in self.sop_tpl.parameters_names:
                # Check if the parameter should be modified
                if any(
                    substring in key for substring in
                    [f'{dbs}{Ptype.SCORE.value}']):
                    self.to_test.append(False)
                    continue
                # Create a new SOP object with the modified parameter
                self.to_test.append(True)
        if len(sop_ids) == sum(self.to_test)+1:
            self.klog.debug(
                'SA restarted from DB')
            if self.settings['restart'] == RestartType.RESCORE:
                self.klog.debug(
                    'Rescoring only, no new calculations will be done.')
            rows = np.array(
                self.sop_db.get_table(table=self.name)
                                    )
            for e_id, row in zip(sop_ids, rows):
                if self.settings['restart'] == RestartType.RESCORE:
                    next_elements.append(
                        Element(
                            sop=SOP.from_db_row(
                                sop_tpl=self.sop_tpl,
                                row=row[1:].tolist()
                            ),
                            id=e_id,
                            gen=self.id,
                            status=ElementStatus.RESCORE.value))
                else:
                    next_elements.append(
                        Element(
                            sop=SOP.from_db_row(
                                sop_tpl=self.sop_tpl,
                                row=row[1:].tolist()
                            ),
                            id=e_id,
                            gen=self.id,
                            status=ElementStatus.DONE.value))
        else:
            raise ValueError(
                f'SA {self.name} in DB is incomplete. '
                f'Found {len(sop_ids)} SOP but expected '
                f'{sum(self.to_test)+1}.')
        return next_elements

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
            uc (float): value of the uncertainty for this parameter
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

        # List to hold the new SOP objects
        new_elements: list[Element] = [
            Element(sop=self.sop_tpl,
                    id=0,
                    gen=self.id)
        ]

        # Get the parameters names and their current values
        pn: dict[str, Any] = self.sop_tpl.parameters_names

        el_id = 0
        # direction of the derivative
        for side in (1, -1):
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
                uc: float = self.sop_tpl.uncertainties[key]
                dstep: float = self.calculate_dstep(
                    uc=uc,
                    param=key,
                    side=side
                )
                new_sop = SOP.from_db_row(
                    sop_tpl=self.sop_tpl,
                    row=[v+(dstep*side) if k == key else v
                         for k, v in pn.items()])
                new_elements.append(
                    Element(
                        sop=new_sop,
                        id=el_id,
                        gen=self.id))
        return new_elements

    def run(self) -> None:
        super().run()
        zero: float = self.elements[0].score
        rslts: NDArray = np.absolute(
            [el.score - zero for el in self.elements[1:]]
            )
        half = int(len(rslts)/2)
        highest = [
            num
            if num > rslts[idx + half]
            else rslts[idx + half]
            for idx, num in enumerate(rslts[:half])]
        tot = np.sum(highest)
        params: list[str] = [
            k for i, k in enumerate(self.sop_tpl.parameters_names)
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
        tbl_name: str = 'G0000'
        # SOP
        if tbl_name not in sop_db.tables:
            sop_db.create_new_table(
                name=tbl_name
                )
        # KIN
        if tbl_name not in kin_db.tables:
            kin_db.create_new_table(
                name=tbl_name
                )
        # SIM
        if tbl_name not in sim_db.tables:
            sim_db.create_new_table(
                name=tbl_name
                )
        initial_element: Element = self.elements[0]
        initial_element.save_kin(db=kin_db, table=tbl_name)
        for sim_num in range(self.settings['n_exp']):
            initial_element.save_sim(db=sim_db,
                                     table=tbl_name,
                                     sim_num=sim_num)
        initial_element.prepare_upsert(db=sop_db, table=tbl_name)
        sop_db.batch_upsert()
        kin_db.batch_upsert()
        sim_db.batch_upsert()
