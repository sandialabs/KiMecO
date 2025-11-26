from logging import Logger
from typing import Any
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from optimizers.NelderMead.nelder_mead import NelderMead
from kimeco.element import Element
from kimeco.goat import GOATs
from scipy.optimize import minimize
from numpy.typing import NDArray
from kimeco.parameters import SOP
from kimeco.enums import ElementStatus


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
                 klog: Logger,
                 dimensions: list[str],
                 nm_subdir: str,
                 registry: Any = None
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
        self.nm_subdir: str = nm_subdir
        self.registry = registry
        self.element_counter = 0
        self.fixed_dimensions: list[str] = dimensions

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

        # Override name and working directory
        self.name = f'NM{self.nm_id:04d}'
        self.wdir = nm_subdir

        # Override GOATs to use nm_subdir
        self.iterations = GOATs(
            sop_db=sop_db,
            sim_db=sim_db,
            kin_db=kin_db,
            wdir=self.wdir
        )

        # Create instance-specific score file
        self.score_file = f'{self.wdir}/NM_scores.txt'
        with open(self.score_file, 'w', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter='ITERATION',
                score='SCORE'))

    @property
    def dimensionality_changed(self) -> bool:
        """For swarm instances, dimensions are fixed."""
        return False

    def run(self) -> NDArray:
        """Run the Nelder-Mead optimization with fixed dimensions."""
        # Use fixed dimensions (no sensitivity analysis)
        self.current_dimensions = self.fixed_dimensions
        self.new_parameters = []

        msg = f"NM{self.nm_id:04d} dimensions: {self.current_dimensions}\n"
        self.klog.info(msg)

        # Run initial optimization
        result = minimize(
            fun=self.objective_function,
            x0=self.get_initial_vertice(),
            method='Nelder-Mead',
            bounds=[(-1, 1) for _ in self.current_dimensions],
            options=self.get_options(initial=True)
        )

        if not result.success:
            self.klog.error(f"NM{self.nm_id:04d} optimization failed: {result.message}")
            raise RuntimeError(f"Nelder-Mead {self.nm_id} optimization failed.")

        # Run refined optimization
        self.klog.info(f"NM{self.nm_id:04d}: Increasing accuracy for final minimization")
        result = minimize(
            fun=self.objective_function,
            x0=self.get_initial_vertice(),
            method='Nelder-Mead',
            bounds=[(-1, 1) for _ in self.current_dimensions],
            options=self.get_options(initial=False)
        )

        if result.success:
            self.klog.info(f"NM{self.nm_id:04d} optimization completed successfully")
            self.klog.info(f"NM{self.nm_id:04d} final parameters: {result.x}")
        else:
            self.klog.error(f"NM{self.nm_id:04d} final optimization failed: {result.message}")
            raise RuntimeError(f"Nelder-Mead {self.nm_id} final optimization failed.")

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
                                    elem_id=self.element_counter):
            sop_in_db = True
            try:
                db_row: list[float] = self.sop_db.get_sop_row(
                    table=table_name,
                    id=self.element_counter)[1:]
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
                        id=self.element_counter,
                        gen=self.nm_id,
                        status=ElementStatus.DONE.value)
                else:
                    vertice = Element(
                        sop=self.last_vertice,
                        id=self.element_counter,
                        gen=self.nm_id)
            else:
                vertice = Element(
                    sop=self.last_vertice,
                    id=self.element_counter,
                    gen=self.nm_id)
        else:
            vertice = Element(
                sop=self.last_vertice,
                id=self.element_counter,
                gen=self.nm_id)

        # Create a generation-like run but with NM table names
        new_gen = GenerationForNM(
            elements=[vertice],
            settings=self.settings,
            rc_tpl=self.input_tpl,
            sop_db=self.sop_db,
            kin_db=self.kin_db,
            sim_db=self.sim_db,
            sf=self.sf,
            pert=self.pert,
            klog=self.klog,
            previous_el={self.element_counter: self.f_el},
            name=table_name
        )
        new_gen.run()

        # Increment element counter for next evaluation
        self.element_counter += 1

        # Register with registry if provided
        if self.registry is not None:
            self.registry.register_nm_element(self.nm_id, new_gen.elements[0])

        self.print_stats(
            params=np.array([
                self.get_absolute(
                    param=p,
                    value=params[self.current_dimensions.index(p)])
                for p in self.current_dimensions]))
        self.update_iterations(last_vertice=new_gen.elements[0])

        return new_gen.elements[0].score

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
        table_name = f"NM{nm_id:04d}"

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
            if elem_id in sop_ids and elem_id in kin_ids and elem_id in sim_ids:
                return True
            else:
                return False
        else:
            return False
    
    def update_iterations(self, last_vertice: Element) -> None:
        """Keep track of the goat list and scores."""
        self.latest_simplex: list[Element] = self.iterations.update_with_generation(
            elements=[last_vertice],
            goat_length=len(self.current_dimensions) + 1
        )
        with open(self.score_file, 'a', encoding='utf-8') as f:
            f.write(self.score_line_tpl.format(
                iter=last_vertice.id,  # Use element id instead of gen
                score=f"{last_vertice.score:.3f}"))
    
    def get_best_element(self) -> Element:
        """Get the best element found during optimization.
        
        Returns:
            Element with lowest score
        """
        if len(self.iterations.generations) == 0:
            return self.f_el
        
        # Get the last generation (best elements)
        last_simp = self.iterations.get_goat_for_gen(-1)
        if len(last_simp) == 0:
            return self.f_el
        
        # Return element with best score
        return min(last_simp, key=lambda el: el.score)