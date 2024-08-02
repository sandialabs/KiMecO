from operator import index
import os
from game.queue.job import Job
from game.templates.pyjob import pytpl
from game.templates.messjob import messtpl
from game.templates.slurm import slurmtpl
from subprocess import Popen, PIPE
import numpy as np
from numpy.typing import NDArray
from numpy import int64
import getpass


class QueueingSystem:
    def __init__(self,
                 max_jobs: int,
                 max_cpu: int,
                 max_mem: int,
                 cpu_job: int = 1,
                 mem_job: float = 500.0,
                 q_type: str = 'slurm',
                 q_name: str = 'day-long-cpu'
                 ) -> None:
        """The queueing system is only meant to manage the number of jobs
        and the ressources used by the workflow. The run() method should only submit jobs
        to use a maximum of ressources. But it should not:
        - Do science
        - Write files

        File writting should be done by other instances of GAME, which will be
        visited when the ressources are fully used
        or when the work queue is empty.

        Args:
            max_jobs (int): Max number of jobs to be used by the WF.
            max_cpu (int): Max number of cpu to be used by the WF
            max_mem (int): Max quantity of memory (Mb) to be used by the WF
            cpu_job (int, optional): Number of cpu used for each job.
                                     Defaults to 1.
            mem_job (float, optional): Quantity of memory (Mb) used
                                       for each job. Defaults to 500.0.
            location (str, optional): Where jobs should be submitted from.
                                      Defaults to local.
        """

        self.av_jobs: int = max_jobs
        self.av_cpu: int = max_cpu
        self.av_mem: int = max_mem
        self.cpu_job: int = cpu_job
        self.mem_job: float = mem_job
        if q_type.casefold() == 'slurm':
            self.subtpl: str = slurmtpl
            self.ext: str = 'slurm'
        else:
            raise NotImplementedError('Slurm is the only q_type available.')
        self.pytpl: str = pytpl
        self.messtpl: str = messtpl
        self.q_name: str = q_name
        self.queue: list[Job] = []
        self.to_rmv: list[int] = []
        self.submitted: int = 0
        self.running: int = 0
        self.n_ready: int = 0

    def add_to_q(self,
                 id: str,
                 location: str,
                 jtype: str,
                 ressources: tuple[int, int]
                 ) -> None:
        """Create the submission file when job is added to queue.
           Job file itself must have already been created by the submitting
           instance.

        Args:
            location (str): Absolute path to the folder
            filename (str): filename without extension
            jtype (str): <kin> (for kinetic) or <sim> (simulation)
            ressources (tuple[int, int]): number of CPU and memory (Mb)
        """
        cpu: int
        mem: int  # In Mb
        (cpu, mem) = ressources
        job = Job(name=id,
                  location=location,
                  cpu=cpu,
                  mem=mem,
                  jtype=jtype)
        self.create_sub_file(job=job)
        self.queue.append(job)
        self.n_ready += 1

    def create_sub_file(self,
                        job: Job
                        ) -> None:
        sub_cmd: str = self.subtpl.format(nprocs=job.cpu,
                                          filename=job.name,
                                          sub_queue=self.q_name,
                                          mem_mb=job.mem
                                          )
        if job.type == 'kin':
            job_cmd: str = self.messtpl.format(filename=job.name)
        elif job.type == 'sim':
            job_cmd: str = self.pytpl.format(filename=job.name)

        sub_file: str = sub_cmd + job_cmd

        with open(f'{job.loc}/{job.name}.{self.ext}', 'w') as f:
            f.write(sub_file)

    def submit(self,
               job: Job) -> None:
        """Go in the submission directory,
        submit the job, and return the slurm's job id.
        Set the Job's status to <running>.

        Args:
            job contains:
            location (str): Submission directory. Absolute path.
            filename (str): Submission script name, without extension.

        """
        os.chdir(job.loc)
        command: list[str] = ['sbatch', job.name+'.'+self.ext]
        process = Popen(args=command,
                        shell=False,
                        stdout=PIPE,
                        stdin=PIPE,
                        stderr=PIPE)
        out, err = process.communicate()
        outstr: str = out.decode()
        slurm_id: int = int(outstr.split()[-1])
        job.sub_id = slurm_id
        job.status = 'running'
        self.av_cpu -= job.cpu
        self.av_mem -= job.mem
        self.av_jobs -= 1
        self.n_ready -= 1

    def run(self) -> None:
        """Run all jobs of the workflow in parallel
        as long as ressources are available.
        """
        for job in self.queue:
            if job.status == 'ready':
                if self.enough_ressources_for(job):
                    self.submit(job)
                else:
                    self.actualize()
                    self.clean()
                    break
        if self.n_ready < self.av_jobs:
            self.actualize()
            self.clean()

    def clean(self) -> None:
        """Costly opration!
        Remove pickedUp jobs from the queue,
        which displaces all elements in the queue.
        """
        for i in reversed(self.to_rmv):
            self.queue.pop(i)

        self.to_rmv = []

    def enough_ressources_for(self,
                              job: Job) -> bool:
        if self.av_jobs > 0 \
         and self.av_cpu > job.cpu\
         and self.av_mem > job.mem:
            return True
        else:
            return False

    def actualize(self) -> None:
        """Remove picked up jobs from queuing system.
        Change status of newly finished jobs.
        """
        slurm_ids: NDArray[int64] = self.get_all_running()
        for i, job in enumerate(self.queue):
            if job.status == 'ready':
                continue
            elif job.status == 'pickedUp':
                self.to_rmv.append(i)
            elif job.status == 'running' and not any(slurm_ids == job.sub_id):
                job.status = 'finished'
                self.av_cpu += job.cpu
                self.av_mem += job.mem
                self.av_jobs += 1

    def get_all_running(self) -> NDArray[int64]:
        """Create numpy array of job ids for fast comparaison
        with job ids in running list

        Returns:
            NDArray[int64]: job ids in return of command squeue -u user
        """
        process = Popen(args=['squeue', '-u', f'{getpass.getuser()}'],
                        shell=False,
                        stdout=PIPE,
                        stdin=PIPE,
                        stderr=PIPE)
        out, err = process.communicate()
        jobs: list[str] = out.decode().split('\n')[1:]
        slurm_ids: NDArray[int64] = np.zeros(len(jobs), dtype=np.int64)
        for i, j in enumerate(jobs):
            slurm_ids[i] = int(j.split()[0])
        return slurm_ids
    
    def status(self,
               id: str) -> str:
        for job in self.queue:
            if job.name == id:
                return job.status
        raise KeyError(f'Job {id} is not present in the queue anymore.')

    # def submit(self,
    #            sim: ct.Solution,
    #            id: str
    #            ) -> None:
    #     self.serialize_sim(sim=sim,
    #                        name=f'sim_{id}')

    # def serialize_sim(self,
    #                   sim: ct.Solution,
    #                   name: str) -> None:
    #     with open(f'{self.location}/{name}.pkl', 'wb') as pkl_file:
    #         pickle.dump([sim], pkl_file)
