from typing import Any
from numpy.typing import NDArray
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.rate_coef import RateCo
from kimeco.templates.sim_arr_tpl import ctjobtpl
from logging import Logger


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCo,
                 id: int,
                 gen_name: str,
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
        self.status: JobStatus = JobStatus.NOT_IN_QUEUE
        self.gen_name: str = gen_name
        self.SOP: SOP = sop
        self.KIN: RateCo = kin
        self.id: int = id
        self.settings: dict[str, Any] = set
        # Species to save in db
        self.sc_species: list[str] = sc_species
        self.el_name: str = f'E{id:04d}'
        self.name: str = f'{gen_name}{self.el_name}S'
        self.loc: str = loc + f'/{(self.id)//50:02d}'
        self.q_sys: QueueingSystem = q_sys
        self.ctjobtpl: str = ctjobtpl
        self.db: SIM_DB = db
        self.profiles: list[NDArray | None] = [
            None] * len(set['exp_profiles'])

    def q_up(self) -> None:
        """Send job to the queuing system.
        """
        cpu: int = self.settings['cpu_sim']
        mem: int = self.settings['mem_sim']
        time_steps: list[int] = \
            [len(i[0]) for i in self.settings['exp_profiles']]
        times = []
        for exp in self.settings['exp_profiles']:
            times.append(exp[0].tolist())
        scratchdir: str = self.settings['scratch_base'] +\
                          self.settings["project_name"] + '/' +\
                          self.name
        ct_job: str = self.ctjobtpl.format(
            init_loc=self.settings['init_loc'],
            input_file=self.settings['input_file'],
            scratchdir=scratchdir,
            el_num=self.id,
            db=self.db,
            tbl_map=self.KIN.tbl_map,
            rates=self.KIN.rc.tolist(),
            time=times,
            all_tsteps=time_steps,
            gen_name=self.gen_name,
            to_watch=self.sc_species
            )
        with open(f'{self.loc}/{self.name}.py', 'w') as f:
            f.write(ct_job)
        self.q_sys.add_to_q(name=self.name,
                            idx=self.id,
                            location=self.loc,
                            jtype='sim',
                            ressources=(cpu, mem))
        self.set_status()

    def set_status(self) -> None:

        self.status = self.q_sys.status(
            id=self.id,
            jtype='sim')
