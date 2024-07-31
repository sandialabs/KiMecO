from copy import deepcopy
import cantera as ct
from game.customrate import MessData, MessRate
import numpy as np
from game.bimolecular import Bimolecular
from game.parameters import SOP
from game.rate_constants import RateCon
from game.well import Well
from game.barrier import Barrier
from game.templates.ct_reaction_tpl import reaction_yaml
from scipy.constants import Avogadro


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCon,
                 ct_sim: str,
                 ct_names: dict[str, str],
                 species_sim: None | ct.Solution = None,
                 reac_idx: None | list[int] = None) -> None:
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
        self.species_sim: None | ct.Solution = species_sim
        self.reac_idx: list[int] | None = reac_idx
        self.simulations: list[ct.Solution] = []
        self.ct_names: dict[str, str] = {ct: mess for mess, ct in ct_names.items()}
        self.ct_unitSystem: dict = ct.UnitSystem().units
        self.set_species()
        self.set_reactions()
        self.init_sims()

    def set_species(self) -> None:
        """Create the simulation with all the species,
           including the ones from the workflow.
        """
        if self.species_sim is not None:
            pass
        workflow2mech: list[str] = []
        workflow_species: list[Well] = []
        mech_species: list[str] = [s.name for s in self.initial_sim.species()]
        for specie, obj in self.SOP.items.items():
            if isinstance(obj, Well) and not isinstance(obj, Barrier):
                workflow_species.append(self.SOP.items[specie].ct_name)
        for specie in workflow_species:
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
        self.species_sim: ct.Solution = ct.Solution(thermo="ideal-gas",
                                                    kinetics="gas",
                                                    species=species,
                                                    reactions=reactions)
        
    def create_reaction(self,
                        reac: str) -> [ct.Reaction, ct.Reaction]:
        """Create a custom cantera Reaction object."""
        bar: Barrier = self.SOP.items[reac]
        equations: list[str]
        units: list[str]
        units, equations = self.get_reaction_eq(bar=bar)
        rates_yaml: list[str] = self.get_reaction_rate(bar=bar,
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
        for reac in self.SOP.barriers_names:
            forward, reverse = self.create_reaction(reac=reac)
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
                        bar: Barrier) -> tuple[list[str], list[str]]:
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
        for indx, side in enumerate(bar.connected):
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
        for indx, side in enumerate(reversed(bar.connected)):
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
                          bar: Barrier,
                          units) -> list[str]:
        """Adapt Mess reaction rate to cantera unit system.

        Args:
            bar (Barrier): barrier corresponding to the reactions
            units (_type_): [forward, reverse]

        Returns:
            list[str]: reaction rates[forward, backward]
        """
        From: int = self.KIN.tbl_map[bar.connected[0].name]
        To: int = self.KIN.tbl_map[bar.connected[1].name]
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
                # new_sim.write_yaml(f"{name}.yaml")

    def run(self,
            q_sys: QueueingSystem) -> None:
        q_sys.add_to_queue(self.simulations)
