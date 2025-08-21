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
from kimeco.enums import Ptype
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
        vertice = Element(
            sop=SOP.from_db_row(
                sop_tpl=self.f_el.sop,
                row=row
            ),
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
