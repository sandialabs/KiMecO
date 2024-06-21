from copy import deepcopy
from typing import Any
import cantera as ct
from game.customrate import MessData, MessRate
import numpy as np
from game.bimolecular import Bimolecular
from game.parameters import SOP
from game.rate_constants import RateCon
from game.well import Well
from game.barrier import Barrier


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCon,
                 ct_sim: str) -> None:
        """Cantera simulation object.
        Modify the cantera simulation provided by the user
        depending on the set of parameters and the rate coefficiecients.

        Args:
            sop (SOP): Set Of Parameters objects
            kin (RateCon): Rate Constants object
            ct_sim (str): Path to the YAML file provided by the user
        """
        self.SOP: SOP = sop
        self.KIN: RateCon = kin
        self.initial_sim: ct.Solution = ct.Solution(ct_sim)
        new_species = self.add_species()
        new_reactions = self.add_reactions()
        self.complete_sim(new_species, new_reactions)
        self.init_sims()
        self.simulations: list[ct.Solution] = []

    def complete_sim(self, new_species: list[ct.Species],
                     new_reactions: list[ct.Reaction]
                     ) -> None:
        species: list[ct.Species] = [s for s in self.initial_sim.species()]
        reactions: list[ct.Reaction] = [r for r in self.initial_sim.reactions()]
        all_species: list[ct.Species] = species.extend(new_species)
        all_reactions: list[ct.Reaction] = reactions.extend(reactions)
        self.modified_sim: ct.Solution = ct.Solution(thermo='ideal-gas',
                                                     kinetics='gas',
                                                     species=all_species,
                                                     reactions=all_reactions)


    def add_species(self) -> list[ct.Species]:
        """Add the species from the SOP
        to the cantera Simulation.
        """
        new_species: list[ct.Species] = []
        species: list[ct.Species] = [s for s in self.initial_sim.species()]
        thermo = ct.NasaPoly2(species[0].thermo.min_temp,
                              species[0].thermo.max_temp,
                              species[0].thermo.reference_pressure,
                              species[0].thermo.coeffs)
        for specie, obj in self.SOP.items.items():
            if isinstance(obj, Well) and not isinstance(obj, Barrier):
                well: Well = self.SOP.items[specie]
                new_specie = ct.Species(name=specie,
                                             composition=well.compo,
                                             )
                new_specie.thermo = thermo
                new_species.append(new_specie)
        reactions: list[ct.Reaction] = [r for r in self.initial_sim.reactions()]
        species.extend(new_species)
        self.species_sim: ct.Solution = ct.Solution(thermo="ideal-gas",
                                                    kinetics="gas",
                                                    species=species,
                                                    reactions=reactions)

    def add_reactions(self) -> list[ct.Reaction]:
        reactions: list[ct.Reaction] = []
        for reac in self.SOP.barriers_names:
            bar: Barrier = self.SOP.items[reac]
            equation: str = self.get_reaction_eq(bar=bar)
            rates: list = self.get_reaction_rate(bar=bar).tolist()
            reaction_yaml: str = f"""
    equation: {equation}
    type: Mess-data
    units: {{length: cm, quantity: molec, pressure: Pa}}
    rc: {rates}
    Pgrid: {self.KIN.set["rc_pres"]}
    Tgrid: {self.KIN.set["rc_temp"]}
    """
            reactions.append(ct.Reaction.from_yaml(reaction_yaml, self.initial_sim))
        return reactions

    def get_reaction_eq(self, bar: Barrier) -> str:
        equation: str = ""
        for indx, side in enumerate(bar.connected):
            if isinstance(side, Well):
                equation += side.name
            elif isinstance(side, Bimolecular):
                equation += f'{side.fragments[0].name}'
                equation += ' + '
                equation += f'{side.fragments[1].name}'

            if indx == 0:
                equation += ' <=> '

        return equation

    def get_reaction_rate(self, bar: Barrier) -> np.ndarray:
        From: int = self.KIN.tbl_map[bar.connected[0].name]
        To: int = self.KIN.tbl_map[bar.connected[1].name]
        rates: np.ndarray = self.KIN.rc[:, :, From, To]

        return rates

    def init_sims(self) -> None:
        for p in self.SOP.rc_pres:
            for t in self.SOP.rc_temp:
                new_sim: ct.Solution = deepcopy(self.modified_sim)
                new_sim.PT = p, t
                self.simulations.append(new_sim)
