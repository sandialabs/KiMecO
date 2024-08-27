from copy import deepcopy
from game.barrier import Barrier
from game.bimolecular import Bimolecular
from game.parameters import SOP
from game.well import Well
import random


class Perturbator:
    def __init__(self,
                 ptype: str,
                 settings: dict
                 ) -> None:

        self.settings = settings
        self.setup(ptype)

    def setup(self,
              ptype: str):
        match ptype:
            case _:
                # Distribution of energy perturbation for wells
                self.pe = 'normal'
                # Distribution of energy perturbation for barriers
                self.pb = 'normal'
                # Type of coherence in frequency perturbation
                self.pf = 'uniform'
                # Distribution of percentage perturbation for
                # imaginary frequency
                self.pif = 'normal'
                # Distribution of energy perturbation for hindered rotors
                self.phr = 'normal'
                # Distribution of sampling symmetry factor perturbation
                # for capture rate of barrierless reactions
                self.pbl = 'normal'

    def perturb(self,
                sop: SOP) -> SOP:
        p_sop: SOP = deepcopy(sop)
        for well in p_sop.wells:
            self.perturb_well(well)
        for bar in p_sop.barriers:
            self.perturb_barrier(bar)
        for bim in p_sop.bimolecular:
            self.perturb_bimolecular(bim)

        return p_sop

    def perturb_well(self,
                     well: Well) -> None:
        self.perturb_energy(well)
        self.perturb_vibrations(well)
        self.perturb_hindered_rotors(well)

    def perturb_barrier(self,
                        bar: Barrier) -> None:
        pass

    def perturb_bimolecular(self,
                            bim: Bimolecular) -> None:
        pass

    def perturb_energy(self,
                       item: Well | Bimolecular) -> None:
        
        perturbation: float

        match self.pe:
            case 'normal':
                perturbation = random.uniform(a=-self.settings['pert_e'],
                                              b=self.settings['pert_e'])
        
        item.energy += perturbation
