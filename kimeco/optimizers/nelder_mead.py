from logging import Logger
from re import I
from typing import Any
import numpy as np
from scipy.optimize import minimize
from numpy.typing import NDArray
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.goat import GOATs
from kimeco.sensitivity.linear import Linear
from kimeco.element import Element
from kimeco.enums import ElementStatus, Ptype, Pclass, Distrib
from kimeco.parameters import SOP
from kimeco.generation import Generation
from kimeco.scoring_f.scoring import Scoring


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
                 klog: Logger
                 ) -> None:
        self.name = 'Nelder-Mead'
        self.sf: Scoring = sf
        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.input_tpl: list[str] = input_tpl
        self.f_el: Element = f_el
        self.settings: dict[str, Any] = settings
        self.pert: Perturbator = pert
        self.klog: Logger = klog
        self.new_parameters: list[str] = self.settings['to_perturb']
        self.current_dimensions: list[str] = self.settings['to_perturb']
        self.wdir: str = self.settings['workdir']
        # Updated in objective function
        self.last_vertice: SOP = self.f_el.sop
        self.iterations = GOATs(sop_db=sop_db,
                                sim_db=sim_db,
                                kin_db=kin_db,
                                wdir=self.wdir)
        self.score_line_tpl = '{iter:>10}{score:>15}\n'
        with open(self.wdir + '/NM_scores.txt', 'w', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter='ITERATION',
                score='SCORE'))

    @property
    def not_enough_dimensions(self) -> bool:
        return set(self.new_parameters) == \
            set(self.current_dimensions)

    def get_initial_vertice(self) -> NDArray:
        vertice_0 = np.array([
            self.get_normalized(
                parameter=p,
                value=self.last_vertice.parameters_names[p])
            for p in self.current_dimensions
        ])
        return vertice_0

    def get_initial_simplex(self) -> NDArray:
        """Create the initial simplex depending on the uncertainties

        Returns:
            NDArray: Array of shape (n+1, n) with n the number of
            dimensions. The first row is the initial vertice, and the
            other rows are the initial vertice plus a step in each
            dimension.
        """
        simplex = np.zeros(
            (len(self.current_dimensions)+1, len(self.current_dimensions)))
        for i in range(len(self.current_dimensions)+1):
            if i == 0:
                simplex[i] = np.array([
                    self.get_normalized(
                        parameter=p,
                        value=self.last_vertice.parameters_names[p])
                    for p in self.current_dimensions
                ])
            else:
                dstep: float = self.calculate_dstep(
                    uc=self.f_el.sop.uncertainties[self.current_dimensions[i-1]],
                    param=self.current_dimensions[i-1],
                    side=1)
                simplex[i] = np.array([
                    self.get_normalized(
                        parameter=p,
                        value=self.last_vertice.parameters_names[p])
                    if p != self.current_dimensions[i-1]
                    else self.get_normalized(
                        parameter=p,
                        value=self.last_vertice.parameters_names[p]
                        + dstep)
                    for p in self.current_dimensions
                ])
        return simplex

    def calculate_dstep(self,
                        uc: float,
                        param: str,
                        side: int) -> float:
        """Calculate the size of the derivative
        step depending on the type of parameter.

        Args:
            uc (float): uncertainty value for this parameter
            param (str): full name of the parameter
            side (int): side of the derivative

        Returns:
            float: derivative step
        """
        # Recognise type of parameter
        ptype: Ptype = Ptype.WE
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
        return dstep * self.settings['nm_deriv_step_factor']

    def get_normalized(self,
                       parameter: str,
                       value: float) -> float:
        """Normalize the value to that it is centered
        on 0 and normalized between bounds (-1, 1) for the
        given parameter

        Args:
            parameter (str): parameter name, used to find the 0
            value (float): value to normalize

        Raises:
            NotImplementedError: unknown parameter class

        Returns:
            float: the normalized value
        """
        bounds: tuple[float, float] = self.get_bound(parameter)
        ptype = Ptype.WE
        for pt in Ptype:
            if pt.value in parameter:
                ptype: Ptype = pt
                break
        pclass = Pclass.ADDITIVE
        for pc in Pclass:
            if ptype.value in pc.value:
                pclass: Pclass = pc
                break
        if pclass == Pclass.ADDITIVE:
            norm_param = (
                value
                - self.f_el.sop.parameters_names[parameter]) \
                / abs(bounds[1] - self.f_el.sop.parameters_names[parameter])
        elif pclass == Pclass.PERCENT:
            norm_param = (
                value
                - self.f_el.sop.parameters_names[parameter]) \
                / abs(bounds[1] - self.f_el.sop.parameters_names[parameter])
        elif pclass == Pclass.MULTIPLICATIVE:
            norm_param = (
                value
                - self.f_el.sop.parameters_names[parameter])
            if norm_param < 0:
                norm_param /= abs(
                    self.f_el.sop.parameters_names[parameter] - bounds[0])
            elif norm_param > 0:
                norm_param /= abs(
                    bounds[1] - self.f_el.sop.parameters_names[parameter])
            else:
                pass
        else:
            raise NotImplementedError(
                f"Parameter class {pclass} not implemented.")
        return norm_param

    def get_absolute(self,
                     param: str,
                     value: float) -> float:
        """Get absolute value from normalized value centered
        on 0 and normalized between bounds (-1, 1) for the
        given parameter

        Args:
            parameter (str): parameter name, used to find the 0
            value (float): normalized value to back transform

        Raises:
            NotImplementedError: unknown parameter class

        Returns:
            float: the absolute value
        """
        bounds: tuple[float, float] = self.get_bound(param)
        ptype = Ptype.WE
        for pt in Ptype:
            if pt.value in param:
                ptype: Ptype = pt
                break
        pclass = Pclass.ADDITIVE
        for pc in Pclass:
            if ptype.value in pc.value:
                pclass: Pclass = pc
                break
        if pclass == Pclass.ADDITIVE:
            abs_param = value * \
                abs(bounds[1] - self.f_el.sop.parameters_names[param])\
                + self.f_el.sop.parameters_names[param]
        elif pclass == Pclass.PERCENT:
            abs_param = value * \
                abs(bounds[1] - self.f_el.sop.parameters_names[param])\
                + self.f_el.sop.parameters_names[param]
        elif pclass == Pclass.MULTIPLICATIVE:
            if value < 0:
                abs_param = value * abs(
                    self.f_el.sop.parameters_names[param] - bounds[0])\
                    + self.f_el.sop.parameters_names[param]
            elif value > 0:
                abs_param = value * abs(
                    bounds[1] - self.f_el.sop.parameters_names[param])\
                    + self.f_el.sop.parameters_names[param]
            else:
                abs_param = self.f_el.sop.parameters_names[param]
        else:
            raise NotImplementedError(
                f"Parameter class {pclass} not implemented.")
        return abs_param

    def get_options(self,
                    initial: bool = True) -> dict[str, Any]:
        options: dict[str, Any] = {'disp': True}
        if initial:
            options['initial_simplex'] = self.get_initial_simplex()
            if self.settings['nm_fatol'] > 0.0:
                self.klog.debug(
                    f"Setting Nelder-Mead fatol={self.settings['nm_fatol']}")
                options['fatol'] = self.settings['nm_fatol']
                self.klog.debug("Using adaptive Nelder-Mead")
            if self.settings['nm_maxiter'] > 0:
                self.klog.debug(
                    f"Setting Nelder-Mead maxiter={self.settings['nm_maxiter']}")
                options['maxiter'] = self.settings['nm_maxiter']
                self.klog.debug("Using adaptive Nelder-Mead")
            if self.settings['nm_maxfev'] > 0:
                self.klog.debug(
                    f"Setting Nelder-Mead maxfev={self.settings['nm_maxfev']}")
                options['maxfev'] = self.settings['nm_maxfev']
            if self.settings['nm_adaptive']:
                self.klog.debug("Using adaptive Nelder-Mead")
                options['adaptive'] = True
                # better performance in high D.
        else:
            options['initial_simplex'] = self.restart_simplex()
            if self.settings['nm_final_fatol'] > 0.0:
                self.klog.debug(
                    f"Setting final Nelder-Mead fatol={self.settings['nm_final_fatol']}")
                options['fatol'] = self.settings['nm_final_fatol']
                self.klog.debug("Using adaptive Nelder-Mead")
            if self.settings['nm_final_maxiter'] > 0:
                self.klog.debug(
                    f"Setting final Nelder-Mead maxiter={self.settings['nm_final_maxiter']}")
                options['maxiter'] = self.settings['nm_final_maxiter']
                self.klog.debug("Using adaptive Nelder-Mead")
            if self.settings['nm_maxfev'] > 0:
                self.klog.debug(
                    f"Setting final Nelder-Mead maxfev={self.settings['nm_final_maxfev']}")
                options['maxfev'] = self.settings['nm_final_maxfev']
            if self.settings['nm_adaptive']:
                self.klog.debug("Using adaptive for final Nelder-Mead")
                options['adaptive'] = True
                # better performance in high D.
        return options

    def restart_simplex(self) -> NDArray:
        """Create a simplex from the best vertices encountered
        in the previous iterations

        Returns:
            NDArray: 2D array of shape (n+1, n) with n the number of
            dimensions. Each row corresponds to one of the best n+1
            vertices.
        """
        simplex = np.zeros(
            (len(self.current_dimensions)+1, len(self.current_dimensions)))
        for i in range(len(self.current_dimensions)+1):
            for j, p in enumerate(self.current_dimensions):
                simplex[i][j] = self.get_normalized(
                    parameter=p,
                    value=self.latest_simplex[i].sop.parameters_names[p])
        return simplex

    def update_iterations(self,
                          last_vertice: Element) -> None:
        """Keep track of the goat list in the goat file,
        and and the associated score

        Args:
            new_els (list[Element]): last vertive
        """
        self.latest_simplex: list[Element] = self.iterations.update_with_generation(
            elements=[last_vertice],
            goat_length=len(self.current_dimensions) + 1
        )
        with open(self.wdir + '/NM_scores.txt', 'a', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter=last_vertice.gen,
                score=f"{last_vertice.score:.3f}"))

    def run(self) -> NDArray:
        """Run the Nelder-Mead optimization."""
        initial = True
        while self.not_enough_dimensions or result['fun'] > 9:
            self.current_dimensions = self.new_parameters
            msg = "Current dimensions:\n"
            msg += f'{self.current_dimensions}' + '\n'
            self.klog.info(msg)
            self.new_parameters = []
            result = minimize(
                fun=self.objective_function,
                x0=self.get_initial_vertice(),
                method='Nelder-Mead',
                bounds=[(-1, 1) for _ in self.current_dimensions],
                options=self.get_options(initial=initial)
            )
            initial = False
            if result.success or result.nfev >= 100:
                self.klog.info(result.x)
                msg = "Running SA to check if minimum is full-dimensional"
                self.klog.info(msg)
                sensitivity = Linear(
                    elements=[Element(
                        sop=self.last_vertice,
                        id=0)],
                    settings=self.settings,
                    rc_tpl=self.input_tpl,
                    sf=self.sf,
                    pert=self.pert,
                    klog=self.klog)
                sensitivity.run()
                self.new_parameters = sensitivity.selected
                self.klog.info(f"New dimensions: {self.new_parameters}")
            else:
                self.klog.error(f"Optimization failed: {result.message}")
                raise RuntimeError("Nelder-Mead optimization failed.")
        else:
            self.klog.info("The dimensionality has not changed.")
        msg: str = "\nIncreasing accuracy for last minimization.\n"

        self.klog.info(msg)
        result = minimize(
            fun=self.objective_function,
            x0=self.get_initial_vertice(),
            method='Nelder-Mead',
            bounds=[(-1,1) for _ in self.current_dimensions],
            options=self.get_options(initial=False)
        )
        if result.success:
            self.klog.info(result.x)
        else:
            self.klog.error(f"Optimization failed: {result.message}")
            raise NotImplementedError("Contact the dev. for a solution.")

    def objective_function(self,
                           params: NDArray) -> float:
        row = [
            v
            if p not in self.current_dimensions
            else self.get_absolute(
                param=p,
                value=params[self.current_dimensions.index(p)])
            for p, v in self.f_el.sop.parameters_names.items()]
        # SOP from vertice
        self.last_vertice = SOP.from_db_row(
                sop_tpl=self.f_el.sop,
                row=row
            )
        if self.is_generation_finished(gen_id=Generation.total()):
            sop_in_db = True
            try:
                db_row: list[float] = self.sop_db.get_sop_row(
                        table=f'G{Generation.total():04d}',
                        id=0)[1:]
            except Exception as e:
                sop_in_db = False
                self.klog.debug(e)

            if sop_in_db:
                db_sop: SOP = SOP.from_db_row(
                    sop_tpl=self.f_el.sop,
                    row=db_row
                )
                same_p: list[bool] = [
                    True if ('score' in p and 'score' in q)
                    else
                    (p == q and
                     db_sop.parameters_names[p] ==
                     self.last_vertice.parameters_names[q])
                    for p, q in
                    zip(db_sop.parameters_names,
                        self.last_vertice.parameters_names)
                ]
                if all(same_p):
                    vertice = Element(
                        sop=db_sop,
                        id=0,
                        gen=Generation.total(),
                        status=ElementStatus.DONE.value)
                else:
                    vertice = Element(
                        sop=self.last_vertice,
                        id=0,
                        gen=Generation.total())
            else:
                vertice = Element(
                    sop=self.last_vertice,
                    id=0,
                    gen=Generation.total())
        else:
            vertice = Element(
                sop=self.last_vertice,
                id=0,
                gen=Generation.total())

        new_gen = Generation(
                elements=[vertice],
                settings=self.settings,
                rc_tpl=self.input_tpl,
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
        self.update_iterations(last_vertice=new_gen.elements[0])
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
        for param in self.current_dimensions:
            bounds.append(self.get_bound(param))
        return bounds

    def get_bound(self,
                  parameter: str) -> tuple[float, float]:
        """Get the bounds for a given parameter

        Args:
            parameter (str): parameter in sop.parameters_names

        Returns:
            tuple[float, float]: absolute values of the bounds
        """
        pt = Ptype.WE
        for ptype in Ptype:
            if ptype.value in parameter:
                pt: Ptype = ptype
                break
        return self.pert.get_boundaries(
            ptype=pt.value,
            i_val=self.f_el.sop.parameters_names[parameter]
            )

    def print_stats(self,
                    params: NDArray) -> None:
        line_tpl = '{name:<15}{start:>10}{current:>10}'
        msg = '\n'
        msg += line_tpl.format(
            name='PARAMETER',
            start='INITIAL',
            current='CURRENT') + '\n'
        for idx, p in enumerate(self.current_dimensions):
            start: float = self.f_el.sop.parameters_names[p]
            current: float = params[idx]
            if start >= 1000:
                str_start: str = f"{start:-6.2E}"
            else:
                str_start: str = f"{start:-6.2f}"
            if current >= 1000:
                str_current: str = f"{current:-6.2E}"
            else:
                str_current: str = f"{current:-6.2f}"
            msg += line_tpl.format(
                name=p,
                start=str_start,
                current=str_current) + '\n'
        self.klog.info(msg)
