import os
import threading
from typing import Any, Optional
from kimeco.core import CoreRun
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.element import Element
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.enums import ElementStatus
from kimeco.logger_config import KMOLogger
from kimeco.q_sys import QueueingSystem


class NMSRunner(CoreRun):
    """NelderMead Swarm Runner - manages dynamic element pool for NM.

    Key differences from CoreRun:
    - Elements are added dynamically via add_element()
    - Each element routes to table based on el.gen (e.g., G0000, G0001)
    - Element pool has fixed size (thread count) but contents change
    - Tables/folders created on-demand per generation
    """

    def __init__(self,
                 settings: dict[str, Any],
                 rc_tpl: list[str],
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 klog: KMOLogger,
                 pert: Optional[Perturbator] = None) -> None:
        """Initialize NMSRunner.

        Args:
            settings: Configuration dictionary
            rc_tpl: Rate coefficient template
            sop_db: SOP database
            kin_db: Kinetics database
            sim_db: Simulation database
            sf: Scoring function
            klog: Logger
            pert: Perturbator (unused, kept for compatibility)
        """
        # Initialize with empty element list
        super().__init__(
            elements=[],
            settings=settings,
            rc_tpl=rc_tpl,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            sf=sf,
            pert=pert,
            klog=klog,
            previous_el={},
            prefix='NMSG'  # Swarm Generation
        )
        # Override elements with dynamic pool (consistent name)
        self.elements: list[Element | None] = [None] * settings['threads']
        # Override QueueingSystem with updated element count
        self.qs = QueueingSystem(
            settings=self.settings,
            nel=settings['threads'],
            nhlp=0,  # Helpers removed - no longer used
            klog=self.klog)

        # Pool-level lock to guard mutations and snapshots
        self.pool_lock = threading.Lock()

        # Track which tables have been created
        self.created_tables: set[str] = set()

        # Lock for table creation
        self.table_creation_lock = threading.Lock()

        # Lock to guard el_locks dict creation
        self.el_locks_lock = threading.Lock()

        # Element counter for defragmentation
        self.elem_count: int = 0

    def add_element(self, el: Element) -> None:
        """Add an element to the first available pool slot.

        Args:
            el: Element to add

        Returns:
            None
        """

        # Find first available slot
        for idx in range(self.settings['threads']):
            if self.elements[idx] is None:
                el.thread_id = idx
                self.elements[idx] = el
                self.klog.debug(
                    f'Element {el.id} (Gen {el.gen}) added to pool at thread {idx}.')
                break
        if el not in self.elements:
            raise RuntimeError("Failed to add element to pool")
        # Ensure tables and folders exist
        self._ensure_infrastructure_exists(el)

    def remove_element(self, el: Element) -> Element:
        """Remove an element from the pool and return it.

        Args:
            el: Element to remove

        Returns:
            The removed element
        """
        with self.pool_lock:
            self.elements[el.thread_id] = None

        self.klog.debug(f'Element {el.id} (Gen {el.gen}) removed from pool.')
        self.klog.debug(f'Thread {el.thread_id} is now available.')

    def _ensure_infrastructure_exists(self, el: Element) -> None:
        """Ensure tables and folders exist for element's generation.

        Args:
            el: Element whose infrastructure to create
        """
        table_name: str = self.get_table_name(el)

        # Thread-safe table creation
        with self.table_creation_lock:
            if table_name not in self.created_tables:
                # Create database tables
                if table_name not in self.sop_db.tables:
                    self.sop_db.create_new_table(name=table_name)
                if table_name not in self.kin_db.tables:
                    self.kin_db.create_new_table(name=table_name)
                if table_name not in self.sim_db.tables:
                    self.sim_db.create_new_table(name=table_name)

                self.created_tables.add(table_name)

        # Create folder structure
        gen_folder: str = self.get_gen_folder(el)
        if not os.path.exists(gen_folder):
            os.makedirs(gen_folder + '/logs', exist_ok=True)

        # Create subfolder for element (50 elements per subfolder)
        subfolder: str = self.get_element_subfolder(el)
        if not os.path.exists(subfolder):
            os.makedirs(subfolder + '/logs', exist_ok=True)

            # Symlink necessary files
            for file in el.sop.files2copy:
                src: str = f'{self.loc}/{file}'
                dst: str = f'{subfolder}/{file}'
                if os.path.exists(src) and not os.path.exists(dst):
                    os.symlink(src, dst)

    def run(self, el: Element) -> Element:
        """Process an element until it reaches DONE status.

        This is the main entry point for NelderMead swarm instances.

        Args:
            el: Element to process

        Returns:
            The processed element (status == DONE)
        """
        # Add element to pool with safeguard
        with self.pool_lock:
            if self.elements.count(None) == 0:
                raise RuntimeError("No available slots in element pool")
            else:
                self.add_element(el)

        # Ensure lock exists for this element
        if (el.gen, el.id) not in self.el_locks:
            self.el_locks[(el.gen, el.id)] = threading.Lock()

        # Process until done
        while el.status != ElementStatus.DONE:
            try:
                self._process_single_element(el)
            except Exception as e:
                self.remove_element(el)
                self.klog.error(f'Status of element {el.id}: {el.status}')
                raise e

        # Remove and return
        self.remove_element(el)
        return el

    def _process_single_element(self, el: Element) -> None:
        """Process one iteration of a single element.

        Args:
            el: Element to process
        """
        if el.status == ElementStatus.DONE:
            return

        # Try to acquire lock (non-blocking)
        if not self.el_locks[(el.gen, el.id)].acquire(blocking=False):
            return

        # Process element with lock held
        try:
            self._process_element_locked(el)
        except Exception as e:
            self.klog.error(f'Error processing element {el.id}: {e}')
            raise e

        # Batch database operations (per element)
        self.sop_db.batch_upsert()
        self.kin_db.batch_upsert()
        self.sim_db.batch_upsert()

        # Collect simulation profiles for this element
        if el:
            self.collect_sim_profiles()

        # Run queuing system
        with self.qs_lock:
            self.qs.run()

    def reset_element(self, el: Element) -> None:
        raise NotImplementedError('NMS cannot reset elements.')

    def collect_sim_profiles(self) -> None:
        """Override: Map DB profiles back to active elements by (gen,id).

        This version scans self.elements (thread-indexed) to find
        the matching element rather than relying on CoreRun.elements.
        """
        if len(self.sim_db._select) == 0:
            return
        nsim: int = self.settings['n_exp']

        collecting = self.sim_db.batch_select()

        # Process each table's results
        for table_name, profiles in collecting.items():
            gen_id = int(table_name[1:5])  # Extract from G#### or SG####

            for sim_id, db_data in profiles.items():
                el_id = sim_id // nsim
                sim_idx = sim_id % nsim

                # Find element with matching ID and generation
                el = None
                with self.pool_lock:
                    for e in self.elements:
                        if e is not None and e.id == el_id and e.gen == gen_id:
                            el = e
                            break
                if el is None:
                    continue

                # number of timesteps
                nsteps: int = len(self.settings['exp_profiles'][sim_idx][0])

                # Validate data completeness
                if len(db_data) != nsteps:
                    continue

                el.sim.profiles[sim_idx] = db_data

                # Scoring needs all the profiles
                if all([prof is not None for prof in el.sim.profiles]):
                    el.status = ElementStatus.SCORING

    @property
    def finished(self) -> bool:
        """Check if all elements in pool are done."""
        return all([
            el is None or el.status == ElementStatus.DONE
            for el in self.elements
        ])

    @property
    def best_score(self) -> float:
        """Get best score from active elements."""
        active_elements = [
            el for el in self.elements if el is not None
        ]
        if not active_elements:
            return float('inf')
        return min([el.score for el in active_elements])
