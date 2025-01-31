from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any

import numpy as np
from game.barrier import Barrier
from game.bimolecular import Bimolecular
from game.parameters import SOP
from game.well import Well


class Perturbator(ABC):
    def __init__(self,
                 settings: dict[str, Any],
                 initial_SOP: SOP
                 ) -> None:
        """_summary_

        Args:
            settings (dict[str, Any]): user input
            initial_SOP (SOP): Initial SetOfParameters object
        """
        self.settings: dict[str, Any] = settings
        # Initial set of parameters
        self.i_sop: SOP = deepcopy(initial_SOP)
        # Factor that starts at 1 and decreases as the number
        # of generations go up.
        self.gen_fact: float
        self.has_boundaries = False

    @abstractmethod
    def set_get_fact(self,
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