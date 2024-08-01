from copy import deepcopy
from game.parameters import SOP


class Perturbator:
    def __init__(self,
                 ptype: str
                 ) -> None:

        self.ptype: str = ptype

    def perturb(self,
                sop: SOP) -> SOP:
        p_sop: SOP = deepcopy(sop)
        self.perturb_wells(p_sop)
        self.perturb_barriers(p_sop)

        return p_sop

    def perturb_wells(self,
                      sop: SOP) -> None:
        pass

    def perturb_barriers(self,
                         sop: SOP) -> None:
        pass
