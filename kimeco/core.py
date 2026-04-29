from _thread import LockType
import sys
from typing import Any, Optional
import os
import io
import glob
import threading
import json
import numpy as np
import pyarrow.feather as feather
import pyarrow as pa
from numpy.typing import NDArray
from kimeco.enums import ModelStatus
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.rate_coef import RateCo
from kimeco.simulation import SIM
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.model import Model
from kimeco.scoring_f.scoring import Scoring
from kimeco.logger_config import KMOLogger
import time
import concurrent.futures


class CoreRun:

    def __init__(self,
                 models: list[Model],
                 settings: dict[str, Any],
                 rc_tpls: list[list[str]],
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 pert: Optional[Perturbator],
                 klog: KMOLogger,
                 previous_el: dict[int, Model] = {},
                 base_dir: str = '',
                 prefix: str = 'C') -> None:

        self.prefix: str = prefix
        self.klog: KMOLogger = klog
        self.models: list[Model] = models
        self.settings: dict[str, Any] = settings
        self.previous_el: dict[int, Model] = previous_el
        self.pert: Optional[Perturbator] = pert
        self.base_dir: str = base_dir
        # Rate coefficients template
        self.rc_tpls: list[list[str]] = rc_tpls
        self.loc: str = settings['workdir']
        # Scoring function
        self.sf: Scoring = sf
        self._best_score = float('inf')

        self.sop_db: SOP_DB = sop_db
        self.kin_db: KIN_DB = kin_db
        self.sim_db: SIM_DB = sim_db
        self.create_tables()

        self.qs = QueueingSystem(
            settings=self.settings,
            nel=len(self.models),
            klog=self.klog)
        self.clean_files()
        # Contain the time when a sim_id was first queried
        self.requeue_timer = {}

        # Thread-safe locks
        self.mdl_locks: dict[tuple[int, int], LockType] = {
            (mdl.gen, mdl.id): threading.Lock() for mdl in self.models}
        self.qs_lock = threading.Lock()
        self.requeue_lock = threading.Lock()
        self.file_locks = {}

        # Create base directory
        base_path: str = f'{self.loc}/{self.base_dir}'
        os.makedirs(base_path, exist_ok=True)

        # Create folders for each model's generation
        if self.models:
            generations_present = set(mdl.gen for mdl in self.models)

            for gen in generations_present:
                if self.prefix.startswith('X'):
                    gen_name = f'{self.prefix}'
                else:
                    gen_name = f'{self.prefix}{gen:04d}'
                gen_dir = f'{base_path}/{gen_name}'
                os.makedirs(gen_dir + '/logs', exist_ok=True)

                # Get models in this generation
                gen_models = [mdl for mdl in self.models if mdl.gen == gen]
                subfolders_needed = set(
                    mdl.id // 50 for mdl in gen_models
                )

                for subfolder_num in subfolders_needed:
                    subfolder = f'{gen_dir}/{subfolder_num:02d}'
                    os.makedirs(subfolder + '/logs', exist_ok=True)

                    # Copy files necessary for MESS calculation
                    first_mdl = next(
                        mdl for mdl in gen_models
                        if mdl.id // 50 == subfolder_num
                    )
                    for file in first_mdl.sop.files2copy:
                        src = f'{self.loc}/{file}'
                        dst = f'{subfolder}/{file}'
                        if (
                                not os.path.isfile(dst) and
                                os.path.isfile(src)):
                            os.symlink(src, dst)

        # Change to base directory
        os.chdir(base_path)

    def get_table_name(self, mdl: Model) -> str:
        """Get the table name for an model based on its generation.

        Args:
            mdl: Model

        Returns:
            Table name (e.g., 'G0000')
        """
        if self.prefix.startswith('X'):
            return f'{self.prefix}'
        else:
            return f'{self.prefix}{mdl.gen:04d}'

    def get_gen_folder(self, mdl: Model) -> str:
        """Get the generation folder path for an model.

        Args:
            mdl: Model

        Returns:
            Path to generation folder (e.g., 'workdir/base_dir/G0000')
        """
        return f'{self.loc}/{self.base_dir}/{self.get_table_name(mdl)}'

    def get_model_subfolder(self, mdl: Model) -> str:
        """Get the model subfolder path (50 models per subfolder).

        Args:
            mdl: Model

        Returns:
            Path to model subfolder (e.g., 'workdir/base_dir/G0000/01')
        """
        return f'{self.get_gen_folder(mdl)}/{mdl.id//50:02d}'

    def get_sim_time_grid(self, sim_idx: int) -> list[float]:
        return self.settings['experiments'][sim_idx].data[0].tolist()

    def clean_files(self) -> None:
        for mdl in self.models:
            if mdl.status != ModelStatus.DONE:
                table_name: str = self.get_table_name(mdl)
                for file in glob.glob(
                    f"{table_name}{mdl.name}*"
                ):
                    os.remove(file)

    def create_tables(self) -> None:
        """Create the tables in all databases for all model generations.
        """
        if not self.models:
            return

        # Get unique generations from models
        generations: set[int] = set(mdl.gen for mdl in self.models)

        for gen in generations:
            if self.prefix.startswith('X'):
                tbl_name = f'{self.prefix}'
            else:
                tbl_name = f'{self.prefix}{gen:04d}'

            # SOP
            if tbl_name not in self.sop_db.tables:
                self.sop_db.create_new_table(name=tbl_name)

            # KIN
            if tbl_name not in self.kin_db.tables:
                self.kin_db.create_new_table(name=tbl_name)

            # SIM
            if tbl_name not in self.sim_db.tables:
                self.sim_db.create_new_table(name=tbl_name)

    @property
    def finished(self) -> bool:
        return all([mdl.status == ModelStatus.DONE
                    for mdl in self.models])

    def run(self) -> None:
        """Run a generation until all of its models are scored.
        """
        while not self.finished:
            with concurrent.futures.ThreadPoolExecutor(
                    max_workers=self.settings['threads']) as exec:
                futures = []
                for idx, mdl in enumerate(self.models):
                    # Safeguard
                    if self.models[idx].id != mdl.id:
                        raise IndexError(
                            'Incorrect ordering of the models.')
                    if mdl.status == ModelStatus.DONE:
                        continue

                    # Try to acquire lock, skip if busy
                    if not self.mdl_locks[(mdl.gen, mdl.id)].acquire(
                            blocking=False):
                        continue

                    # Submit work with lock held
                    futures.append(
                        exec.submit(self._process_model_locked, mdl))

                # Wait for all futures to complete and check for errors
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        self.klog.error(f'Error processing model: {e}')
                        sys.exit(-1)
            self.sop_db.batch_upsert()
            self.kin_db.batch_upsert()
            self.sim_db.batch_upsert()
            self.collect_sim_profiles()
            with self.qs_lock:
                self.qs.run()

    def _process_model_locked(self, mdl: Model) -> None:
        """Process model with lock already held by caller.
        Lock will be released in finally block.
        """
        try:
            if mdl.status == ModelStatus.RESET:
                self.reset_model(mdl)
            elif mdl.status == ModelStatus.SOP:
                self.calculate_rate_coefficients(mdl)
            elif mdl.status == ModelStatus.KIN:
                self.run_simulation(mdl)
            elif mdl.status == ModelStatus.SIM:
                self.recover_simulation_data(mdl)
            elif mdl.status == ModelStatus.RESCORE:
                self.recalc_score(mdl)
            elif mdl.status == ModelStatus.SCORING:
                self.calc_score(mdl)
            elif mdl.status == ModelStatus.TO_SAVE:
                self.finalize_model(mdl)
        finally:
            self.mdl_locks[(mdl.gen, mdl.id)].release()

    def reset_model(self,
                    mdl: Model) -> None:
        """Reset a failed model."""
        if self.pert is None:
            raise RuntimeError(
                'Cannot reset an model without a perturbator.'
            )

        rst: int = mdl.reset
        table_name: str = self.get_table_name(mdl)

        self.models[mdl.id] = Model(
            sop=self.pert.perturb(sop=self.previous_el[mdl.id].sop),
            id=mdl.id,
            gen=mdl.gen
            )
        for file in glob.glob(f"{table_name}{mdl.name}*"):
            os.remove(file)
        self.models[mdl.id].reset = rst + 1

    def calculate_rate_coefficients(self, mdl: Model) -> None:
        """Calculate rate coefficients for an model."""
        table_name: str = self.get_table_name(mdl)
        if hasattr(mdl, 'thread_id'):
            q_idx: int = mdl.thread_id
        else:
            q_idx = mdl.id
        mdl.rateCoef = RateCo(
            sop=mdl.sop,
            settings=self.settings,
            software_tpls=self.rc_tpls,
            id=mdl.id,
            q_idx=q_idx,
            name=f'{table_name}{mdl.name}',
            loc=self.get_gen_folder(mdl),
            q_sys=self.qs,
            db=self.kin_db,
            klog=self.klog
        )
        mdl.rateCoef.set_status(table=table_name)
        if mdl.rateCoef.status == JobStatus.FINISHED:
            self.klog.debug(
                f'Rate coefficient calc status for model {mdl.id}:' +
                f'{mdl.rateCoef.status.value}')
        if mdl.rateCoef.status == JobStatus.NOT_IN_QUEUE:
            mdl.rateCoef.q_up()
        elif mdl.rateCoef.status == JobStatus.FINISHED:
            mdl.save_kin(db=self.kin_db, table=table_name)

    def run_simulation(self,
                       mdl: Model) -> None:
        """Run the simulation for an model."""
        table_name: str = self.get_table_name(mdl)
        mdl.rateCoef.load_rates_from_db(table=table_name)
        if hasattr(mdl, 'thread_id'):
            q_idx: int = mdl.thread_id
        else:
            q_idx = mdl.id
        mdl.sim = SIM(
            sop=mdl.sop,
            kin=mdl.rateCoef,
            id=mdl.id,
            q_idx=q_idx,
            db=self.sim_db,
            gen_name=table_name,
            loc=self.get_gen_folder(mdl),
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        mdl.sim.q_up()
        mdl.status = ModelStatus.SIM

    def recover_simulation_data(self,
                                mdl: Model) -> None:
        """Recover simulation data for an model."""
        nsim: int = self.settings['n_exp']
        table_name: str = self.get_table_name(mdl)

        # Change status from RUNNING to FINISHED (may have failed)
        mdl.sim.set_status()
        if mdl.sim.status == JobStatus.FINISHED:
            with self.qs_lock:
                self.qs.pickUp(id=mdl.sim.q_idx, jtype='sim')
            mdl.sim.set_status()

        # Reset Model if simulation had an error
        if mdl.sim.status == JobStatus.FAILED:
            mdl.status = ModelStatus.RESET
            return

        # If successful, read JSON files
        if mdl.sim.status == JobStatus.PICKED_UP or\
           mdl.sim.status == JobStatus.NOT_IN_QUEUE:
            if any([prof is None for prof in mdl.sim.profiles]):
                # Read JSON files for each simulation profile
                for sim in range(nsim):
                    if mdl.sim.profiles[sim] is not None:
                        continue  # Already loaded

                    flnm: str = (
                        f'{self.get_model_subfolder(mdl)}'
                        f'/{table_name}{mdl.name}S{sim:02d}.json'
                    )

                    key = (mdl.id, sim)
                    if not os.path.isfile(flnm):
                        # File doesn't exist yet - check if we should requeue
                        with self.requeue_lock:
                            if key not in self.requeue_timer:
                                self.requeue_timer[key] = time.time()
                                continue
                            # Wait maximum 30 sec for file
                            elif (time.time() -
                                  self.requeue_timer[key] < 30.0):
                                continue
                            else:
                                self.requeue_timer[key] = time.time()
                                msg = (f'Missing file: {mdl.name}S{sim:02d}'
                                       '.json - resubmitting')
                                self.klog.info(msg)
                                mdl.sim.q_up()
                                return
                    else:
                        # File exists
                        if os.path.getsize(flnm) == 0:
                            time.sleep(2)

                        # Load data from JSON file
                        with open(flnm, 'r') as f:
                            data: dict[str, list[float]] = json.load(f)

                        # Convert loaded lists to numpy arrays for scoring.
                        mdl.sim.profiles[sim] = np.array(
                            [vals for vals in data.values()]
                        )

                        # Prepare data for database upsert
                        tbl = pa.table(
                            {col: data[col] for col in data}
                        )
                        buf = io.BytesIO()
                        feather.write_feather(tbl, buf)
                        blob = buf.getvalue()
                        self.sim_db.prepare_batch_upsert(
                            table=table_name,
                            mdl_id=mdl.id,
                            experiment_id=sim,
                            result=blob,
                        )

                        # Delete JSON file after successful read
                        os.remove(flnm)
                        if all([prof is not None
                                for prof in mdl.sim.profiles]):
                            mdl.status = ModelStatus.SCORING

    def finalize_model(self,
                       mdl: Model) -> None:
        """Make sure model is saved before changing status."""
        table_name = self.get_table_name(mdl)

        mdl.prepare_upsert(db=self.sop_db, table=table_name)
        mdl.status = ModelStatus.DONE

    def collect_sim_profiles(self) -> None:
        """Batch recovery of concentration profiles from the database.
        This is used primarily for restart scenarios (RESCORE mode) where
        profiles already exist in the database but not as JSON files.
        """
        if len(self.sim_db._select) == 0:
            return

        collecting: dict[str, dict[int, dict[int, NDArray]]] = \
            self.sim_db.batch_select()

        # Process each table's results
        for table_name, model_profiles in collecting.items():
            for mdl_id, exp_profiles in model_profiles.items():

                # Find model with matching ID and generation
                mdl = None
                for model in self.models:
                    if (model.id == mdl_id and
                            self.get_table_name(model) == table_name):
                        mdl = model
                        break

                if mdl is None:
                    continue  # Model not found

                for sim_idx, db_data in exp_profiles.items():
                    # number of timesteps
                    nsteps: int = len(self.get_sim_time_grid(sim_idx))

                    # Validate data completeness
                    if len(db_data) != nsteps:
                        continue

                    mdl.sim.profiles[sim_idx] = db_data.T[1:]

                # Scoring needs all the profiles
                if all([prof is not None for prof in mdl.sim.profiles]):
                    mdl.status = ModelStatus.SCORING

    def recalc_score(self,
                     mdl: Model) -> None:
        """Reload simulated profiles from db, and rescore them.
        Save the new score by overwritting the old one.

        Args:
            mdl (Model): Model
        """
        table_name = self.get_table_name(mdl)
        if hasattr(mdl, 'thread_id'):
            q_idx: int = mdl.thread_id
        else:
            q_idx = mdl.id
        mdl.rateCoef = RateCo(
            sop=mdl.sop,
            settings=self.settings,
            software_tpls=self.rc_tpls,
            id=mdl.id,
            q_idx=q_idx,
            name=f'{table_name}{mdl.name}',
            loc=self.get_gen_folder(mdl),
            q_sys=self.qs,
            db=self.kin_db,
            klog=self.klog
        )
        mdl.sim = SIM(
            sop=mdl.sop,
            kin=mdl.rateCoef,
            id=mdl.id,
            q_idx=q_idx,
            db=self.sim_db,
            gen_name=table_name,
            loc=self.get_gen_folder(mdl),
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        if any([prof is None for prof in mdl.sim.profiles]):
            mdl.request_sim_profiles(sim_db=self.sim_db,
                                     table=table_name)

    def calc_score(self,
                   mdl: Model) -> None:
        """Calculate the score of the model
        using the user requested function.
        If the elif statement for a new scoring function
        is missing, also add the chosen string to
        the implemented_sf list in default_settings.py.

        Args:
            settings (dict[str, Any]): User input + default settings
        """
        try:
            scores: list[float] = self.sf.score(sim=mdl.sim)
            for idx, k in enumerate(mdl.sop.scores):
                mdl.sop.scores[k] = scores[idx]
            mdl.status = ModelStatus.TO_SAVE
        except IndexError as e:
            self.klog.debug(str(e))
            # Occurs when a simulation didn't work so profiles were not saved
            mdl.status = ModelStatus.RESET
            self.klog.info(f'Resetting model {mdl.id}: error during scoring.')

    @property
    def best_score(self) -> float:
        if self._best_score > min(
           [mdl.score for mdl in self.models if mdl is not None]):
            self._best_score: float = min(
                [mdl.score for mdl in self.models if mdl is not None])
        return self._best_score
