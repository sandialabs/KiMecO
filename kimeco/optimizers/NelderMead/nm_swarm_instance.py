from typing import Any
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from kimeco.optimizers.NelderMead.nelder_mead import NelderMead
from kimeco.element import Element
from kimeco.goat import GOATs
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
                 shared_core: NMSRunner
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
        self.gen_counter = 0
        self.current_dimensions: list[str] = dimensions

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
            klog=klog
        )
        self.shared_core: NMSRunner = shared_core
        # Override name and working directory
        self.name: str = f'E{self.nm_id:04d}'

        # Create instance-specific score file
        self.score_file: str = \
            f'{self.wdir}/nm_swarm/NM{self.nm_id:04d}_scores.txt'
        with open(self.score_file, 'w', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter='ITERATION',
                score='SCORE'))

    def run(self) -> NDArray:
        """Run the Nelder-Mead optimization with fixed dimensions."""
        # Use fixed dimensions (no sensitivity analysis)

        # Run initial optimization
        result = minimize(
            fun=self.objective_function,
            x0=self.get_initial_vertice(),
            method='Nelder-Mead',
            bounds=[(-1, 1) for _ in self.current_dimensions],
            options=self.get_options(initial=False)
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
        table_name = f'NM{self.nm_id:04d}'
        if self.is_vertice_finished(nm_id=self.nm_id,
                                    elem_id=self.gen_counter):
            sop_in_db = True
            try:
                db_row: list[float] = self.sop_db.get_sop_row(
                    table=table_name,
                    id=self.gen_counter)[1:]
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
        self.shared_core.add_element(el=vertice)
        finished_vertice: Element = self.shared_core.run(nm_el=vertice)

        # Increment element counter for next evaluation
        self.gen_counter += 1

        self.print_stats(
            params=np.array([
                self.get_absolute(
                    param=p,
                    value=params[self.current_dimensions.index(p)])
                for p in self.current_dimensions]))
        self.update_iterations(last_vertice=finished_vertice)

        return finished_vertice.score

    def is_vertice_finished(self,
                            nm_id: int,
                            elem_id: int) -> bool:
        """Check if a table is finished.

        Args:
            nm_id: ID of the nelder-mead instance
            elem_id: Element ID to check
        Returns:
            bool: Whether it is finished
        """
        table_name: str = f"NM{nm_id:04d}"

        if self.sop_db.table_exists(table_name) and\
           self.kin_db.table_exists(table_name) and\
           self.sim_db.table_exists(table_name):
            sop_ids = set(self.sop_db.get_column(
                table=table_name,
                column_name='id'))
            kin_ids = set(self.kin_db.get_column(
                table=table_name,
                column_name='kin_id'))
            tmp = np.array(self.sim_db.get_column(
                table=table_name,
                column_name='sim_id'))//len(self.settings['exp_profiles'])
            sim_ids = set(tmp.tolist())
            if elem_id in sop_ids and\
               elem_id in kin_ids and\
               elem_id in sim_ids:
                return True
            else:
                return False
        else:
            return False

    def update_iterations(self,
                          last_vertice: Element) -> None:
        """Keep track of the scores."""
        with open(self.score_file, 'a', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter=last_vertice.id,
                score=f"{last_vertice.score:.3f}"))

    def get_best_element(self) -> Element:
        """Get the best element found during optimization.

        Returns:
            Element with lowest score
        """
        all_vertices: list[Element] = []
        rows = self.sop_db.get_table(table=f'NM{self.nm_id:04d}')
        for row in rows:
            el = SOP.from_db_row(
                sop_tpl=self.f_el.sop,
                row=row[1:])  # Skip id
            element = Element(
                sop=el,
                id=row[0],  # id
                gen=self.nm_id,
                status=ElementStatus.DONE.value)
            all_vertices.append(element)

        # Return element with best score
        return min(all_vertices, key=lambda el: el.score)