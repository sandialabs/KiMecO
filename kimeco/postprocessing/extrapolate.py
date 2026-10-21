from kimeco.core import CoreRun
from kimeco.model import Model
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.enums import ModelStatus
from typing import Any
from kimeco.logger_config import KMOLogger
from kimeco.simulation import SIM
from kimeco.rate_coef import RateCo


class Extrapolate(CoreRun):

    def __init__(self,
                 models: list[Model],
                 prefix: str,
                 settings: dict[str, Any],
                 rc_tpls: list[list[str]],
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 pert: Perturbator,
                 klog: KMOLogger,
                 previous_el: dict[int, Model] = {},
                 ) -> None:
        super().__init__(
                 models=models,
                 settings=settings,
                 rc_tpls=rc_tpls,
                 sop_db=sop_db,
                 kin_db=kin_db,
                 sim_db=sim_db,
                 sf=sf,
                 pert=pert,
                 klog=klog,
                 previous_el=previous_el,
                 base_dir='',
                 prefix=prefix)
        # Overwrite pressure and temperature grids for postprocessing
        self.pres: list[float] = settings["pp_pres"]
        self.temp: list[float] = settings["pp_temp"]

    def reset_model(self,
                    mdl: Model) -> None:
        """Retry a failed postprocessing model in place.

        Extrapolation replays fixed SOPs (nothing to perturb) and merged
        ensembles use non-contiguous ids, so avoid indexing ``self.models``
        or ``self.previous_el`` by id as the base class does.
        """
        mdl.reset += 1
        mdl.status = ModelStatus.SOP

    # run_simulation() is inherited from CoreRun: it must reload the rates
    # from KIN_DB before writing the simulation scripts, because the
    # postprocess reuse branch of calculate_rate_coefficients() leaves
    # rc_by_pes empty.

    def recalc_score(self,
                     mdl: Model) -> None:
        """Reload postprocessing simulation profiles from the PP DB."""
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
        """Skip scoring in postprocessing and finalize persisted results."""
        mdl.status = ModelStatus.TO_SAVE
