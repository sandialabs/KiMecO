from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any

from kimeco.barrier import Barrier
from kimeco.bimolecular import Bimolecular
from kimeco.parameters import SOP
from kimeco.well import Well


class Perturbator(ABC):
    def __init__(self,
                 settings: dict[str, Any],
                 initial_SOP: SOP
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
        # Factor that starts at 1 and decreases as the number
        # of generations go up.
        self.gen_fact: float = 1.0
        self.has_boundaries = False
        self.additive: list[str] = ['e', 'b', 'pow', 'lf_p', 'hf_p']
        self.percent: list[str] = ['if', 'hr', 'sigma', 'epsi', 'fact']
        self.select: list[str] = self.settings['only_perturb']

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
        std_p: str = 'std_' + ptype
        if ptype in self.additive:
            return [i_val - self.settings[std_p] * self.settings['max_std'],
                    i_val + self.settings[std_p] * self.settings['max_std']]
        elif ptype in self.percent:
            return [i_val - i_val
                    * self.settings[std_p] * self.settings['max_std'],
                    i_val + i_val
                    * self.settings[std_p] * self.settings['max_std']]
        else:
            raise NotImplementedError('Parameter not parametrised.')

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

    @abstractmethod
    def set_gen_fact(self,
                     gen: int) -> None:
        """Set the generation factor depending on the
        generation number.

        Args:
            gen (int): number of generation
        """
        pass

    @abstractmethod
    def perturb(self,
                sop: SOP) -> SOP:
        """Perturb a set of parameters

        Args:
            sop (SOP): SOP object

        Returns:
            SOP: Perturbed SOP
        """
        pass

    @abstractmethod
    def perturb_well(self,
                     well: Well) -> None:
        pass

    @abstractmethod
    def perturb_barrier(self,
                        bar: Barrier) -> None:
        pass

    @abstractmethod
    def perturb_bimolecular(self,
                            bim: Bimolecular) -> None:
        pass

    @abstractmethod
    def perturb_energy(self,
                       item: Well | Bimolecular | Barrier) -> None:
        """Perturb the energy of a Well or Bimolecular object.
        Calculate the perturbation and add it to the energy of the object.

        Args:
            item (Well | Bimolecular): Object to perturb the energy of.
        """
        pass

    @abstractmethod
    def perturb_vibrations(self,
                           well: Well) -> None:
        """Perturb the vibrations of a well by a given percentage.
        The percentage is the same for all frequencies.

        Args:
            well (Well) : Well object
        """
        pass

    @abstractmethod
    def perturb_hindered_rotors(self,
                                well: Well) -> None:
        """Perturb all hindered rotors scan by different
        percentage value for each scan. The value is constant within a scan.

        Args:
            well (Well) : Well object
        """
        pass

    @abstractmethod
    def perturb_ifreq(self,
                      bar: Barrier) -> None:
        """Perturb the imaginary frequency of a barrier by a given percentage.

        Args:
            bar (Barrier) : Barrier object
        """
        pass

    def perturb_symmetry_factor(self,
                                bar: Barrier):
        pass