import os
from copy import deepcopy
from typing import Any
import cantera as ct
from pandas import DataFrame
from game.cantera.customrate import MessData, MessRate
import numpy as np
from game.bimolecular import Bimolecular
from game.database.game_db import Game_db
from game.parameters import SOP
from game.q_sys import QueueingSystem
from game.rate_constants import RateCo
from game.well import Well
from game.barrier import Barrier
from game.templates.ct_reaction_tpl import reaction_yaml
from game.templates.ct_job import ctjobtpl
from scipy.constants import Avogadro
import pickle


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCo,
                 ct_sim: str,
                 ct_names: dict[str, str],
                 name: str,
                 id: int,
                 db: Game_db,
                 loc: str,
                 q_sys: QueueingSystem,
                 set: dict[str, Any],
                 reac_idx:  list[int] | None = None,
                 species_sim: None | ct.Solution = None) -> None:
        """Cantera simulation object.
        Modify the cantera simulation provided by the user
        depending on the set of parameters and the rate coefficiecients.

        Args:
            sop (SOP): Set Of Parameters objects
            kin (RateCo): Rate Constants object
            ct_sim (str): Path to the YAML file provided by the user
            ct_names (dict[str, str]): Key is name of species in worflow.
                                       Value is name of species in mech file.
            id (str): Base of each simulation's name
            loc (str): In which folder to create the files.
            species_sim (None | ct.Solution, optional):
                Cantera solution object containing the mechanism + WF species.
                Defaults to None.
            reac_idx (None | list[int], optional):
                List of indexes of reactions to replace in the mechanism.
                Defaults to None.
        """

        self.status: list[str] = []
        self.SOP: SOP = sop
        self.KIN: RateCo = kin
        self.initial_sim: ct.Solution = ct.Solution(f"../../{ct_sim}")
        self.species_sim: None | ct.Solution = species_sim
        self.reac_idx: list[int] | None = reac_idx
        self.simulations: list[ct.Solution] = []
        self.ct_names: dict[str, str] = {ct: wf for wf, ct in ct_names.items()}
        self.ct_unitSystem: dict = ct.UnitSystem().units
        # SOP.items is a dictionary.
        # key = name of species (str)
        # Value = The associated object. Can be a Well, Bimolecular or Barrier
        self.species = [
            self.SOP.items[specie].ct_name
            for specie, obj in self.SOP.items.items()
            if isinstance(obj, Well) and not isinstance(obj, Barrier)]
        self.set_species()
        self.set_reactions()
        self.init_sims()
        self.id: int = id
        self.name: str = name
        self.loc: str = loc
        self.q_sys: QueueingSystem = q_sys
        self.ctjobtpl: str = ctjobtpl
        self.set: dict[str, Any] = set
        self.db: Game_db = db
        self.profiles: list[DataFrame] = []

    def set_species(self) -> None:
        """Create the simulation with all the species,
           including the ones from the workflow.
        """
        if self.species_sim is not None:
            return
        workflow2mech: list[str] = []
        mech_species: list[str] = [s.name for s in self.initial_sim.species()]
        for specie in self.species:
            if specie not in mech_species:
                workflow2mech.append(specie)
        self.add_species(workflow2mech=workflow2mech)

    def add_species(self,
                    workflow2mech: list[str]) -> None:
        """Add the missing species from the SOP
        to the cantera Simulation.
        """
        new_species: list[ct.Species] = []
        species: list[ct.Species] = [s for s in self.initial_sim.species()]
        thermo = ct.NasaPoly2(species[0].thermo.min_temp,
                              species[0].thermo.max_temp,
                              species[0].thermo.reference_pressure,
                              species[0].thermo.coeffs)
        for specie in workflow2mech:
            well: Well = self.SOP.items[self.ct_names[specie]]
            new_specie: ct.Species = ct.Species(name=well.ct_name,
                                                composition=well.compo
                                                )
            new_specie.thermo = thermo
            new_species.append(new_specie)
        reactions: list[ct.Reaction] = [r for r in
                                        self.initial_sim.reactions()]
        species.extend(new_species)
        self.species_sim = ct.Solution(thermo="ideal-gas",
                                       kinetics="gas",
                                       species=species,
                                       reactions=reactions)

    def create_reaction(self,
                        reactant: Well | Bimolecular,
                        product: Well | Bimolecular) -> list[ct.Reaction]:
        """Create a custom cantera Reaction object."""

        equations: list[str]
        units: list[str]
        units, equations = self.get_reaction_eq(reactant=reactant,
                                                product=product)
        rates_yaml: list[str] = self.get_reaction_rate(reactant=reactant,
                                                       product=product,
                                                       units=units)
        p_yaml: str = ''
        for p in self.KIN.set["rc_pres"]:
            p_yaml += f'  - {p} torr' + '\n'
        t_yaml: str = ''
        for t in self.KIN.set["rc_temp"]:
            t_yaml += f'  - {t} K' + '\n'
        forward_yaml: str = reaction_yaml.format(equation=equations[0],
                                                 rates_yaml=rates_yaml[0][:-1],
                                                 p_yaml=p_yaml[:-1],
                                                 t_yaml=t_yaml[:-1])
        forward = ct.Reaction.from_yaml(forward_yaml, self.species_sim)
        reverse_yaml: str = reaction_yaml.format(equation=equations[1],
                                                 rates_yaml=rates_yaml[1][:-1],
                                                 p_yaml=p_yaml[:-1],
                                                 t_yaml=t_yaml[:-1])
        reverse = ct.Reaction.from_yaml(reverse_yaml, self.species_sim)

        return [forward, reverse]

    def set_reactions(self) -> None:
        """Replace mechanism reactions by workflow reactions.
        """
        new_reactions: list[ct.Reaction] = []
        for idx, reactant in enumerate(self.SOP.wells[:-1]):
            for product in self.SOP.wells[idx+1:]:
                forward, reverse = self.create_reaction(reactant=reactant,
                                                        product=product)
                new_reactions.append(forward)
                new_reactions.append(reverse)
        for reactant in self.SOP.wells:
            for product in self.SOP.bimolecular:
                forward, reverse = self.create_reaction(reactant=reactant,
                                                        product=product)
                new_reactions.append(forward)
                new_reactions.append(reverse)
        reactions: list[ct.Reaction] = \
            [r for r in self.species_sim.reactions()]
        self.remove_redundant_reactions(reactions=reactions,
                                        new_reactions=new_reactions)
        reactions.extend(new_reactions)
        species: list[ct.Species] = [s for s in self.species_sim.species()]
        self.final_sim: ct.Solution = ct.Solution(thermo='ideal-gas',
                                                  kinetics='gas',
                                                  species=species,
                                                  reactions=reactions)

    def remove_redundant_reactions(self,
                                   new_reactions: list[ct.Reaction],
                                   reactions: list[ct.Reaction]
                                   ) -> None:
        """Remove from the mechanism the reactions
           redundant with the workflow.

        Args:
            reactions (list[ct.Reaction]): mechanism reactions
        """
        if self.reac_idx is None:
            self.reac_idx: list[int] = []
            for idx, reac in enumerate(reactions):
                for new_reac in new_reactions:
                    if reac.reactants == new_reac.reactants and\
                       reac.products == new_reac.products:
                        self.reac_idx.append(idx)

        for idx in reversed(self.reac_idx):
            reactions.pop(idx)

    def get_reaction_eq(self,
                        reactant: Well | Bimolecular,
                        product: Well | Bimolecular) -> tuple[list[str], list[str]]:
        """Create the reation's equations (forward and reverse) and find
        appropriate units for the rate coefficient.

        Args:
            bar (Barrier): Barrier object corresponding to the reaction.

        Returns:
            tuple[list[str], list[str]]: units[forward, reverse]
                                         equations[f,r]
        """
        forwrd: str = ""
        units = []
        for indx, side in enumerate([reactant, product]):
            if isinstance(side, Well):
                forwrd += side.ct_name
            elif isinstance(side, Bimolecular):
                forwrd += f'{side.fragments[0].ct_name}'
                forwrd += ' + '
                forwrd += f'{side.fragments[1].ct_name}'

            if indx == 0:
                if '+' in forwrd:
                    units.append("m^3/s/kmol")
                else:
                    units.append("s^-1")
                forwrd += ' => '

        reverse: str = ""
        for indx, side in enumerate([product, reactant]):
            if isinstance(side, Well):
                reverse += side.ct_name
            elif isinstance(side, Bimolecular):
                reverse += f'{side.fragments[0].ct_name}'
                reverse += ' + '
                reverse += f'{side.fragments[1].ct_name}'

            if indx == 0:
                if '+' in reverse:
                    units.append("m^3 / s / kmol")
                else:
                    units.append("s^-1")
                reverse += ' => '

        return (units, [forwrd, reverse])

    def get_reaction_rate(self,
                          reactant: Well | Bimolecular,
                          product: Well | Bimolecular,
                          units) -> list[str]:
        """Adapt Mess reaction rate to cantera unit system.

        Args:
            bar (Barrier): barrier corresponding to the reactions
            units (_type_): [forward, reverse]

        Returns:
            list[str]: reaction rates[forward, backward]
        """
        From: int = self.KIN.tbl_map[reactant.name]
        To: int = self.KIN.tbl_map[product.name]
        f_rates: np.ndarray = deepcopy(self.KIN.rc[:, :, From, To])
        r_rates: np.ndarray = deepcopy(self.KIN.rc[:, :, To, From])
        if 'm^3' in units[0]:
            f_rates *= Avogadro / 1000
        if 'm^3' in units[1]:
            r_rates *= Avogadro / 1000
        f_rates_yaml: str = ''
        r_rates_yaml: str = ''

        for pindex in range(len(self.KIN.set["rc_pres"])):
            for tindex in range(len(self.KIN.set["rc_temp"])):
                f_rates_yaml += f'rc_{pindex}_{tindex}: \
                                {f_rates[pindex,tindex]}' + '\n'
                r_rates_yaml += f'rc_{pindex}_{tindex}: \
                                {r_rates[pindex,tindex]}' + '\n'
        return [f_rates_yaml, r_rates_yaml]

    def get_std_unit(self,
                     unit: str) -> str:
        """Change any unit into Cantera standard system of units.

        Args:
            unit (str): any unit

        Returns:
            str: string of the standard unit
        """
        std_unit: str = ''
        full_dim: dict = ct.Units(unit).dimensions
        for dim, exp in full_dim.items():
            if exp != 0.0:
                std_unit += f' {self.ct_unitSystem[dim]}^{exp} *'
        std_unit: str = std_unit[1:-2]

        return std_unit

    def init_sims(self) -> None:
        """A simulation is created for each PT combination.
        Loops through P first and then T to create sim index.
        """
        reactions: list[ct.Reaction] = [r for r in self.final_sim.reactions()]
        species: list[ct.Species] = [s for s in self.final_sim.species()]
        simid = 0
        for p in self.SOP.rc_pres:
            for t in self.SOP.rc_temp:
                simid += 1
                name: str = f'sim{simid}'
                new_sim = ct.Solution(name=name,
                                        thermo='ideal-gas',
                                        kinetics='gas',
                                        species=species,
                                        reactions=reactions)
                new_sim.TP = t, p
                self.simulations.append(new_sim)

    def q_up(self) -> None:
        
        cpu: int = self.set['cpu_sim']
        mem: int = self.set['mem_sim']
        for i, sim in enumerate(self.simulations):
            self.set_status(i)
            self.serialize(sim=sim,
                           name=self.name+f'S{i}')
            self.q_sys.add_to_q(name=self.name+f'S{i}',
                                idx=self.id*len(self.simulations)+i,
                                location=self.loc,
                                jtype='sim',
                                ressources=(cpu, mem))

    def serialize(self,
                  sim: ct.Solution,
                  name: str) -> None:
        ct_job: str = self.ctjobtpl.format(db_name=self.db.name,
                                           sim_id=name,
                                           to_watch=self.species,
                                           sim_time=self.set['sim_time'],
                                           tstep=self.set['sim_tstep'])
        with open(f'{self.loc}/{name}.py', 'w') as f:
            f.write(ct_job)
        with open(f'{self.loc}/{name}.pkl', 'wb') as pkl_file:
            pickle.dump(sim, pkl_file)

    def set_status(self,
                   sim: int) -> None:

        if len(self.status) < sim + 1:
            self.status.append('notInQueue')

        status: str = self.q_sys.status(
            id=self.id*len(self.simulations)+sim,
            jtype='sim')
        if status == 'notInQueue':
            if False:  # self.data_in_db(sim):
                self.status[sim] = 'finished'
            else:
                self.status[sim] = status
        else:
            self.status[sim] = status

    def recover_results(self,
                        sim: int) -> None:
        for sim in range(len(self.simulations)):
            name = self.name+f'S{sim}'
            self.profiles.append(
                self.db.get_sim_data(index=name)
            )
        print(self.profiles)
