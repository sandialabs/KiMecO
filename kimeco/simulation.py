# from copy import deepcopy
from typing import Any
import cantera as ct
from numpy.typing import NDArray
# from kimeco.cantera.customrate import MessData, MessRate
# import numpy as np
# from kimeco.bimolecular import Bimolecular
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.rate_coef import RateCo
# from kimeco.well import Well
# from kimeco.templates.ct_reaction_tpl import reaction_yaml
# from kimeco.templates.ct_job import ctjobtpl
from kimeco.templates.sim_arr_tpl import ctjobtpl
from logging import Logger
import pickle


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCo,
                 id: int,
                 gen_name: str,
                 species: list[str],
                 sc_species: list[str],
                 db: SIM_DB,
                 loc: str,
                 q_sys: QueueingSystem,
                 set: dict[str, Any],
                 klog: Logger  # ,
                 #  reac_idx:  list[int] | None = None,
                 #  species_sim: None | ct.Solution = None
                 ) -> None:
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

        Args:
            sop (SOP): Set Of Parameters objects
            kin (RateCo): Rate Constants object
            ct_sim (str): Path to the YAML file provided by the user
            ct_names (dict[str, str]): Key is name of species in worflow.
                                       Value is name of species in mech file.
            name (str): name of the simulation object
            id (int):
                Identifier of the simulation object.
                Used to calculate the identifier of individual sim(P,T).
            db (Kimeco_db): Kimeco SIM DB
            loc (str): Where the files will be generated
            q_sys (QueueingSystem): Kimeco Queuing system.
            set (dict[str, Any]): Settings (JSON input file)
            reac_idx (list[int] | None, optional):
                Indexes of the reactions to change in the mechanism file.
                Defaults to None.
            species_sim (None | ct.Solution, optional):
                Cantera object where the worflow species and
                mechanism species are already combined.
                Defaults to None.
        """
        self.klog: Logger = klog
        self.status: list[JobStatus] = [
            JobStatus.NOT_IN_QUEUE]\
            * len(set['rc_pres'])\
            * len(set['rc_temp'])
        self.gen_name: str = gen_name
        self.SOP: SOP = sop
        self.KIN: RateCo = kin
        self.id: int = id
        self.initial_sim: ct.Solution = ct.Solution(f"../../{set['ct_yaml']}")
        # self.species_sim: None | ct.Solution = species_sim
        # self.reac_idx: list[int] | None = reac_idx
        self.simulations: list[ct.Solution] = []
        # ct is the name in cantera and wf is name in worflow
        self.ct_names: dict[str, str] = {
            ct: wf for wf, ct in set['ct_names'].items()}
        self.ct_unitSystem: dict = ct.UnitSystem().units
        self.settings: dict[str, Any] = set
        # Species to be in the mechanism
        self.species: list[str] = species
        # Species to save in db
        self.sv_species: list[str] = sc_species
        # Species to used in scoring
        self.sc_species: list[str] = sc_species
        # self.set_species()
        # self.set_reactions()
        # self.init_sims()
        self.el_name: str = f'E{id:04d}'
        self.name: str = f'{gen_name}{self.el_name}S'
        self.loc: str = loc + f'/{(self.id)//50:02d}'
        self.q_sys: QueueingSystem = q_sys
        self.ctjobtpl: str = ctjobtpl
        self.db: SIM_DB = db
        self.profiles: list[NDArray | None] = [
            None for i in range(len(set['rc_pres']) * len(set['rc_temp']))]

    # def set_species(self) -> None:
    #     """Create the simulation with all the species,
    #        including the ones from the workflow.
    #     """
    #     if self.species_sim is not None:
    #         return
    #     workflow2mech: list[str] = []
    #     mech_species: list[str] = [s.name for s in self.initial_sim.species()]
    #     for specie in self.species:
    #         if specie not in mech_species:
    #             workflow2mech.append(specie)
    #     self.add_species(workflow2mech=workflow2mech)

    # def add_species(self,
    #                 workflow2mech: list[str]) -> None:
    #     """Add the missing species from the SOP
    #     to the cantera Simulation.
    #     """
    #     msg: str = 'Species added to the mechanism:\n'
    #     msg += f'{workflow2mech}'
    #     self.klog.debug(msg)
    #     new_species: list[ct.Species] = []
    #     species: list[ct.Species] = [s for s in self.initial_sim.species()]
    #     thermo = ct.NasaPoly2(species[0].thermo.min_temp,
    #                           species[0].thermo.max_temp,
    #                           species[0].thermo.reference_pressure,
    #                           species[0].thermo.coeffs)
    #     for specie in workflow2mech:
    #         well: Well = self.SOP.items[self.ct_names[specie]]
    #         new_specie: ct.Species = ct.Species(name=well.ct_name,
    #                                             composition=well.compo
    #                                             )
    #         new_specie.thermo = thermo
    #         new_species.append(new_specie)
    #     reactions: list[ct.Reaction] = [r for r in
    #                                     self.initial_sim.reactions()]
    #     species.extend(new_species)
    #     self.species_sim = ct.Solution(thermo="ideal-gas",
    #                                    kinetics="gas",
    #                                    species=species,
    #                                    reactions=reactions)

    # def create_reaction(self,
    #                     reactant: Well | Bimolecular,
    #                     product: Well | Bimolecular) -> list[ct.Reaction]:
    #     """Create a custom cantera Reaction object."""

    #     equations: list[str]
    #     units: list[str]
    #     units, equations = self.get_reaction_eq(reactant=reactant,
    #                                             product=product)
    #     rates_yaml: list[str] = self.get_reaction_rate(reactant=reactant,
    #                                                    product=product,
    #                                                    units=units)
    #     p_yaml: str = ''
    #     for p in self.settings["rc_pres"]:
    #         p_yaml += f'  - {round(p, 5)} {self.settings["pres_unit"]}' + '\n'
    #     t_yaml: str = ''
    #     for t in self.KIN.set["rc_temp"]:
    #         t_yaml += f'  - {round(t, 5)} K' + '\n'
    #     forward_yaml: str = reaction_yaml.format(equation=equations[0],
    #                                              rates_yaml=rates_yaml[0][:-1],
    #                                              p_yaml=p_yaml[:-1],
    #                                              t_yaml=t_yaml[:-1])
    #     forward = ct.Reaction.from_yaml(forward_yaml, self.species_sim)
    #     reverse_yaml: str = reaction_yaml.format(equation=equations[1],
    #                                              rates_yaml=rates_yaml[1][:-1],
    #                                              p_yaml=p_yaml[:-1],
    #                                              t_yaml=t_yaml[:-1])
    #     reverse = ct.Reaction.from_yaml(reverse_yaml, self.species_sim)

    #     return [forward, reverse]

    # def set_reactions(self) -> None:
    #     """Replace mechanism reactions by workflow reactions.
    #     """
    #     new_reactions: list[ct.Reaction] = []
    #     # Create well to well reactions
    #     for idx, reactant in enumerate(self.SOP.wells[:-1]):
    #         for product in self.SOP.wells[idx+1:]:
    #             forward, reverse = self.create_reaction(reactant=reactant,
    #                                                     product=product)
    #             new_reactions.append(forward)
    #             new_reactions.append(reverse)
    #     # Create well to bimolecular reactions
    #     for reactant in self.SOP.wells:
    #         for product in self.SOP.bimolecular:
    #             forward, reverse = self.create_reaction(reactant=reactant,
    #                                                     product=product)
    #             new_reactions.append(forward)
    #             new_reactions.append(reverse)
    #     # Create bimolecular to bimolecular reactions
    #     for idx, reactant in enumerate(self.SOP.bimolecular[:-1]):
    #         for product in self.SOP.bimolecular[idx+1:]:
    #             forward, reverse = self.create_reaction(reactant=reactant,
    #                                                     product=product)
    #             new_reactions.append(forward)
    #             new_reactions.append(reverse)
    #     if self.id == 0:
    #         msg = \
    #             'The k(T,P) of the following reactions will be updated:' + '\n'
    #         for reac in new_reactions:
    #             msg += f'{reac}' + '\n'
    #         self.klog.info(msg)
    #     reactions: list[ct.Reaction] = \
    #         [r for r in self.species_sim.reactions()]
    #     self.remove_redundant_reactions(reactions=reactions,
    #                                     new_reactions=new_reactions)
    #     reactions.extend(new_reactions)
    #     species: list[ct.Species] = [s for s in self.species_sim.species()]
    #     self.final_sim: ct.Solution = ct.Solution(thermo='ideal-gas',
    #                                               kinetics='gas',
    #                                               species=species,
    #                                               reactions=reactions)

    # def remove_redundant_reactions(self,
    #                                new_reactions: list[ct.Reaction],
    #                                reactions: list[ct.Reaction]
    #                                ) -> None:
    #     """Remove from the mechanism the reactions
    #        redundant with the workflow.

    #     Args:
    #         reactions (list[ct.Reaction]): mechanism reactions
    #     """
    #     if self.reac_idx is None:
    #         self.reac_idx: list[int] = []
    #         reac_log = ''
    #         for idx, reac in enumerate(reactions):
    #             for new_reac in new_reactions:
    #                 if reac.reactants == new_reac.reactants and\
    #                    reac.products == new_reac.products:
    #                     self.reac_idx.append(idx)
    #                     reac_log += f'{reac}' + '\n'
    #         if self.id == 0:
    #             msg: str = \
    #                 'Redundant reactions removed from kinetic mechanism:\n'
    #             msg += f'{self.reac_idx}:' + '\n' + reac_log
    #             self.klog.info(msg)

    #     for idx in reversed(self.reac_idx):
    #         reactions.pop(idx)

    # def get_reaction_eq(self,
    #                     reactant: Well | Bimolecular,
    #                     product: Well | Bimolecular
    #                     ) -> tuple[list[str], list[str]]:
    #     """Create the reation's equations (forward and reverse) and find
    #     appropriate units for the rate coefficient.

    #     Args:
    #         bar (Barrier): Barrier object corresponding to the reaction.

    #     Returns:
    #         tuple[list[str], list[str]]: units[forward, reverse]
    #                                      equations[f,r]
    #     """
    #     forwrd: str = ""
    #     units = []
    #     for indx, side in enumerate([reactant, product]):
    #         if isinstance(side, Well):
    #             forwrd += side.ct_name
    #         elif isinstance(side, Bimolecular):
    #             forwrd += f'{side.fragments[0].ct_name}'
    #             forwrd += ' + '
    #             forwrd += f'{side.fragments[1].ct_name}'

    #         if indx == 0:
    #             if '+' in forwrd:
    #                 units.append("m^3/s/kmol")
    #             else:
    #                 units.append("s^-1")
    #             forwrd += ' => '

    #     reverse: str = ""
    #     for indx, side in enumerate([product, reactant]):
    #         if isinstance(side, Well):
    #             reverse += side.ct_name
    #         elif isinstance(side, Bimolecular):
    #             reverse += f'{side.fragments[0].ct_name}'
    #             reverse += ' + '
    #             reverse += f'{side.fragments[1].ct_name}'

    #         if indx == 0:
    #             if '+' in reverse:
    #                 units.append("m^3 / s / kmol")
    #             else:
    #                 units.append("s^-1")
    #             reverse += ' => '

    #     return (units, [forwrd, reverse])

    # def get_reaction_rate(self,
    #                       reactant: Well | Bimolecular,
    #                       product: Well | Bimolecular,
    #                       units) -> list[str]:
    #     """Adapt Mess reaction rate to cantera unit system.

    #     Args:
    #         bar (Barrier): barrier corresponding to the reactions
    #         units (_type_): [forward, reverse]

    #     Returns:
    #         list[str]: reaction rates[forward, backward]
    #     """
    #     From: int = self.KIN.tbl_map[reactant.name]
    #     To: int = self.KIN.tbl_map[product.name]
    #     f_rates: np.ndarray = deepcopy(self.KIN.rc[:, :, From, To])
    #     r_rates: np.ndarray = deepcopy(self.KIN.rc[:, :, To, From])
    #     if 'm^3' in units[0]:
    #         f_rates *= Avogadro / 1000
    #     if 'm^3' in units[1]:
    #         r_rates *= Avogadro / 1000
    #     f_rates_yaml: str = ''
    #     r_rates_yaml: str = ''

    #     for pindex in range(len(self.KIN.set["rc_pres"])):
    #         for tindex in range(len(self.KIN.set["rc_temp"])):
    #             f_rates_yaml += f'rc_{pindex}_{tindex}: ' +\
    #                             f'{f_rates[pindex,tindex]}' + '\n'
    #             r_rates_yaml += f'rc_{pindex}_{tindex}: ' +\
    #                             f'{r_rates[pindex,tindex]}' + '\n'
    #     return [f_rates_yaml, r_rates_yaml]

    # def get_std_unit(self,
    #                  unit: str) -> str:
    #     """Change any unit into Cantera standard system of units.

    #     Args:
    #         unit (str): any unit

    #     Returns:
    #         str: string of the standard unit
    #     """
    #     std_unit: str = ''
    #     full_dim: dict = ct.Units(unit).dimensions
    #     for dim, exp in full_dim.items():
    #         if exp != 0.0:
    #             std_unit += f' {self.ct_unitSystem[dim]}^{exp} *'
    #     std_unit: str = std_unit[1:-2]

    #     return std_unit

    # def init_sims(self) -> None:
    #     """A simulation is created for each PT combination.
    #     Loops through P first and then T to create sim index.
    #     """
    #     reactions: list[ct.Reaction] = [r for r in self.final_sim.reactions()]
    #     species: list[ct.Species] = [s for s in self.final_sim.species()]
    #     simid = 0
    #     for p in self.SOP.rc_pres:
    #         for t in self.SOP.rc_temp:
    #             simid += 1
    #             name: str = f'sim{simid}'
    #             new_sim = ct.Solution(name=name,
    #                                   thermo='ideal-gas',
    #                                   kinetics='gas',
    #                                   species=species,
    #                                   reactions=reactions)
    #             # The pressure given to this simulation is
    #             # likely in the wrong unit (unless Pa),
    #             # but is converted in the cantera job
    #             new_sim.TP = t, p
    #             self.simulations.append(new_sim)

    # def q_up(self) -> None:
    #     """Send job to the queuing system.
    #     """
    #     cpu: int = self.settings['cpu_sim']
    #     mem: int = self.settings['mem_sim']
    #     for idx, sim in enumerate(self.simulations):
    #         sim_id: int = idx + self.id * len(self.simulations)
    #         self.serialize(sim=sim,
    #                        name=self.name+f'S{idx:02d}',
    #                        sim_id=sim_id)
    #         self.q_sys.add_to_q(name=self.name+f'S{idx:02d}',
    #                             idx=sim_id,
    #                             location=self.loc,
    #                             jtype='sim',
    #                             ressources=(cpu, mem))
    #         self.set_status(idx)

    def q_up(self) -> None:
        """Send job to the queuing system.
        """
        cpu: int = self.settings['cpu_sim']
        mem: int = self.settings['mem_sim']
        time_steps: list[int] = \
            [len(i[0]) for i in self.settings['exp_profiles']]
        ct_job: str = self.ctjobtpl.format(
            init_loc=self.settings['init_loc'],
            input_file=self.settings['input_file'],
            el_num=self.id,
            db=self.db,
            tbl_map=self.KIN.tbl_map,
            rates=self.KIN.rc.tolist(),
            time=self.settings['exp_profiles']
            [:][0].tolist(),
            all_tsteps=time_steps,
            gen_name=self.gen_name,
            to_watch=self.sv_species,
            initial_X=self.settings['initial_X'],
            pres_unit=self.settings['pres_unit']
            )
        with open(f'{self.loc}/{self.name}.py', 'w') as f:
            f.write(ct_job)
        self.q_sys.add_to_q(name=self.name,
                            idx=self.id,
                            location=self.loc,
                            jtype='sim',
                            ressources=(cpu, mem))
        self.set_status()

    # def requeue(self,
    #             idx: int,
    #             sim_id: int) -> None:
    #     """Resend a specific simulation to the queuing system.

    #     Args:
    #         sim (int): index of the simulation in this object
    #         sim_id (int):
    #             index of the simulation in queing system
    #     """
    #     cpu: int = self.settings['cpu_sim']
    #     mem: int = self.settings['mem_sim']
    #     sim = self.simulations[idx]
    #     sim_id: int = idx + self.id * len(self.simulations)
    #     self.serialize(sim=sim,
    #                    name=self.name+f'S{idx:02d}',
    #                    sim_id=sim_id)
    #     self.q_sys.add_to_q(name=self.name+f'S{idx:02d}',
    #                         idx=sim_id,
    #                         location=self.loc,
    #                         jtype='sim',
    #                         ressources=(cpu, mem))
    #     self.set_status(idx)

    # def serialize(self,
    #               sim: ct.Solution,
    #               name: str,
    #               sim_id: int) -> None:
    #     """Create the python job and the pkl file.

    #     Args:
    #         sim (ct.Solution): cantera simulation object
    #         name (str): base of filename
    #         sim_id (int): sim id unique accross a generation
    #     """
    #     time_steps: list[int] = \
    #         [len(i[0]) for i in self.settings['exp_profiles']]
    #     exp: int = sim_id % len(self.simulations)
    #     ct_job: str = self.ctjobtpl.format(
    #         db=self.db,
    #         sim_name=name,
    #         sim_id=sim_id,
    #         el_num=self.id,
    #         time=self.settings['exp_profiles']
    #         [exp][0].tolist(),
    #         all_tsteps=time_steps,
    #         gen_name=self.gen_name,
    #         to_watch=self.sv_species,
    #         initial_X=self.settings['initial_X'][exp],
    #         pres_unit=self.settings['pres_unit']
    #         )
    #     with open(f'{self.loc}/{name}.py', 'w') as f:
    #         f.write(ct_job)
    #     with open(f'{self.loc}/{name}.pkl', 'wb') as pkl_file:
    #         pickle.dump(sim, pkl_file)

    def set_status(self) -> None:

        self.status = [self.q_sys.status(
            id=self.id,
            jtype='sim')]\
            * len(self.settings['rc_pres'])\
            * len(self.settings['rc_temp'])
