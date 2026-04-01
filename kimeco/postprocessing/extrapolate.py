from kimeco.core import CoreRun
from kimeco.element import Element
from kimeco.database.kin_db import KIN_DB
from kimeco.database.sim_db import SIM_DB
from kimeco.database.sop_db import SOP_DB
from kimeco.scoring_f.scoring import Scoring
from kimeco.Perturbators.perturbator import Perturbator
from kimeco.enums import ElementStatus
from typing import Any
from kimeco.logger_config import KMOLogger
from kimeco.simulation import SIM_PP
from kimeco.rate_coef import RateCo


class Extrapolate(CoreRun):

    def __init__(self,
                 elements: list[Element],
                 prefix: str,
                 settings: dict[str, Any],
                 rc_tpls: list[list[str]],
                 sop_db: SOP_DB,
                 kin_db: KIN_DB,
                 sim_db: SIM_DB,
                 sf: Scoring,
                 pert: Perturbator,
                 klog: KMOLogger,
                 previous_el: dict[int, Element] = {},
                 ) -> None:
        super().__init__(
                 elements=elements,
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
                 prefix='X' + prefix)
        # Overwrite pressure and temperature grids for postprocessing
        self.pres: list[float] = settings["pp_pres"]
        self.temp: list[float] = settings["pp_temp"]

    def run_simulation(self,
                       el: Element) -> None:
        """Run a postprocessing Cantera simulation for an element."""
        table_name: str = self.get_table_name(el)
        if hasattr(el, 'thread_id'):
            q_idx: int = el.thread_id
        else:
            q_idx = el.id
        el.sim = SIM_PP(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            q_idx=q_idx,
            db=self.sim_db,
            gen_name=table_name,
            pp_species=self.settings['pp_species'],
            loc=self.get_gen_folder(el),
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        el.sim.q_up()
        el.status = ElementStatus.SIM

    def get_sim_time_grid(self, sim_idx: int) -> list[float]:
        return self.settings['pp_times'][sim_idx]

    def recalc_score(self,
                     el: Element) -> None:
        """Reload postprocessing simulation profiles from the PP DB."""
        table_name = self.get_table_name(el)
        if hasattr(el, 'thread_id'):
            q_idx: int = el.thread_id
        else:
            q_idx = el.id
        el.rateCoef = RateCo(
            sop=el.sop,
            settings=self.settings,
            software_tpls=self.rc_tpls,
            id=el.id,
            q_idx=q_idx,
            name=f'{table_name}{el.name}',
            loc=self.get_gen_folder(el),
            q_sys=self.qs,
            db=self.kin_db,
            klog=self.klog
        )
        el.sim = SIM_PP(
            sop=el.sop,
            kin=el.rateCoef,
            id=el.id,
            q_idx=q_idx,
            db=self.sim_db,
            gen_name=table_name,
            pp_species=self.settings['pp_species'],
            loc=self.get_gen_folder(el),
            q_sys=self.qs,
            set=self.settings,
            klog=self.klog
        )
        if any([prof is None for prof in el.sim.profiles]):
            el.request_sim_profiles(sim_db=self.sim_db,
                                    table=table_name)

    def calc_score(self,
                   el: Element) -> None:
        """Skip scoring in postprocessing and finalize persisted results."""
        el.status = ElementStatus.TO_SAVE
