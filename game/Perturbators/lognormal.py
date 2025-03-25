from copy import deepcopy

from game.barrier import Barrier
from game.bimolecular import Bimolecular
from game.parameters import SOP
from game.Perturbators.perturbator import Perturbator
from game.well import Well
from numpy import random
import numpy as np
from typing import Any


class LogNormal(Perturbator):
    def __init__(self,
                 settings: dict[str, Any],
                 initial_SOP: SOP) -> None:
        super().__init__(settings=settings,
                         initial_SOP=initial_SOP)
        self.has_boundaries = True
        self.name = 'LogNormal'

    def set_gen_fact(self,
                     gen: int) -> None:
        """Set the generation factor depending on the
        generation number.

        f(gen) = np.exp(-np.power(gen, 0.5)*0.1)

        Args:
            gen (int): number of generation
        """
        self.gen_fact = 1.0

    def perturb(self,
                sop: SOP) -> SOP:
        """Perturb a set of parameters

        Args:
            sop (SOP): SOP object

        Returns:
            SOP: Perturbed SOP
        """
        p_sop: SOP = deepcopy(sop)

        if '__fact' in self.select:
            try_fact = -1
            while try_fact < 0 or\
                not self.within_boundaries(perturbed_val=try_fact,
                                           ptype='fact',
                                           initial_val=self.i_sop.factor):
                # Truncate distribution at 0 to have positive factor
                try_fact: float = p_sop.factor * random.normal(
                    loc=1,
                    scale=self.settings['std_fact']*self.gen_fact)
            p_sop.factor = try_fact

        if '__pow' in self.select:
            try_pow = -1
            while try_pow < 0 or\
                not self.within_boundaries(perturbed_val=try_pow,
                                           ptype='pow',
                                           initial_val=self.i_sop.power):
                # Truncate distribution at 0 to have positive power
                try_pow: float = random.normal(
                    loc=p_sop.power,
                    scale=self.settings['std_pow']*self.gen_fact)
            p_sop.power = try_pow

        for i in range(len(p_sop.sigmas)):
            if f'__sigma_{i}' in self.select:
                try_sig = -1
                while try_sig < 0 or \
                    not self.within_boundaries(
                        perturbed_val=try_sig,
                        ptype='sigma',
                        initial_val=self.i_sop.sigmas[i]):
                    try_sig = random.normal(
                        loc=p_sop.sigmas[i],
                        scale=self.settings['std_sigma']*self.gen_fact)
                p_sop.sigmas[i] = try_sig

        for i in range(len(p_sop.epsilons)):
            if f'__epsi_{i}' in self.select:
                try_eps = -1
                while try_eps < 0 or \
                    not self.within_boundaries(
                        perturbed_val=try_eps,
                        ptype='epsi',
                        initial_val=self.i_sop.epsilons[i]):
                    try_eps = random.normal(
                        loc=p_sop.epsilons[i],
                        scale=self.settings['std_epsi']*self.gen_fact)
                p_sop.epsilons[i] = try_eps

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

        if isinstance(item, (Well, Bimolecular)):
            value: float = self.settings['std_e']
            ptype = 'e'
        elif isinstance(item, Barrier):
            value = self.settings['std_b']
            ptype = 'b'
        else:
            raise TypeError('Unknown item type')

        if f'{item.name}__e' in self.select:
            # Set trial energy out of the boundaries
            try_e: float = self.i_sop.items[item.name].energy\
                - (3*self.settings['max_std']) * value
            while not self.within_boundaries(
                  perturbed_val=try_e,
                  ptype=ptype,
                  initial_val=self.i_sop.items[item.name].energy):
                try_e = random.normal(
                    loc=item.energy,
                    scale=value*self.gen_fact)

            item.energy = try_e

    def perturb_vibrations(self,
                           well: Well) -> None:
        """Perturb the vibrations of a well by a given percentage.
        The percentage is the same for all frequencies.

        Args:
            well (Well) : Well object
        """
        if f'{well.name}__lf_p' in self.select:
            # Set trial low-frequency perturbation out of the boundaries
            try_lf_p = -1

            while try_lf_p < 0 or\
                not self.within_boundaries(
                    perturbed_val=try_lf_p,
                    ptype='lf_p',
                    initial_val=1):
                try_lf_p = random.lognormal(
                    mean=np.log(well.lf_p),
                    sigma=self.settings['std_lf_p']*self.gen_fact)
            well.lf_p = try_lf_p

        if f'{well.name}__hf_p' in self.select:
            # Set trial high-frequency perturbation out of the boundaries
            try_hf_p = -1

            while try_hf_p < 0 or\
                not self.within_boundaries(
                    perturbed_val=try_hf_p,
                    ptype='hf_p',
                    initial_val=1):
                try_hf_p = random.lognormal(
                    mean=np.log(well.hf_p),
                    sigma=self.settings['std_hf_p']*self.gen_fact)
            well.hf_p = try_hf_p

    def perturb_hindered_rotors(self,
                                well: Well) -> None:
        """Perturb all hindered rotors scan by different
        percentage value for each scan. The value is constant within a scan.

        Args:
            well (Well) : Well object
        """

        for num, rot in enumerate(well.rotors):
            if f'{well.name}__hr{num}' in self.select:
                # Set trial rotor perturbation out of the boundaries
                try_r: float = 1 -\
                    (3*self.settings['max_std']) * self.settings['std_hr']
                while not self.within_boundaries(
                      perturbed_val=try_r,
                      ptype='hr',
                      initial_val=1):
                    try_r = random.normal(
                        loc=well.rotors[num].pert,
                        scale=self.settings['std_hr']*self.gen_fact)

                well.rotors[num].pert = try_r

    def perturb_ifreq(self,
                      bar: Barrier) -> None:
        """Perturb the imaginary frequency of a barrier by a given percentage.

        Args:
            bar (Barrier) : Barrier object
        """
        # Doesn't perturb the frequency of barrierless barrier
        if 'nobar' in bar.name:
            return

        if f'{bar.name}__if' in self.select:
            # Set trial imaginary frequency out of the boundaries
            try_if: float = self.i_sop.items[bar.name].ifreq\
                - (3*self.settings['max_std']) * self.settings['std_if']
            while not self.within_boundaries(
                    perturbed_val=try_if,
                    ptype='if',
                    initial_val=self.i_sop.items[bar.name].ifreq):
                try_if = random.lognormal(
                    mean=np.log(bar.ifreq),
                    sigma=self.settings['std_if']*self.gen_fact)

            bar.ifreq = try_if

    def perturb_symmetry_factor(self,
                                bar: Barrier):
        pass
