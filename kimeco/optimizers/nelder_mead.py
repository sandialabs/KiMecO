from logging import Logger
from typing import Any
import numpy as np
from scipy.optimize import minimize
from numpy.typing import NDArray
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.element import Element
from kimeco.parameters import SOP
from kimeco.generation import Generation


class NelderMead:
    def __init__(self,
                 f_el: Element,
                 settings: dict[str, Any],
                 pert: Perturbator,
                 klog: Logger) -> None:
        self.f_el: Element = f_el
        self.settings: dict[str, Any] = settings
        self.pert: Perturbator = pert
        self.klog: Logger = klog

    def get_initial_simplex(self) -> NDArray:
        dim: int = len(self.settings['only_perturb'])
        vertice_0 = np.array([
            self.f_el.sop.parameters_names[p]
            for p in self.settings['only_perturb']
        ])
        simplex = np.full(
            shape=(dim + 1, len(vertice_0)),
            fill_value=vertice_0)
        for i in range(dim):
            simplex[i+1] = np.array([
                self.pert.perturb(self.f_el.sop).parameters_names[p]
                for p in self.settings['only_perturb']
            ])
        return simplex

    def optimize(self,
                 initial_params: NDArray) -> NDArray:
        """Run the Nelder-Mead optimization."""
        result = minimize(
            self.objective_function,
            self.get_initial_simplex(),
            method='Nelder-Mead',
            options={
                'xatol': self.settings.get('tolerance', 1e-4),
                'disp': True}
        )
        if result.success:
            self.klog.info(f"Optimization successful: {result.message}")
            return result.x
        else:
            self.klog.error(f"Optimization failed: {result.message}")
            raise RuntimeError("Nelder-Mead optimization failed.")

    def objective_function(self,
                           params: NDArray):
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
                previous_el={0:self.f_el}
                )
