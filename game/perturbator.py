from copy import deepcopy
from game.barrier import Barrier
from game.bimolecular import Bimolecular
from game.parameters import SOP
from game.well import Well
from numpy import random


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
                self.pf = 'normal'
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
        self.perturb_energy(item=well)
        self.perturb_vibrations(well=well)
        self.perturb_hindered_rotors(well=well)

    def perturb_barrier(self,
                        bar: Barrier) -> None:
        self.perturb_energy(item=bar)
        self.perturb_hindered_rotors(well=bar)
        self.perturb_vibrations(well=bar)
        self.perturb_ifreq(bar=bar)

    def perturb_bimolecular(self,
                            bim: Bimolecular) -> None:
        self.perturb_energy(item=bim)
        for well in bim.fragments:
            self.perturb_vibrations(well=well)
            self.perturb_hindered_rotors(well=well)

    def perturb_energy(self,
                       item: Well | Bimolecular | Barrier) -> None:
        """Perturb the energy of a Well or Bimolecular object.
        Calculate the perturbation and add it to the energy of the object.

        Args:
            item (Well | Bimolecular): Object to perturb the energy of.
        """
        perturbation: float

        if isinstance(item, (Well, Bimolecular)):
            value: float = self.settings['pert_e']
        elif isinstance(item, Barrier):
            value = self.settings['pert_b']

        match self.pe:
            case 'uniform':
                perturbation = random.uniform(low=-value,
                                              high=value)
            case 'normal':
                perturbation = random.normal(loc=0,
                                             scale=value)

        item.energy += perturbation

    def perturb_vibrations(self,
                           well: Well) -> None:
        """Perturb the vibrations of a well by a given percentage for all.

        Args:
            well (Well) : Well object
        """
        perturbation = 1.0

        match self.pf:
            case 'uniform':
                perturbation += random.uniform(-self.settings['pert_f'],
                                               self.settings['pert_f'])
            case 'normal':
                perturbation += random.normal(loc=0,
                                              scale=self.settings['pert_f'])

        well.frequencies *= perturbation

    def perturb_hindered_rotors(self,
                                well: Well) -> None:
        """Perturb all hindered rotors scan by different
        percentage value for each scan. The value is constant within a scan.

        Args:
            well (Well) : Well object
        """

        for rot in well.rotors:
            perturbation = 1.0

            match self.pf:
                case 'uniform':
                    perturbation += \
                        random.uniform(-self.settings['pert_hr'],
                                       self.settings['pert_hr'])
                case 'normal':
                    perturbation += \
                        random.normal(loc=0,
                                      scale=self.settings['pert_hr'])

            rot.scan *= perturbation

    def perturb_ifreq(self,
                      bar: Barrier) -> None:
        """Perturb the imaginary frequency of a barrier by a given percentage.

        Args:
            bar (Barrier) : Barrier object
        """
        perturbation = 1.0

        match self.pf:
            case 'uniform':
                perturbation += random.uniform(-self.settings['pert_f'],
                                               self.settings['pert_f'])
            case 'normal':
                perturbation += random.normal(loc=0,
                                              scale=self.settings['pert_f'])

        bar.ifreq *= perturbation
