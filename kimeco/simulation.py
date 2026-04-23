from typing import Any
from numpy.typing import NDArray
from kimeco.database.sim_db import SIM_DB
from kimeco.parameters import SOP
from kimeco.q_sys import QueueingSystem, JobStatus
from kimeco.rate_coef import RateCo
from kimeco.logger_config import KMOLogger


class SIM:
    def __init__(self,
                 sop: SOP,
                 kin: RateCo,
                 id: int,
                 q_idx: int,
                 gen_name: str,
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
        self.el_name: str = f'E{id:04d}'
        self.name: str = f'{gen_name}{self.el_name}S'
        self.loc: str = loc + f'/{(self.id)//50:02d}'
        self.q_sys: QueueingSystem = q_sys
        self.db: SIM_DB = db
        self.profiles: list[NDArray | None] = [
            None] * len(set['experiments'])
        self.q_idx: int = q_idx

    def q_up(self) -> None:
        """Send job to the queuing system.
        """
        cpu: int = self.settings['cpu_sim']
        mem: int = self.settings['mem_sim']
        time_steps: list[int] = [
            len(exp.data[0]) for exp in self.settings['experiments']
        ]
        times = [
            exp.data[0].tolist() for exp in self.settings['experiments']
        ]
        to_watch = [exp.species for exp in self.settings['experiments']]
        rates_by_pes = {
            int(pes_id): rates.tolist()
            for pes_id, rates in getattr(self.KIN, 'rc_by_pes').items()
        }
        tbl_map_by_pes = {
            int(pes_id): tbl_map
            for pes_id, tbl_map in getattr(self.KIN, 'tbl_map_by_pes').items()
        }
        scratchdir: str = (
            self.settings['scratch_base']
            + self.settings['project_name']
            + '/'
            + self.name
        )
        for exp_id, exp in enumerate(self.settings['experiments']):
            ct_job: str = exp.sim_file.format(
                init_loc=self.settings['init_loc'],
                input_file=self.settings['input_file'],
                scratchdir=scratchdir,
                el_num=self.id,
                db=self.db,
                tbl_map_by_pes=tbl_map_by_pes,
                rates_by_pes=rates_by_pes,
                time=times,
                all_tsteps=time_steps,
                gen_name=self.gen_name,
                to_watch=to_watch
            )
            script_name = f'{self.name}_{exp_id:02d}.py'
            with open(f'{self.loc}/{script_name}', 'w') as f:
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


class SIM_PP(SIM):
    def __init__(self,
                 sop: SOP,
                 kin: RateCo,
                 id: int,
                 q_idx: int,
                 gen_name: str,
                 pp_species: list[str],
                 db: SIM_DB,
                 loc: str,
                 q_sys: QueueingSystem,
                 set: dict[str, Any],
                 klog: KMOLogger
                 ) -> None:
        super().__init__(
            sop=sop,
            kin=kin,
            id=id,
            q_idx=q_idx,
            gen_name=gen_name,
            db=db,
            loc=loc,
            q_sys=q_sys,
            set=set,
            klog=klog,
        )
        self.pp_species = pp_species
        self.ctjobtpl = self.settings['cantera_tpl']
        self.profiles = [
            None] * (
                len(self.settings['pp_pres']) *
                len(self.settings['pp_temp'])
            )

    def q_up(self) -> None:
        cpu: int = self.settings['cpu_sim']
        mem: int = self.settings['mem_sim']
        time_steps: list[int] = [
            len(times) for times in self.settings['pp_times']
        ]
        scratchdir: str = (
            self.settings['scratch_base']
            + self.settings['project_name']
            + '/'
            + self.name
        )
        rates_by_pes = {
            int(pes_id): rates.tolist()
            for pes_id, rates in getattr(self.KIN, 'rc_by_pes').items()
        }
        tbl_map_by_pes = {
            int(pes_id): tbl_map
            for pes_id, tbl_map in getattr(self.KIN, 'tbl_map_by_pes').items()
        }
        ct_job: str = self.ctjobtpl.format(
            init_loc=self.settings['init_loc'],
            input_file=self.settings['input_file'],
            scratchdir=scratchdir,
            el_num=self.id,
            db=self.db,
            tbl_map_by_pes=tbl_map_by_pes,
            rates_by_pes=rates_by_pes,
            time=self.settings['pp_times'],
            all_tsteps=time_steps,
            gen_name=self.gen_name,
            to_watch=self.pp_species,
            initial_x=self.settings['pp_initial_X'],
        )
        with open(f'{self.loc}/{self.name}.py', 'w') as f:
            f.write(ct_job)
        self.q_sys.add_to_q(name=self.name,
                            idx=self.q_idx,
                            location=self.loc,
                            jtype='sim',
                            ressources=(cpu, mem))
        self.set_status()
