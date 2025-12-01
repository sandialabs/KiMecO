import time
from typing import Any
import os
import multiprocessing
import threading
import concurrent.futures
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.scoring_f.scoring import Scoring
from kimeco.sensitivity.linear import Linear
from kimeco.optimizers.NelderMead.nm_swarm_instance import NelderMeadInstance
from kimeco.optimizers.NelderMead.nm_swarm_runner import NMSRunner
from kimeco.logger_config import KMOLogger


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
                 klog: KMOLogger,
                 pert: Perturbator) -> None:
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
            klog: KMOLogger
        """
        self.new_folder_lock = threading.Lock()
        self.pert: Perturbator = pert
        self.elements: list[Element] = elements
        self.settings: dict[str, Any] = settings
        self.sf: Scoring = sf
        self.input_tpl: list[str] = input_tpl
        self.klog: KMOLogger = klog
        self.wdir: str = settings['workdir']
        self.swarm_dir: str = os.path.join(self.wdir, 'nm_swarm')
        if not os.path.exists(self.swarm_dir):
            os.makedirs(self.swarm_dir, exist_ok=True)
        os.chdir(self.swarm_dir)
        # Create swarm directory
        self.initialize_databases()
        self.core = NMSRunner(
            settings=settings,
            sf=sf,
            sop_db=sop_db,
            sim_db=sim_db,
            kin_db=kin_db,
            rc_tpl=input_tpl,
            klog=klog
        )
        # Determine dimensionality via sensitivity analysis
        self.dimensions: list[str] = []
        self.determine_dimensions()

        # Results storage
        self.nm_instances: list[NelderMeadInstance] = []
        self.results: list[dict[str, Any]] = []

        # Determine number of workers
        cpu_count: int = multiprocessing.cpu_count()
        threads: int = self.settings['threads']
        self.max_workers: int = min(cpu_count, threads)
        self.klog.info(f"N-M Swarm with {len(self.elements)} instances")
        self.klog.info(
            f"Using {self.max_workers} parallel workers" + "\n"
            f"(CPU count: {cpu_count}, threads limit: {threads})"
        )

    def initialize_databases(self) -> None:
        """Create the three databases used by KiMecO
        """
        start_time: float = time.time()
        self.sop_db = SOP_DB(sop=self.elements[0].sop,
                             name='NMS_DB_SOP',
                             threads=self.settings['threads'],
                             path=self.swarm_dir)
        sop_db_time: float = time.time() - start_time
        msg = 'NMS_DB_SOP initialized:'
        self.klog.info(f"{msg:<65}{sop_db_time:>15.1f}")
        self.kin_db = KIN_DB(sop=self.elements[0].sop,
                             name='NMS_DB_KIN',
                             threads=self.settings['threads'],
                             path=self.swarm_dir)
        kin_db_time: float = time.time() - start_time - sop_db_time
        msg = 'NMS_DB_KIN initialized:'
        self.klog.info(f"{msg:<65}{kin_db_time:>15.1f}")
        self.sim_db = SIM_DB(sop=self.elements[0].sop,
                             name='NMS_DB_SIM',
                             threads=self.settings['threads'],
                             path=self.swarm_dir)
        sim_db_time: float = \
            time.time() - start_time - sop_db_time - kin_db_time
        msg = 'NMS_DB_SIM initialized:'
        self.klog.info(f"{msg:<65}{sim_db_time:>15.1f}")

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
        self.klog.info(f"Optimizing dimensions: {self.dimensions}")

        # Launch parallel NM instances
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_nm = {}
            for nm_id, el in enumerate(self.elements):
                future = executor.submit(
                    self._run_single_nm,
                    nm_id=nm_id,
                    el=el
                )
                future_to_nm[future] = nm_id

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_nm):
                nm_id = future_to_nm[future]
                try:
                    result = future.result()
                    self.results.append(result)
                    self.klog.info(
                        f"NelderMead {nm_id:04d} completed successfully")
                except Exception as exc:
                    self.klog.error(
                        f"NelderMead {nm_id:04d} failed with exception: {exc}")
                    self.results.append({
                        'nm_id': nm_id,
                        'success': False,
                        'error': str(exc),
                        'best_element': None
                    })

        # Return best elements
        best_elements: list[Element] = [
            r['best_element'] for r in self.results if r['success']]
        self.klog.info(
            f"NM Swarm completed: {len(best_elements)}/{len(self.elements)}")

        return best_elements

    def _run_single_nm(self,
                       nm_id: int,
                       el: Element) -> dict[str, Any]:
        """Run a single Nelder-Mead optimization.

        Args:
            nm_id: ID for this NM instance
            el: Starting element

        Returns:
            Dictionary with results
        """

        # Create instance
        nm = NelderMeadInstance(
                nm_id=nm_id,
                settings=self.settings,
                sf=self.sf,
                pert=self.pert,
                sop_db=self.sop_db,
                sim_db=self.sim_db,
                kin_db=self.kin_db,
                f_el=el,
                input_tpl=self.input_tpl,
                klog=self.klog,
                dimensions=self.dimensions,  # Will be set later
                shared_core=self.core
            )

        # Run optimization
        result_x = nm.run()

        # Get best element
        best_el: Element = nm.get_best_element()

        return {
            'nm_id': nm_id,
            'success': True,
            'result_x': result_x,
            'best_element': best_el,
            'iterations': len(nm.iterations.generations)
        }

    def create_dir(self,
                   el: Element) -> None:
        with self.new_folder_lock:
            dir_name: str = f"{self.swarm_dir}/G{el.gen:04d}"
            if not os.path.exists(dir_name):
                os.makedirs(dir_name, exist_ok=True)
                os.makedirs(dir_name + '/logs', exist_ok=True)
                for file in el.sop.files2copy:
                    src: str = f"{self.wdir}/{file}"
                    dst: str = f"{dir_name}/{file}"
                    if os.path.exists(src) and not os.path.exists(dst):
                        os.symlink(src, dst)

