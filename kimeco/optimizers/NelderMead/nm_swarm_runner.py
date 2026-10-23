import os
import threading
from typing import Any, Optional
from kimeco.core import CoreRun
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.model import Model
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.enums import ModelStatus
from kimeco.logger_config import KMOLogger
from kimeco.q_sys import QueueingSystem


class NMSRunner(CoreRun):
    """NelderMead Swarm Runner - manages dynamic model pool for NM.

    Key differences from CoreRun:
    - Models are added dynamically via add_model()
    - Each model routes to table based on mdl.gen (e.g., G0000, G0001)
    - Model pool has fixed size (thread count) but contents change
    - Tables/folders created on-demand per generation
    """

    def __init__(self,
                 settings: dict[str, Any],
                 rc_tpls: list[list[str]],
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 klog: KMOLogger,
                 pert: Optional[Perturbator] = None) -> None:
        """Initialize NMSRunner.

        Args:
            settings: Configuration dictionary
            rc_tpls: Rate coefficient templates
            sop_db: SOP database
            kin_db: Kinetics database
            sim_db: Simulation database
            sf: Scoring function
            klog: Logger
            pert: Perturbator (unused, kept for compatibility)
        """
        # Initialize with empty model list
        super().__init__(
            models=[],
            settings=settings,
            rc_tpls=rc_tpls,
            sop_db=sop_db,
            kin_db=kin_db,
            sim_db=sim_db,
            sf=sf,
            pert=pert,
            klog=klog,
            previous_el={},
            prefix='NMSG'  # Swarm Generation
        )
        # Override models with dynamic pool (consistent name)
        self.models: list[Model | None] = [None] * settings['threads']
        # Override QueueingSystem with updated model count
        self.qs = QueueingSystem(
            settings=self.settings,
            nel=settings['threads'],
            klog=self.klog)

        # Pool-level lock to guard mutations and snapshots
        self.pool_lock = threading.Lock()

        # Track which tables have been created
        self.created_tables: set[str] = set()

        # Lock for table creation
        self.table_creation_lock = threading.Lock()

        # Guards the registration of per-model locks in the inherited
        # self.mdl_locks dict (keyed by (table name, model id), e.g.
        # ('NMSG0003', 2)), since models join the pool from several threads.
        self.el_locks_lock = threading.Lock()

        # Model counter for defragmentation
        self.mdl_count: int = 0

    def add_model(self, mdl: Model) -> None:
        """Add an model to the first available pool slot.

        Args:
            mdl: Model to add

        Returns:
            None
        """

        # Find first available slot
        for idx in range(self.settings['threads']):
            if self.models[idx] is None:
                mdl.thread_id = idx
                self.models[idx] = mdl
                self.klog.debug(
                    f'Model {mdl.id} (Gen {mdl.gen}) added to pool at thread {idx}.')
                break
        if mdl not in self.models:
            raise RuntimeError("Failed to add model to pool")
        # Ensure tables and folders exist
        self._ensure_infrastructure_exists(mdl)

    def remove_model(self, mdl: Model) -> None:
        """Remove an model from the pool and return it.

        Args:
            el: Model to remove

        Returns:
            The removed model
        """
        with self.pool_lock:
            self.models[mdl.thread_id] = None

        self.klog.debug(f'Model {mdl.id} (Gen {mdl.gen}) removed from pool.')
        self.klog.debug(f'Thread {mdl.thread_id} is now available.')

    def _ensure_infrastructure_exists(self, mdl: Model) -> None:
        """Ensure tables and folders exist for model's generation.

        Args:
            mdl: Model whose infrastructure to create
        """
        table_name: str = self.get_table_name(mdl)

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
        gen_folder: str = self.get_gen_folder(mdl)
        if not os.path.exists(gen_folder):
            os.makedirs(gen_folder + '/logs', exist_ok=True)

        # Create subfolder for model (50 models per subfolder)
        subfolder: str = self.get_model_subfolder(mdl)
        if not os.path.exists(subfolder):
            os.makedirs(subfolder + '/logs', exist_ok=True)

            # Symlink necessary files
            for file in mdl.sop.files2copy:
                src: str = f'{self.loc}/{file}'
                dst: str = f'{subfolder}/{file}'
                if os.path.exists(src) and not os.path.exists(dst):
                    os.symlink(src, dst)

    def run(self, mdl: Model) -> Model:
        """Process an model until it reaches DONE status.

        This is the main entry point for NelderMead swarm instances.

        Args:
            mdl: Model to process

        Returns:
            The processed model (status == DONE)
        """
        # Add model to pool with safeguard
        with self.pool_lock:
            if self.models.count(None) == 0:
                raise RuntimeError("No available slots in model pool")
            else:
                self.add_model(mdl)

        # Register this model's lock under the key used by the base class
        # (table name, model id), e.g. ('NMSG0003', 2): the base
        # _process_model_locked releases that same lock in its finally block.
        lock_key: tuple[str, int] = (self.get_table_name(mdl), mdl.id)
        with self.el_locks_lock:
            if lock_key not in self.mdl_locks:
                self.mdl_locks[lock_key] = threading.Lock()

        # Process until done
        while mdl.status != ModelStatus.DONE:
            try:
                self._process_single_model(mdl)
            except Exception as e:
                self.remove_model(mdl)
                self.klog.error(f'Status of model {mdl.id}: {mdl.status}', exc_info=True)
                raise e

        # Remove and return
        self.remove_model(mdl)
        return mdl

    def _process_single_model(self, mdl: Model) -> None:
        """Process one iteration of a single model.

        Args:
            mdl: Model to process
        """
        if mdl.status == ModelStatus.DONE:
            return

        # Try to acquire the model's lock registered in run() (non-blocking)
        if not self.mdl_locks[
                (self.get_table_name(mdl), mdl.id)].acquire(blocking=False):
            return

        # Process model with lock held
        try:
            self._process_model_locked(mdl)
        except Exception as e:
            self.klog.error(f'Error processing model {mdl.id}: {e}', exc_info=True)
            raise e

        # Batch database operations (per model)
        self.sop_db.batch_upsert()
        self.kin_db.batch_upsert()
        self.sim_db.batch_upsert()

        # Collect simulation profiles for this model
        if mdl:
            self.collect_sim_profiles()

        # Run queuing system
        with self.qs_lock:
            self.qs.run()

    def reset_model(self, mdl: Model) -> None:
        self.klog.warning(
            f'Error detected for NelderMead {mdl.id}.',
            'Setting high score to vertice.'
        )
        mdl.status = ModelStatus.DONE

    def collect_sim_profiles(self) -> None:
        """Override: map the profiles read from SIM_DB back to pooled models.

        Same logic as CoreRun.collect_sim_profiles, except that the pool
        (self.models, one slot per thread) is scanned under self.pool_lock
        and its empty slots (None) are skipped. A model matches a DB result
        when it has the same id and its table name (e.g. 'NMSG0003', from
        get_table_name) is the table the result was read from.
        """
        if len(self.sim_db._select) == 0:
            return

        # {table name: {model id: {DB experiment id: profile array}}}
        collecting = self.sim_db.batch_select()

        # Process each table's results
        for table_name, model_profiles in collecting.items():
            for mdl_id, exp_profiles in model_profiles.items():

                # Find the pooled model with matching id and table name
                mdl = None
                with self.pool_lock:
                    for pooled in self.models:
                        if (pooled is not None and
                                pooled.id == mdl_id and
                                self.get_table_name(pooled) == table_name):
                            mdl = pooled
                            break

                if mdl is None:
                    continue  # Model not (or no longer) in the pool

                offset: int = getattr(mdl, '_sim_offset', 0)
                for db_exp_id, db_data in exp_profiles.items():
                    # Map the banded DB experiment_id back to the local index.
                    local: int = db_exp_id - offset
                    # number of timesteps
                    nsteps: int = len(self.get_sim_time_grid(local))

                    # Validate data completeness
                    if len(db_data) != nsteps:
                        continue

                    mdl.sim.profiles[local] = db_data.T[1:]

                # Scoring needs all the profiles
                if all([prof is not None for prof in mdl.sim.profiles]):
                    mdl.status = ModelStatus.SCORING

    @property
    def finished(self) -> bool:
        """Check if all models in pool are done."""
        return all([
            mdl is None or mdl.status == ModelStatus.DONE
            for mdl in self.models
        ])

    @property
    def best_score(self) -> float:
        """Get best score from active models."""
        active_models = [
            mdl for mdl  in self.models if mdl is not None
        ]
        if not active_models:
            return float('inf')
        return min([mdl.score for mdl in active_models])
