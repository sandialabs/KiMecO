from logging import Logger
from typing import Any
import os
import multiprocessing
import concurrent.futures
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.enums import ElementStatus
from kimeco.scoring_f.scoring import Scoring
from kimeco.sensitivity.linear import Linear
from optimizers.NelderMead.nm_swarm_instance import NelderMeadInstance
from optimizers.NelderMead.nm_swarm_runner import NMSRunner


class NelderMeadSwarm:
    """Parallel execution of multiple Nelder-Mead optimizations.

    Runs independent Nelder-Mead optimizations in parallel, each starting from
    a different initial element. Performs a single upfront sensitivity analysis
    to determine the parameter dimensions used by all NM instances.
    """

    def __init__(self,
                 elements: list[Element],
                 settings: dict[str, Any],
                 sf: Scoring,
                 sop_db: SOP_DB,
                 sim_db: SIM_DB,
                 kin_db: KIN_DB,
                 input_tpl: list[str],
                 klog: Logger) -> None:
        """Initialize the NelderMeadSwarm.
        
        Args:
            elements: List of starting elements (one per NM instance)
            settings: Configuration dictionary
            sf: Scoring function
            pert: Perturbator
            sop_db: SOP database
            sim_db: Simulation database
            kin_db: Kinetics database
            input_tpl: Rate constant template
            klog: Logger
        """
        self.elements: list[Element] = elements
        self.settings: dict[str, Any] = settings
        self.sf: Scoring = sf
        self.sop_db: SOP_DB = sop_db
        self.sim_db: SIM_DB = sim_db
        self.kin_db: KIN_DB = kin_db
        self.input_tpl: list[str] = input_tpl
        self.klog: Logger = klog
        self.wdir: str = settings['workdir']
        self.core = NMSRunner(
            settings=settings,
            sf=sf,
            sop_db=sop_db,
            sim_db=sim_db,
            kin_db=kin_db,
            rc_tpl=input_tpl,
            klog=klog
        )

        # Create swarm directory
        self.swarm_dir = os.path.join(self.wdir, 'nm_swarm')
        os.makedirs(self.swarm_dir, exist_ok=True)

        # Determine dimensionality via sensitivity analysis on average element
        self.dimensions: list[str] = []
        self.determine_dimensions()

        # Results storage
        self.nm_instances: list[NelderMeadInstance] = []
        self.results: list[dict[str, Any]] = []

    def determine_dimensions(self) -> None:
        """Perform sensitivity analysis to determine dimensions.

        Sets self.dimensions to the list of parameters to optimize.
        """
        self.klog.info("Running sensitivity analysis NM Swarm")
        sensitivity = Linear(
            elements=self.elements,
            settings=self.settings,
            rc_tpl=self.input_tpl,
            sf=self.sf,
            klog=self.klog
        )
        sensitivity.run()

        self.dimensions = sensitivity.selected
        self.klog.info(
            "Determined dimensions for all NM instances:\n" +
            f"{self.dimensions}")

    def run(self) -> list[Element]:
        """Run all Nelder-Mead optimizations in parallel.

        Returns:
            List of best elements (one per NM instance)
        """
        
        # Determine number of workers
        cpu_count = multiprocessing.cpu_count()
        threads_limit = self.settings.get('threads', cpu_count)
        max_workers = min(cpu_count, threads_limit)
        
        self.klog.info(f"Starting NelderMeadSwarm with {len(self.initial_elements)} instances")
        self.klog.info(f"Using {max_workers} parallel workers (CPU count: {cpu_count}, threads limit: {threads_limit})")
        self.klog.info(f"Optimizing dimensions: {self.dimensions}")
        
        # Create per-NM subdirectories
        for nm_id in range(len(self.initial_elements)):
            nm_subdir = os.path.join(self.swarm_dir, f'NM{nm_id:04d}')
            os.makedirs(nm_subdir, exist_ok=True)
        
        # Launch parallel NM instances
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_nm = {}
            for nm_id, initial_el in enumerate(self.initial_elements):
                future = executor.submit(
                    self._run_single_nm,
                    nm_id=nm_id,
                    initial_el=initial_el
                )
                future_to_nm[future] = nm_id
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_nm):
                nm_id = future_to_nm[future]
                try:
                    result = future.result()
                    self.results.append(result)
                    self.klog.info(f"NelderMead {nm_id:04d} completed successfully")
                except Exception as exc:
                    self.klog.error(f"NelderMead {nm_id:04d} failed with exception: {exc}")
                    self.results.append({
                        'nm_id': nm_id,
                        'success': False,
                        'error': str(exc),
                        'best_element': None
                    })
        
        # Write unified GOAT file
        goat_file = os.path.join(self.swarm_dir, 'swarm_goats.txt')
        self.registry.write_swarm_goat_file(goat_file)
        
        # Return best elements
        best_elements = [r.get('best_element') for r in self.results if r.get('success') and r.get('best_element')]
        self.klog.info(f"NelderMeadSwarm completed: {len(best_elements)}/{len(self.initial_elements)} succeeded")
        
        return best_elements
    
    def _run_single_nm(self, nm_id: int, initial_el: Element) -> dict[str, Any]:
        """Run a single Nelder-Mead optimization.
        
        Args:
            nm_id: ID for this NM instance
            initial_el: Starting element
            
        Returns:
            Dictionary with results
        """
        
        try:
            # Create NM instance subdirectory
            nm_subdir = os.path.join(self.swarm_dir, f'NM{nm_id:04d}')
            
            # Create instance
            nm = NelderMeadInstance(
                nm_id=nm_id,
                settings=self.settings,
                sf=self.sf,
                pert=self.pert,
                sop_db=self.sop_db,
                sim_db=self.sim_db,
                kin_db=self.kin_db,
                f_el=initial_el,
                input_tpl=self.input_tpl,
                klog=self.klog,
                dimensions=self.dimensions,
                nm_subdir=nm_subdir,
                registry=self.registry
            )
            
            # Run optimization
            result_x = nm.run()
            
            # Register GOATs with registry
            self.registry.register_nm_goats(nm_id, nm.iterations)
            
            # Get best element
            best_el = nm.get_best_element()
            
            return {
                'nm_id': nm_id,
                'success': True,
                'result_x': result_x,
                'best_element': best_el,
                'iterations': len(nm.iterations.generations)
            }
            
        except Exception as exc:
            self.klog.error(f"NelderMead {nm_id:04d} encountered error: {exc}")
            import traceback
            self.klog.error(traceback.format_exc())
            raise
