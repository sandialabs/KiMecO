from logging import Logger
from typing import Any
import numpy as np
from scipy.optimize import minimize
from numpy.typing import NDArray
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.enums import ElementStatus, Ptype
from kimeco.parameters import SOP
from kimeco.generation import Generation
from kimeco.scoring_f.scoring import Scoring
from kimeco.database.kimeco_db import dbs


class NelderMead:
    def __init__(self,
                 settings: dict[str, Any],
                 sf: Scoring,
                 pert: Perturbator,
                 sop_db: SOP_DB,
                 sim_db: SIM_DB,
                 kin_db: KIN_DB,
                 f_el: Element,
                 input_tpl: list[str],
                 location: str,
                 klog: Logger
                 ) -> None:
        self.name = 'Nelder-Mead'
        self.sf: Scoring = sf
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.loc: str = location
        self.input_tpl: list[str] = input_tpl
        self.f_el: Element = f_el
        self.settings: dict[str, Any] = settings
        self.pert: Perturbator = pert
        self.klog: Logger = klog

    def get_initial_simplex(self) -> NDArray:
        vertice_0 = np.array([
            self.f_el.sop.parameters_names[p]
            for p in self.settings['only_perturb']
        ])
        return vertice_0

    def run(self) -> NDArray:
        """Run the Nelder-Mead optimization."""
        result = minimize(
            fun=self.objective_function,
            x0=self.get_initial_simplex(),
            method='Nelder-Mead',
            bounds=self.get_bounds(),
            options={
                'fatol': 0.001,
                'disp': True}
        )
        if result.success:
            self.klog.info(f"Optimization successful: {result.message}")
            return result.x
        else:
            self.klog.error(f"Optimization failed: {result.message}")
            raise RuntimeError("Nelder-Mead optimization failed.")

    def objective_function(self,
                           params: NDArray) -> float:
        row = [
            v
            if p not in self.settings['only_perturb']
            else params[self.settings['only_perturb'].index(p)]
            for p, v in self.f_el.sop.parameters_names.items()]
        v_sop: SOP = SOP.from_db_row(
                sop_tpl=self.f_el.sop,
                row=row
            )
        if self.is_generation_finished(gen_id=Generation.total()):
            sop_in_db = True
            try:
                db_row: list[float] = self.sop_db.get_sop_row(
                        table=f'G{Generation.total():04d}',
                        id=0)[1:]
            except Exception:
                sop_in_db = False
                
            if sop_in_db:
                db_sop: SOP = SOP.from_db_row(
                    sop_tpl=self.f_el.sop,
                    row=db_row
                )
                same_p: list[bool] = [
                    True if ('score' in p and 'score' in q)
                    else
                    (p==q and
                    db_sop.parameters_names[p] == v_sop.parameters_names[q])
                    for p, q in
                    zip(db_sop.parameters_names, v_sop.parameters_names)
                ]
                if all(same_p):
                    vertice = Element(
                        sop=db_sop,
                        id=0,
                        gen=Generation.total(),
                        status=ElementStatus.DONE.value)
                else:
                    vertice = Element(
                        sop=v_sop,
                        id=0,
                        gen=Generation.total())
            else:
                vertice = Element(
                    sop=v_sop,
                    id=0,
                    gen=Generation.total())
        else:
            vertice = Element(
                sop=v_sop,
                id=0,
                gen=Generation.total())

        new_gen = Generation(
                elements=[vertice],
                settings=self.settings,
                rc_tpl=self.input_tpl,
                loc=self.loc,
                sop_db=self.sop_db,
                kin_db=self.kin_db,
                sim_db=self.sim_db,
                sf=self.sf,
                pert=self.pert,
                klog=self.klog,
                previous_el={0: self.f_el}
                )
        new_gen.run()
        self.print_stats(params=params)
        return new_gen.elements[0].score

    def is_generation_finished(self,
                               gen_id: int) -> bool:
        """Check if a generation is finished.

        Args:
            gen_id (int): Generation id

        Returns:
            bool: Wether it is finished
        """
        gen_name: str = f"G{gen_id:04d}"
        if self.sop_db.table_exists(gen_name) and\
           self.kin_db.table_exists(gen_name) and\
           self.sim_db.table_exists(gen_name):
            sop_ids = set(self.sop_db.get_column(
                table=gen_name,
                column_name='id'))
            kin_ids = set(self.kin_db.get_column(
                table=gen_name,
                column_name='kin_id'))
            tmp = np.array(self.sim_db.get_column(
                table=gen_name,
                column_name='sim_id'))//len(self.settings['exp_profiles'])
            sim_ids = set(tmp.tolist())
            if sop_ids == kin_ids == sim_ids:
                return True
            else:
                return False
        else:
            return False

    def get_bounds(self):
        bounds = []
        for param in self.settings['only_perturb']:
            for ptype in Ptype:
                if ptype.value in param.split(dbs)[1]:
                    break
            bounds.append(tuple(
                self.pert.get_boundaries(
                    ptype=ptype.value,
                    i_val=self.f_el.sop.parameters_names[param]
                ))
            )
        return bounds

    def print_stats(self,
                    params: NDArray) -> None:
        line_tpl = '{name:<15}{start:>10}{current:>10}'
        msg = '\n'
        msg += line_tpl.format(
            name='PARAMETER',
            start='INITIAL',
            current='CURRENT') + '\n'
        for idx, p in enumerate(self.settings['only_perturb']):
            start: float = self.f_el.sop.parameters_names[p]
            current: float = params[idx]
            if start >= 1000:
                str_start: str = f"{start:-5.2E}"
            else:
                str_start: str = f"{start:-6.2f}"
            if current >= 1000:
                str_current: str = f"{current:-5.2E}"
            else:
                str_current: str = f"{current:-6.2f}"
            msg += line_tpl.format(
                name=p,
                start=str_start,
                current=str_current) + '\n'
        self.klog.info(msg)
