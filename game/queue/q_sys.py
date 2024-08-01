from game.templates.slurm_pyjob import tpl
from subprocess import Popen, PIPE
import pickle
from game import game_path
import cantera as ct


class QueueingSystem:
    def __init__(self,
                 max_jobs: int,
                 max_cpu: int,
                 max_mem: int,
                 cpu_job: int = 1,
                 mem_job: float = 500.0,
                 location: str | None = None
                 ) -> None:

        self.queue: list = []
        self.max_jobs: int = max_jobs
        self.max_cpu: int = max_cpu
        self.max_mem: int = max_mem
        self.cpu_job: int = cpu_job
        self.mem_job: float = mem_job
        self.location: str | None = location
        self.sub_tpl: str = tpl
        with open(f'{game_path}/templates/ct_job.tpl') as f:
            self.pyjob_tpl: str = f.read()

    def submit(self,
               sim: ct.Solution,
               id: str
               ) -> None:
        self.serialize_sim(sim=sim,
                           name=f'sim_{id}')

    def serialize_sim(self,
                      sim: ct.Solution,
                      name: str) -> None:
        with open(f'{self.location}/{name}.pkl', 'wb') as pkl_file:
            pickle.dump([sim], pkl_file)
