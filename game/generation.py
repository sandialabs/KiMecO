import os
from typing import Any

from game.element import Element
from game.parameters import SOP
from game.database.game_db import Game_db
from game.well import Well
from game.barrier import Barrier
import numpy as np
import numpy.typing as npt
from numpy import bool_

from game.q_sys import QueueingSystem
from game.rate_coef import RateCo
from game.simulation import SIM


class Generation:
    __id = 0

    def __init__(self,
                 elements: list[Element],
                 set: dict[str, Any],
                 rc_tpl: list[str],
                 loc: str,
                 sop_db: Game_db,
                 kin_db: Game_db,
                 sim_db: Game_db
                 ) -> None:
        """Generation object manages the worflow of
        a given set of elements, going from creating them
        (perturbed SOPs) to calculating the rate constants
        and doing the cantera Simulation

        Args:
            sop (SOP): Initial set of parameters to be perturbed
            n (int): number of elements in the generation
            pert (Perturbator): Perturbator object used to perturb the SOP
                                of this generation
            set (dict): Settings.
            rc_tpl: Template for rate constant calculation.
            loc: Location. Absolute path of where the gen folder should be.
        """
        self.elements: list[Element] = elements
        self.id: int = Generation.__id
        Generation.__id += 1
        self.species: list[str] = [
            self.elements[0].sop.items[specie].ct_name
            for specie, obj in self.elements[0].sop.items.items()
            if isinstance(obj, Well) and not isinstance(obj, Barrier)]
        self.settings: dict[str, Any] = set
        self.rc_tpl: list[str] = rc_tpl
        self.loc: str = loc
        self.best_score: float = np.inf
        if not os.path.isdir(f'{self.loc}/G{self.id}'):
            os.mkdir(f'{self.loc}/G{self.id}')
        os.chdir(f'{self.loc}/G{self.id}')
        self.sop_db: Game_db = sop_db
        self.kin_db: Game_db = kin_db
        self.sim_db: Game_db = sim_db
        self.create_tables()
        self.save_sops()
        self.qs = QueueingSystem(max_jobs=self.settings['max_jobs'],
                                 max_cpu=self.settings['max_cpu'],
                                 max_mem=self.settings['max_mem'],
                                 cpu_kin=self.settings['cpu_kin'],
                                 mem_kin=self.settings['mem_kin'],
                                 cpu_sim=self.settings['cpu_sim'],
                                 mem_sim=self.settings['mem_sim'],
                                 nkin=len(self.elements),
                                 nsim=len(self.elements) *
                                 len(self.settings['rc_temp']) *
                                 len(self.settings['rc_pres'])
                                 )

    def create_tables(self) -> None:
        """Create the tables in all databases
        """
        # Create table for gen in SOP, KIN and SIM
        # SOP
        self.sop_db.create_table(
            name=f'G{self.id}',
            columns=[key for key in 
                     self.elements[0].sop.parameters_names.keys()],
            types=[type(val) for val in 
                   self.elements[0].sop.parameters_names.values()]
            )
        # KIN
        kin_col: list[str] = ['P', 'T', 'kin_id', 'specie']
        kin_col.extend(self.elements[0].sop.wells_names)
        kin_col.extend(self.elements[0].sop.bimols_names)
        kin_types: list = [float, float, str, str]
        kin_types.extend([float for i in range(
            len(self.elements[0].sop.wells_names) +
            len(self.elements[0].sop.bimols_names))])
        self.kin_db.create_table(
            name=f'G{self.id}',
            columns=kin_col,
            types=kin_types
            )
        # SIM
        sim_col: list[str] = ['P', 'T', 'sim_id', 'time']
        sim_col.extend(self.species)
        sim_types = [int, float, float, int, float]
        sim_types.extend([float for i in range(len(self.species))])
        self.sim_db.create_table(
            name=f'G{self.id}',
            columns=sim_col,
            types=sim_types
            )

    def save_sops(self) -> None:
        """Save all the SOPs of all elements in the db.
        """
        for el in self.elements:
            # Creates an Element from a perturbed SOP and save it in the db
            el.save_sop(db=self.sop_db,
                        table=f'G{self.id}',
                        mode=self.settings['restart'])

    def run(self) -> None:
        """Run a generation until all of its elements are scored.

        Args:
            q_sys (QueueingSystem): Queueing system in charge of managing
                                    the ressources and running as many jobs
                                    in parallel as possible.
        """
        finished: npt.NDArray[bool_] = np.full(shape=(len(self.elements), 1),
                                               fill_value=False)
        while not all(finished):
            for idx, el in enumerate(self.elements):
                # Skip finished elements
                if finished[idx]:
                    continue
                # Calculate rate coefficients
                if el.status == 'sop':
                    el.rateCoef = RateCo(sop=el.sop,
                                         settings=self.settings,
                                         software_tpl=self.rc_tpl,
                                         id=el.id,
                                         name=f'G{self.id}E{el.id}',
                                         loc=f'{self.loc}/G{self.id}',
                                         q_sys=self.qs,
                                         db=self.kin_db)
                    el.rateCoef.q_up()
                    el.status = 'kin'
                # Recover rate coefficients
                elif el.status == 'kin':
                    el.rateCoef.set_status()
                    if el.rateCoef.status == 'finished':
                        el.save_kin(db=self.kin_db,
                                    table=f'G{self.id}')
                        el.status = 'kin2sim'
                # Calculate SIMs
                elif el.status == 'kin2sim':
                    el.sim = SIM(sop=el.sop,
                                 kin=el.rateCoef,
                                 id=el.id,
                                 db=self.sim_db,
                                 gen_id=self.id,
                                 species=self.species,
                                 loc=f'{self.loc}/G{self.id}',
                                 q_sys=self.qs,
                                 set=self.settings)
                    el.sim.q_up()
                    el.status = 'sim'
                # Recover simulations data
                elif el.status == 'sim':
                    for sim in range(len(el.sim.simulations)):
                        el.sim.set_status(sim=sim)
                    if all([True if status == 'finished' else False
                            for status in el.sim.status]):
                        el.recover_sim_profiles(db=self.sim_db,
                                                table=f'G{self.id}')
                        el.status = 'scoring'
                # Scoring
                elif el.status == 'scoring':
                    el.calc_score(settings=self.settings)
                    el.status = 'DONE'
                elif el.status == 'DONE':
                    finished[idx] = True
                    if el.score < self.best_score:
                        self.best_score: float = el.score
            self.qs.run()
