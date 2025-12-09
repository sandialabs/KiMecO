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


class Extrapolate(CoreRun):

    def __init__(self,
                 elements: list[Element],
                 prefix: str,
                 settings: dict[str, Any],
                 rc_tpl: list[str],
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
                 rc_tpl=rc_tpl,
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

    def run_simulation(self,
                       el: Element) -> None:
        """Overwrite the method to stop the run at this step."""
        el.status = ElementStatus.DONE
