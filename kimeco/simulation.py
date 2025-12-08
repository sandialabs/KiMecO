from typing import Any
from numpy.typing import NDArray
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.rate_coef import RateCo
from kimeco.templates.sim_arr_tpl import ctjobtpl
from kimeco.logger_config import KMOLogger


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCo,
                 id: int,
                 q_idx: int,
                 gen_name: str,
                 sc_species: list[str],
                 db: SIM_DB,
                 loc: str,
                 q_sys: QueueingSystem,
                 set: dict[str, Any],
                 klog: KMOLogger
                 ) -> None:
        """Handles the simulations.

        Args:
            sop (SOP): Set of Master equation parameters
            kin (RateCo): Rate coefficients object
            id (int): Identifier of the simulation
            q_idx (int): Queuing system index
            gen_name (str): Name of the generation
            sc_species (list[str]): Species to score
            db (SIM_DB): Simulation database
            loc (str): Where to store the simulation files
            q_sys (QueueingSystem): Queuing system
            set (dict[str, Any]): Settings
            klog (KMOLogger): Logger
        """
        self.klog: KMOLogger = klog
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
        self.q_idx: int = q_idx

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
                            idx=self.q_idx,
                            location=self.loc,
                            jtype='sim',
                            ressources=(cpu, mem))
        self.set_status()

    def set_status(self) -> None:

        self.status = self.q_sys.status(
            id=self.q_idx,
            jtype='sim')
