
from copy import copy, deepcopy
from logging import Logger
from typing import Any

from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.parameters import SOP
from kimeco.enums import FreqMode
from kimeco.well import Well
import numpy as np
from kimeco.enums import Ptype
from kimeco.database.kimeco_db import dbs
from kimeco.enums import Distrib


class Perturbator:
    def __init__(self,
                 settings: dict[str, Any],
                 initial_SOP: SOP,
                 klog: Logger
                 ) -> None:
        """Model class for perturbator.
        Cannot be used directly, but should be inherited

        Args:
            settings (dict[str, Any]): user input
            initial_SOP (SOP): Initial SetOfParameters object
        """
        self.settings: dict[str, Any] = settings
        # Initial set of parameters
        self.i_sop: SOP = deepcopy(initial_SOP)
        self.has_boundaries = True
        self.klog: Logger = klog

        # List of parameters that should never be below 0
        self.zero_bound: set[str] = {
            Ptype.SFC.value,
            Ptype.ETF.value,
            Ptype.ETP.value,
            Ptype.HRS.value,
            Ptype.SIG.value,
            Ptype.EPSI.value,
            Ptype.BFC.value,
            Ptype.IFC.value
        }
        self.additive: set[str] = {
            Ptype.WE.value,
            Ptype.BE.value,
            Ptype.ETP.value,
            Ptype.BFC.value,
            Ptype.IFC.value}
        self.multiplicative: set[str] = {
            Ptype.SFC.value,
            Ptype.MRC.value
            }
        self.percent: set[str] = {
            Ptype.IF.value,
            Ptype.HRS.value,
            Ptype.SIG.value,
            Ptype.EPSI.value,
            Ptype.ETF.value}
        self.select: list[str] = self.settings['only_perturb']
        self.distribs: dict[Ptype, Distrib] = {
            ptype: self.settings[f'distrib_{ptype.value}'] for ptype in Ptype
            if f'distrib_{ptype.value}' in self.settings
        }

    def print_pert_parameters(self) -> None:
        msg = 'Perturbation settings:\n'
        tpl = '\t{param:<20} {un_str:>20} {distrib:>20}\n'
        msg += tpl.format(param='PARAMETERS',
                          un_str='UNCERTAINTIES',
                          distrib='DISTRIBUTIONS')
        for param, un in self.i_sop.uncertainties.items():
            pshort: str = param.split(dbs)[1]
            for ptype in Ptype:
                if ptype.value in pshort:
                    distrib = self.distribs[ptype].value
                    break
            msg += tpl.format(param=param,
                              un_str=f'{un:-.2E}',
                              distrib=distrib)
        self.klog.info(msg)

    def get_boundaries(self,
                       ptype: str,
                       i_val: float) -> list[float]:
        """Get the appropriate boundaries for a given parameter.

        Args:
            ptype (str): type of parameter
            i_val (float): initial value before perturbation

        Raises:
            NotImplementedError: unknown ptype

        Returns:
            list[float]: boundaries [lower, upper]
        """
        bounds: list[float]
        std_p: str = 'std_' + ptype
        if ptype in self.additive:
            bounds = [i_val - self.settings[std_p] * self.settings['max_std'],
                      i_val + self.settings[std_p] * self.settings['max_std']]
        elif ptype in self.percent:
            bounds = [i_val - i_val
                      * self.settings[std_p] * self.settings['max_std'],
                      i_val + i_val
                      * self.settings[std_p] * self.settings['max_std']]
        elif ptype in self.multiplicative:
            bounds = [
                i_val / (self.settings[std_p] * self.settings['max_std']),
                i_val * (self.settings[std_p] * self.settings['max_std'])]
        else:
            raise NotImplementedError('Parameter not parametrised.')
        if ptype in self.zero_bound and min(bounds) < 0:
            bounds[bounds.index(min(bounds))] = 0.0
        return bounds

    def within_boundaries(self,
                          perturbed_val: float,
                          ptype: str,
                          initial_val: float
                          ) -> bool:
        """Check wether a perturbed parameter is within
        the trusted space from the initial value.

        Args:
            perturbed_val (float): trial perturbed value
            ptype (str): type of parameter to obtain the boundaries from
            initial_val (float): value in the initial set of parameter

        Returns:
            bool: Wether or not within boundaries.
        """
        boundaries: list[float] = self.get_boundaries(ptype=ptype,
                                                      i_val=initial_val)
        if perturbed_val > min(boundaries) and\
           perturbed_val < max(boundaries):
            return True
        else:
            return False

    def get_scale(self,
                  ptype: str,
                  param: str) -> float:
        """Get the expected standard deviation.

        Args:
            ptype (str): parameter's type
            param (str): parameter's name

        Returns:
            float: The standard deviation of the parameter.
        """
        uncertainty: float = self.i_sop.uncertainties[param]
        if ptype in self.additive:
            return uncertainty
        elif ptype in self.percent:
            return uncertainty * self.i_sop.parameters_names[param]
        elif ptype in self.multiplicative:
            return uncertainty * self.i_sop.parameters_names[param]
        else:
            raise TypeError('Unknown parameter type in get_scale.')

    def get_mean_sigma(self,
                       ptype: str,
                       param: str,
                       c_val: float,
                       bounds: list[float]) -> tuple[float, float, float]:
        local_c_val: float = copy(c_val)
        scale: float = self.get_scale(ptype, param)
        shift: float = min(bounds)
        local_c_val -= shift
        variance: float = (scale/local_c_val) ** 2
        sigma_squared: float = np.log(1 + variance)
        sigma: float = float(np.sqrt(sigma_squared))
        mean: float = float(np.log(local_c_val) - sigma_squared / 2)
        return mean, sigma, shift

    def get_rng(self,
                ptype: str,
                i_val: float,
                c_val: float,
                param: str,
                distrib: Distrib) -> float:
        """Get a random number for the desired parameter.

        Args:
            ptype (str): Parameter type
            i_val (float): initial value
            c_val (float): current values
            param (str): parameter's name
            distrib (Distrib): Type of distribution to sample

        Returns:
            float: the random number for requested parameter
        """
        if distrib == Distrib.UNIFORM:
            bounds: list[float] = self.get_boundaries(ptype=ptype,
                                                      i_val=i_val)
            return float(np.random.uniform(low=bounds[0], high=bounds[1]))
        elif distrib == Distrib.NORMAL:
            loc: float = c_val
            scale: float = self.get_scale(param=param,
                                          ptype=ptype)
            return float(np.random.normal(loc=loc, scale=scale))
        elif distrib == Distrib.LOGNORMAL:
            # This shift is simply for negative values
            bounds: list[float] = self.get_boundaries(ptype=ptype,
                                                      i_val=i_val)
            mean, sigma, shift = self.get_mean_sigma(
                param=param,
                ptype=ptype,
                c_val=c_val,
                bounds=bounds)
            return float(np.random.lognormal(mean, sigma) + shift)

    def perturb(self,
                sop: SOP) -> SOP:
        """Perturb a set of parameters

        Args:
            sop (SOP): SOP object

        Returns:
            SOP: Perturbed SOP
        """
        p_sop: SOP = deepcopy(sop)

        if dbs+Ptype.ETF.value in self.select:
            try_fact = -1
            while try_fact < 0 or\
                not self.within_boundaries(perturbed_val=try_fact,
                                           ptype=Ptype.ETF.value,
                                           initial_val=self.i_sop.factor):
                # Truncate distribution at 0 to have positive factor
                try_fact: float = self.get_rng(
                    ptype=Ptype.ETF.value,
                    i_val=self.i_sop.factor,
                    c_val=p_sop.factor,
                    param=dbs+Ptype.ETF.value,
                    distrib=self.settings[f'distrib_{Ptype.ETF.value}'])
            p_sop.factor = try_fact

        if dbs+Ptype.ETP.value in self.select:
            try_pow = -1
            while try_pow < 0 or\
                not self.within_boundaries(perturbed_val=try_pow,
                                           ptype=Ptype.ETP.value,
                                           initial_val=self.i_sop.power):
                # Truncate distribution at 0 to have positive power
                try_pow: float = self.get_rng(
                    ptype=Ptype.ETP.value,
                    i_val=self.i_sop.power,
                    c_val=p_sop.power,
                    param=dbs+Ptype.ETP.value,
                    distrib=self.settings[f'distrib_{Ptype.ETP.value}'])
            p_sop.power = try_pow

        for i in range(len(p_sop.sigmas)):
            if f'{dbs}{Ptype.SIG.value}{i}' in self.select:
                try_sig = -1
                while try_sig < 0 or \
                    not self.within_boundaries(
                        perturbed_val=try_sig,
                        ptype=Ptype.SIG.value,
                        initial_val=self.i_sop.sigmas[i]):
                    try_sig: float = self.get_rng(
                        ptype=Ptype.SIG.value,
                        i_val=self.i_sop.sigmas[i],
                        c_val=p_sop.sigmas[i],
                        param=dbs+Ptype.SIG.value,
                        distrib=self.settings[f'distrib_{Ptype.SIG.value}'])
                p_sop.sigmas[i] = try_sig

        for i in range(len(p_sop.epsilons)):
            if f'{dbs}{Ptype.EPSI.value}{i}' in self.select:
                try_eps = -1
                while try_eps < 0 or \
                    not self.within_boundaries(
                        perturbed_val=try_eps,
                        ptype=Ptype.EPSI.value,
                        initial_val=self.i_sop.epsilons[i]):
                    try_eps: float = self.get_rng(
                        ptype=Ptype.EPSI.value,
                        i_val=self.i_sop.epsilons[i],
                        c_val=p_sop.epsilons[i],
                        param=dbs+Ptype.EPSI.value,
                        distrib=self.settings[f'distrib_{Ptype.EPSI.value}'])
                p_sop.epsilons[i] = try_eps

        for well in p_sop.wells:
            self.perturb_well(well)
        for bim in p_sop.bimolecular:
            self.perturb_bimolecular(bim)
        # Barriers must alway be after W and BM
        for bar in p_sop.barriers:
            self.perturb_barrier(bar)

        return p_sop

    def perturb_well(self,
                     well: Well) -> None:
        self.perturb_energy(item=well)
        self.perturb_vibrations(well=well)
        self.perturb_hindered_rotors(well=well)
        self.perturb_multi_rotors(well=well)

    def perturb_barrier(self,
                        bar: Barrier) -> None:
        self.perturb_barrier_energy(bar=bar)
        self.perturb_vibrations(well=bar)
        self.perturb_hindered_rotors(well=bar)
        self.perturb_multi_rotors(well=bar)
        if bar.barrierless:
            self.perturb_symmetry_factor(bar=bar)
        else:
            self.perturb_ifreq(bar=bar)

    def perturb_bimolecular(self,
                            bim: Bimolecular) -> None:
        self.perturb_energy(item=bim)
        for well in bim.fragments:
            self.perturb_vibrations(well=well)
            self.perturb_hindered_rotors(well=well)
            self.perturb_multi_rotors(well=well)

    def perturb_energy(self,
                       item: Well | Bimolecular) -> None:
        """Perturb the energy of a Well or Bimolecular object.
        Calculate the perturbation and add it to the energy of the object.

        Args:
            item (Well | Bimolecular): Object to perturb the energy of.
        """
        param: str = f'{item.name}{dbs}{Ptype.WE.value}'
        if param in self.select:
            # Set trial energy out of the boundaries
            try_e: float = self.i_sop.items[item.name].energy\
                - (3*self.settings['max_std']) * \
                self.settings[f'std_{Ptype.WE.value}']
            while not self.within_boundaries(
                  perturbed_val=try_e,
                  ptype=Ptype.WE.value,
                  initial_val=self.i_sop.items[item.name].energy):
                try_e = self.get_rng(
                    ptype=Ptype.WE.value,
                    i_val=self.i_sop.items[item.name].energy,
                    c_val=item.energy,
                    param=param,
                    distrib=self.settings[f'distrib_{Ptype.WE.value}'])

            item.energy = try_e

    def perturb_barrier_energy(self,
                               bar: Barrier) -> None:
        """Perturb the energy of a Well or Bimolecular object.
        Calculate the perturbation and add it to the energy of the object.

        Args:
            item (Well | Bimolecular): Object to perturb the energy of.
        """
        param: str = f'{bar.name}{dbs}{Ptype.BE.value}'
        if param in self.select:
            # Set trial energy out of the boundaries
            try_e: float = -np.inf
            # The barrier must always be above the energy of both fragments
            while (try_e <= max(
                    bar.connected[0].energy,
                    bar.connected[1].energy) or
                   not self.within_boundaries(
                   perturbed_val=try_e,
                   ptype=Ptype.BE.value,
                   initial_val=self.i_sop.items[bar.name].energy)):
                try_e = self.get_rng(
                    ptype=Ptype.BE.value,
                    i_val=self.i_sop.items[bar.name].energy,
                    c_val=bar.energy,
                    param=param,
                    distrib=self.settings[f'distrib_{Ptype.BE.value}'])

            bar._energy = try_e

    def perturb_vibrations(self,
                           well: Well) -> None:
        """Change the perturbation factors

        Args:
            well (Well) : Well object
        """

        # BATCH perturbation
        if self.settings['freq_mode'] == FreqMode.BATCH:
            param: str = f'{well.name}{dbs}{Ptype.BFC.value}'
            if param in self.select:
                # Set trial low-frequency perturbation out of the boundaries
                try_bfc = -1

                while try_bfc < 0 or\
                    not self.within_boundaries(
                        perturbed_val=try_bfc,
                        ptype=Ptype.BFC.value,
                        initial_val=1):
                    try_bfc = self.get_rng(
                        ptype=Ptype.BFC.value,
                        i_val=self.i_sop.items[well.name].bfc,
                        c_val=well.bfc,
                        param=param,
                        distrib=self.settings[f'distrib_{Ptype.BFC.value}'])
                well.bfc = try_bfc
        # INDIVIDUAL perturbation
        elif self.settings['freq_mode'] == FreqMode.INDIVIDUAL:
            for idx, c_val in enumerate(well.ifc):
                param: str = f'{well.name}{dbs}{Ptype.IFC.value}{idx:02d}'
                if param in self.select:
                    # Set trial frequency perturbation out of the boundaries
                    try_ifc = -1

                    while try_ifc < 0 or\
                        not self.within_boundaries(
                            perturbed_val=try_ifc,
                            ptype=Ptype.IFC.value,
                            initial_val=1):
                        try_ifc: float = self.get_rng(
                            ptype=Ptype.IFC.value,
                            i_val=self.i_sop.items[well.name].ifc[idx],
                            c_val=c_val,
                            param=param,
                            distrib=self.settings[f'distrib_{Ptype.IFC.value}']
                            )
                    well.ifc[idx] = try_ifc
        else:
            raise TypeError('Unknown frequency perturbation mode')

    def perturb_hindered_rotors(self,
                                well: Well) -> None:
        """Perturb all hindered rotors scan by different
        percentage value for each scan. The value is constant within a scan.

        Args:
            well (Well) : Well object
        """

        for num, rot in enumerate(well.h_rotors):
            param: str = f'{well.name}{dbs}{Ptype.HRS.value}{num}'
            if param in self.select:
                # Set trial rotor perturbation out of the boundaries
                try_r: float = 1 -\
                    (3*self.settings['max_std']) *\
                    self.settings[f'std_{Ptype.HRS.value}']
                while not self.within_boundaries(
                      perturbed_val=try_r,
                      ptype=Ptype.HRS.value,
                      initial_val=1):
                    try_r = self.get_rng(
                        ptype=Ptype.HRS.value,
                        i_val=1.0,
                        c_val=rot.pert,
                        param=param,
                        distrib=self.settings[f'distrib_{Ptype.HRS.value}']
                        )

                rot.pert = try_r

    def perturb_multi_rotors(self,
                             well: Well) -> None:
        """Perturb all multi rotors symmetry factor by a different
        percentage.

        Args:
            well (Well) : Well object
        """

        for num, rot in enumerate(well.m_rotors):
            param: str = f'{well.name}{dbs}{Ptype.MRC.value}{num}'
            if param in self.select:
                # Set trial rotor perturbation out of the boundaries
                try_r: float = 1 -\
                    (3*self.settings['max_std']) *\
                    self.settings[f'std_{Ptype.MRC.value}']
                while not self.within_boundaries(
                      perturbed_val=try_r,
                      ptype=Ptype.MRC.value,
                      initial_val=1):
                    try_r = self.get_rng(
                        ptype=Ptype.MRC.value,
                        i_val=1.0,
                        c_val=rot.sfc,
                        param=param,
                        distrib=self.settings[f'distrib_{Ptype.MRC.value}']
                        )

                rot.sfc = try_r

    def perturb_ifreq(self,
                      bar: Barrier) -> None:
        """Perturb the imaginary frequency of a barrier by a given percentage.

        Args:
            bar (Barrier) : Barrier object
        """
        param: str = f'{bar.name}{dbs}{Ptype.IF.value}'
        if param in self.select:
            # Set trial imaginary frequency out of the boundaries
            try_if: float = -1
            while try_if < 0 or not self.within_boundaries(
                    perturbed_val=try_if,
                    ptype=Ptype.IF.value,
                    initial_val=self.i_sop.items[bar.name].ifreq):
                try_if = self.get_rng(
                        ptype=Ptype.IF.value,
                        i_val=self.i_sop.items[bar.name].ifreq,
                        c_val=bar.ifreq,
                        param=param,
                        distrib=self.settings[f'distrib_{Ptype.IF.value}']
                        )

            bar.ifreq = try_if

    def perturb_symmetry_factor(self,
                                bar: Barrier):
        """Perturb the symmetry factor of a barrierless reaction

        Args:
            bar (Barrier): barrierless reaction.
        """
        param: str = f'{bar.name}{dbs}{Ptype.SFC.value}'
        if param in self.select:
            # Set trial symmetry factor out of the boundaries
            try_sfc: float = -1
            while (try_sfc <= 0 or
                   not self.within_boundaries(
                    perturbed_val=try_sfc,
                    ptype=Ptype.SFC.value,
                    initial_val=self.i_sop.items[bar.name].sfc)):
                try_sfc = self.get_rng(
                        ptype=Ptype.SFC.value,
                        i_val=self.i_sop.items[bar.name].sfc,
                        c_val=bar.sfc,
                        param=param,
                        distrib=self.settings[f'distrib_{Ptype.SFC.value}']
                        )

            bar.sfc = try_sfc
