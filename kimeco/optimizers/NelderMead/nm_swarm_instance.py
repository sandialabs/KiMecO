from typing import Any
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from kimeco.optimizers.NelderMead.nelder_mead import NelderMead
from kimeco.optimizers.NelderMead.db_query_saver import DBQuerySaver
from kimeco.element import Element
from scipy.optimize import minimize
from numpy.typing import NDArray
from kimeco.parameters import SOP
from kimeco.enums import ElementStatus
from kimeco.optimizers.NelderMead.nm_swarm_runner import NMSRunner
from kimeco.logger_config import KMOLogger
import numpy as np


class NelderMeadInstance(NelderMead):
    """Nelder-Mead instance for use within NelderMeadSwarm.

    Uses instance-specific table naming (NM0000, NM0001, ...), maintains
    per-instance element counters, and works with fixed dimensions (no
    sensitivity analysis during optimization).
    """

    def __init__(self,
                 nm_id: int,
                 settings: dict[str, Any],
                 sf: Scoring,
                 pert: Perturbator,
                 sop_db: SOP_DB,
                 sim_db: SIM_DB,
                 kin_db: KIN_DB,
                 f_el: Element,
                 input_tpl: list[str],
                 klog: KMOLogger,
                 dimensions: list[str],
                 shared_core: NMSRunner,
                 dbqs: DBQuerySaver,
                 prefix: str = ''
                 ) -> None:
        """Initialize NelderMeadInstance.

        Args:
            nm_id: Unique ID for this NM instance
            settings: Configuration dictionary
            sf: Scoring function
            pert: Perturbator
            sop_db: SOP database
            sim_db: Simulation database
            kin_db: Kinetics database
            f_el: Initial element
            input_tpl: Rate constant template
            klog: Logger
            dimensions: Fixed list of parameters to optimize
            nm_subdir: Subdirectory for this instance's files
            registry: Optional SwarmRegistry for tracking elements
        """
        self.nm_id: int = nm_id
        self.gen_prefix: str = prefix + 'G'
        self.prefix: str = prefix + f'{nm_id:04d}'
        self.gen_counter = 0
        self.dbqs: DBQuerySaver = dbqs
        # Call parent init but override some behaviors
        super().__init__(
            settings=settings,
            sf=sf,
            pert=pert,
            sop_db=sop_db,
            sim_db=sim_db,
            kin_db=kin_db,
            f_el=f_el,
            input_tpl=input_tpl,
            klog=klog,
            prefix=self.prefix
        )
        self.new_parameters: list[str] = dimensions
        self.current_dimensions: list[str] = []
        self.shared_core: NMSRunner = shared_core
        # Override name and working directory
        self.name: str = f'E{self.nm_id:04d}'

        # Create instance-specific score file
        self.score_file: str = f'{self.wdir}/{self.prefix}_scores.txt'
        with open(self.score_file, 'w', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter='ITERATION',
                score='SCORE'))

    def get_options(self,
                    initial: bool = True) -> dict[str, Any]:
        options: dict[str, Any] = {'disp': True}
        options['initial_simplex'] = self.get_initial_simplex()

        self.klog.debug(
            f"Setting final Nelder-Mead fatol="
            f"{self.settings['nm_final_fatol']}")
        options['fatol'] = self.settings['nm_final_fatol']

        self.klog.debug(
            f"Setting final Nelder-Mead xatol="
            f"{self.settings['nm_final_xatol']}")
        options['xatol'] = self.settings['nm_final_xatol']

        if self.settings['nm_final_maxiter'] > 0:
            self.klog.debug(
                f"Setting final Nelder-Mead maxiter="
                f"{self.settings['nm_final_maxiter']}")
            options['maxiter'] = self.settings['nm_final_maxiter']

        if self.settings['nm_maxfev'] > 0:
            self.klog.debug(
                f"Setting final Nelder-Mead maxfev="
                f"{self.settings['nm_final_maxfev']}")
            options['maxfev'] = self.settings['nm_final_maxfev']

        if self.settings['nm_adaptive']:
            self.klog.debug("Using adaptive for final Nelder-Mead")
            options['adaptive'] = True
            # better performance in high D.
        return options

    def run(self) -> NDArray:
        """Run the Nelder-Mead optimization with fixed dimensions."""
        # Use fixed dimensions (no sensitivity analysis)
        """Run the Nelder-Mead optimization."""
        initial = True
        # while self.dimensionality_changed or result['fun'] > 9:
        self.current_dimensions = self.new_parameters
        self.new_parameters = []

        # Run initial optimization
        result = minimize(
            fun=self.objective_function,
            x0=self.get_initial_vertice(),
            method='Nelder-Mead',
            bounds=[(-1, 1) for _ in self.current_dimensions],
            options=self.get_options(initial=initial)
        )

        if result.success:
            self.klog.debug(f"NM{self.nm_id:04d} optimization completed")
            self.klog.debug(f"NM{self.nm_id:04d} final parameters: {result.x}")
        else:
            self.klog.error(
                f"NM{self.nm_id:04d} optimization failed: {result.message}")

        return result.x

    def objective_function(self, params: NDArray) -> float:
        """Objective function with per-instance element tracking."""
        row = [
            v
            if p not in self.current_dimensions
            else self.get_absolute(
                param=p,
                value=params[self.current_dimensions.index(p)])
            for p, v in self.last_vertice.parameters_names.items()]

        # SOP from vertice
        self.last_vertice = SOP.from_db_row(
            sop_tpl=self.f_el.sop,
            row=row
        )

        # Check if this SOP already exists in our NM table
        table_name: str = f'{self.gen_prefix}{self.gen_counter:04d}'
        if self.dbqs.is_vertice_finished(gen_id=self.gen_counter,
                                         el_id=self.nm_id,
                                         prefix=self.gen_prefix):
            self.klog.debug(
                f"NM{self.nm_id:04d} call {self.gen_counter} is in db.")
            sop_in_db = True
            try:
                db_row: list[float] = self.sop_db.get_sop_row(
                    table=table_name,
                    id=self.nm_id)[1:]
            except Exception as e:
                sop_in_db = False
                self.klog.debug(str(e))

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
                        id=self.nm_id,
                        gen=self.gen_counter,
                        status=ElementStatus.DONE.value)
                else:
                    vertice = Element(
                        sop=self.last_vertice,
                        id=self.nm_id,
                        gen=self.gen_counter)
            else:
                vertice = Element(
                    sop=self.last_vertice,
                    id=self.nm_id,
                    gen=self.gen_counter)
        else:
            vertice = Element(
                sop=self.last_vertice,
                id=self.nm_id,
                gen=self.gen_counter)

        # Create a generation-like run but with NM table names
        finished_vertice: Element = self.shared_core.run(el=vertice)

        # Increment element counter for next evaluation
        self.gen_counter += 1

        # self.print_stats(
        #     params=np.array([
        #         self.get_absolute(
        #             param=p,
        #             value=params[self.current_dimensions.index(p)])
        #         for p in self.current_dimensions]))
        self.update_iterations(last_vertice=finished_vertice)

        return finished_vertice.score

    # def is_vertice_finished(self,
    #                         gen_id: int,
    #                         elem_id: int) -> bool:
    #     """Check if a table is finished.

    #     Args:
    #         nm_id: ID of the nelder-mead instance
    #         elem_id: Element ID to check
    #     Returns:
    #         bool: Whether it is finished
    #     """
    #     table_name: str = f"{self.gen_prefix}{gen_id:04d}"

    #     if self.sop_db.table_exists(table_name) and\
    #        self.kin_db.table_exists(table_name) and\
    #        self.sim_db.table_exists(table_name):
    #         sop_ids = set(self.sop_db.get_column(
    #             table=table_name,
    #             column_name='id'))
    #         kin_ids = set(self.kin_db.get_column(
    #             table=table_name,
    #             column_name='kin_id'))
    #         tmp = np.array(self.sim_db.get_column(
    #             table=table_name,
    #             column_name='sim_id'))//len(self.settings['exp_profiles'])
    #         sim_ids = set(tmp.tolist())
    #         if elem_id in sop_ids and\
    #            elem_id in kin_ids and\
    #            elem_id in sim_ids:
    #             return True
    #         else:
    #             return False
    #     else:
    #         return False

    def update_iterations(self,
                          last_vertice: Element) -> None:
        """Keep track of the scores."""
        with open(self.score_file, 'a', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter=self.gen_counter,
                score=f"{last_vertice.score:.3f}"))

    def get_best_element(self) -> Element:
        """Get the best element found during optimization.

        Returns:
            Element with lowest score
        """
        all_vertices: list[Element] = []
        rows = self.sop_db.get_table(
            table=f'{self.gen_prefix}{self.gen_counter:04d}')
        for row in rows:
            sop = SOP.from_db_row(
                sop_tpl=self.f_el.sop,
                row=row[1:])  # Skip id
            element = Element(
                sop=sop,
                id=row[0],  # id
                gen=self.gen_counter,
                status=ElementStatus.DONE.value)
            all_vertices.append(element)

        # Return element with best score
        return min(all_vertices, key=lambda el: el.score)
