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
        self.simulations: list[ct.Solution] = []
        self.add_species()
        self.add_reactions()
        self.init_sims()

    def add_species(self) -> None:
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
                new_specie: ct.Species = ct.Species(name=well.ct_name,
                                                    composition=well.compo
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
        new_reactions: list[ct.Reaction] = []
        for reac in self.SOP.barriers_names:
            bar: Barrier = self.SOP.items[reac]
            equation: str = self.get_reaction_eq(bar=bar)
            rates_yaml: str = self.get_reaction_rate(bar=bar)
            p_yaml: str = ''
            for p in self.KIN.set["rc_pres"]:
                p_yaml += f'      - {p} Pa' + '\n'
            t_yaml: str = ''
            for t in self.KIN.set["rc_temp"]:
                t_yaml += f'      - {t} K' + '\n'
            reaction_yaml: str = f"""
    equation: {equation}
    type: Mess-data
    rc:
{rates_yaml[:-1]}
    Pgrid:
{p_yaml[:-1]}
    Tgrid:
{t_yaml[:-1]}
"""
            new_reactions.append(ct.Reaction.from_yaml(reaction_yaml, self.species_sim))
        reactions: list[ct.Reaction] = [r for r in self.species_sim.reactions()]
        reactions.extend(new_reactions)
        species: list[ct.Species] = [s for s in self.species_sim.species()]
        self.final_sim: ct.Solution = ct.Solution(thermo='ideal-gas',
                                                  kinetics='gas',
                                                  species=species,
                                                  reactions=reactions)

    def get_reaction_eq(self, bar: Barrier) -> str:
        equation: str = ""
        for indx, side in enumerate(bar.connected):
            if isinstance(side, Well):
                equation += side.ct_name
            elif isinstance(side, Bimolecular):
                equation += f'{side.fragments[0].ct_name}'
                equation += ' + '
                equation += f'{side.fragments[1].ct_name}'

            if indx == 0:
                equation += ' => '

        return equation

    def get_reaction_rate(self, bar: Barrier) -> str:
        From: int = self.KIN.tbl_map[bar.connected[0].name]
        To: int = self.KIN.tbl_map[bar.connected[1].name]
        rates: np.ndarray = self.KIN.rc[:, :, From, To]
        rates_yaml: str = ''
        for p in rates:
            rates_yaml += '      - '
            for idx, t in enumerate(p):
                if idx == 0:
                    rates_yaml += f'- {t} cm^3/molec/s' + '\n'
                else:
                    rates_yaml += f'        - {t} cm^3/molec/s' + '\n'
        return rates_yaml

    def init_sims(self) -> None:
        ctwriter = ct.YamlWriter()
        reactions: list[ct.Reaction] = [r for r in self.final_sim.reactions()]
        species: list[ct.Species] = [s for s in self.final_sim.species()]
        simid = 0
        for p in self.SOP.rc_pres:
            for t in self.SOP.rc_temp:
                simid += 1
                name: str = f'sim{simid}'
                new_sim: ct.Solution = ct.Solution(name=name,
                                                   thermo='ideal-gas',
                                                   kinetics='gas',
                                                   species=species,
                                                   reactions=reactions)
                new_sim.TP = t, p
                self.simulations.append(new_sim)
                new_sim.write_yaml(f"{name}.yaml")
                ctwriter.add_solution(new_sim)
