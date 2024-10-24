from copy import deepcopy
from typing import Any
from game.barrier import Barrier
from game.bimolecular import Bimolecular
from game.parameters import SOP
from game.well import Well
from numpy import random


class Perturbator:
    def __init__(self,
                 ptype: str,
                 settings: dict[str, Any]
                 ) -> None:

        self.settings: dict[str, Any] = settings
        # Distribution for energy transfert parameters
        self.et: str
        # Distribution for Lenerd-Jones parameters
        self.lj: str
        # Distribution of energy perturbation for wells
        self.pe: str
        # Distribution of energy perturbation for barriers
        self.pb: str
        # Type of coherence in frequency perturbation
        self.pf: str
        # Distribution of percentage perturbation for
        # imaginary frequency
        self.pif: str
        # Distribution of energy perturbation for hindered rotors
        self.phr: str
        # Distribution of sampling symmetry factor perturbation
        # for capture rate of barrierless reactions
        self.pbl: str
        self.ptype: str = ptype
        self.setup(ptype)

    def setup(self,
              ptype: str) -> None:
        if ptype == 'nominal':
            self.et = 'init'
            self.lj = 'init'
            self.pe = 'init'
            self.pb = 'init'
            self.pf = 'init'
            self.pif = 'init'
            self.phr = 'init'
            self.pbl = 'init'
        else:
            self.et = 'normal'
            self.lj = 'normal'
            self.pe = 'normal'
            self.pb = 'normal'
            self.pf = 'normal'
            self.pif = 'normal'
            self.phr = 'normal'
            self.pbl = 'normal'

    def perturb(self,
                sop: SOP) -> SOP:
        """Perturb a set of parameters

        Args:
            sop (SOP): SOP object

        Returns:
            SOP: Perturbed SOP
        """
        p_sop: SOP = deepcopy(sop)

        if self.et == 'init':
            pass
        else:
            p_sop.factor *= 1 + random.normal(loc=0,
                                              scale=self.settings['pert_etf'])
            p_sop.power *= 1 + random.normal(loc=0,
                                             scale=self.settings['pert_ete'])
        if self.lj == 'init':
            pass
        else:
            p_sop.sigmas *= 1 + random.normal(
                loc=0,
                scale=self.settings['pert_sigma'])
            p_sop.epsilons *= 1 + random.normal(
                loc=0,
                scale=self.settings['pert_epsi'])

        if self.ptype != 'nominal':
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
        self.perturb_vibrations(well=bar)
        self.perturb_hindered_rotors(well=bar)
        self.perturb_ifreq(bar=bar)
        if bar.barrierless:
            self.perturb_symmetry_factor(bar=bar)

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
        """Perturb the vibrations of a well by a given percentage.
        The percentage is the same for all frequencies.

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

        for num, rot in enumerate(well.rotors):
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
            well.rotors_pert[num] = perturbation

    def perturb_ifreq(self,
                      bar: Barrier) -> None:
        """Perturb the imaginary frequency of a barrier by a given percentage.

        Args:
            bar (Barrier) : Barrier object
        """
        perturbation = 1.0

        #Doesn't perturb the frequency of barrierless barrier
        if 'nobar' in bar.name:
            return
        match self.pf:
            case 'uniform':
                perturbation += random.uniform(-self.settings['pert_if'],
                                               self.settings['pert_if'])
            case 'normal':
                perturbation += random.normal(loc=0,
                                              scale=self.settings['pert_if'])

        bar.ifreq *= perturbation

    def perturb_symmetry_factor(self,
                                bar: Barrier):
        pass